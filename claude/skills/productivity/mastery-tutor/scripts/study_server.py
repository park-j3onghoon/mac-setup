"""Serve the single-page local study room. No browser activation or external hosting."""

import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from learning_store import Store, StoreError
from study_jobs import Jobs
from study_images import image_path
from study_runner import available_providers
from study_view import session_detail, session_summary

ASSETS = Path(__file__).resolve().parent.parent / 'assets'


def render_html(token):
    html = (ASSETS / 'study.html').read_text()
    scripts = ['vendor/marked/marked.umd.js', 'vendor/dompurify/purify.min.js',
               'study_markdown.js', 'study_images.js', 'study.js']
    javascript = '\n;\n'.join((ASSETS / path).read_text() for path in scripts)
    javascript = re.sub(r'</script', r'<\\/script', javascript, flags=re.IGNORECASE)
    return html.replace('/* STUDY_CSS */', (ASSETS / 'study.css').read_text()).replace(
        '/* STUDY_JS */', javascript).replace('__STUDY_TOKEN__', token)


def load_token(web):
    path = web / 'access-token'
    token = path.read_text().strip() if path.exists() else ''
    if not token and (web / 'index.html').exists():
        previous = re.search(r"const STUDY_TOKEN = '([A-Za-z0-9_-]{43})'", (web / 'index.html').read_text())
        token = previous.group(1) if previous else ''
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        token = secrets.token_urlsafe(32)
    Store.atomic_text(path, token)
    return token


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, status, value, content_type='application/json; charset=utf-8'):
        if isinstance(value, bytes):
            body = value
        elif isinstance(value, str):
            body = value.encode()
        else:
            body = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('X-Frame-Options', 'DENY')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data: blob:; frame-src 'self' about:; "
                         "base-uri 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self):
        host = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != host:
            return False
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{host}':
            return False
        return self.headers.get('Sec-Fetch-Site') not in ('cross-site',)

    def do_GET(self):
        try:
            if not self.allowed():
                return self.reply(403, {'error': '이 컴퓨터의 학습 화면에서 접속해 주세요.'})
            path = urlsplit(self.path).path
            if path == '/':
                return self.reply(200, self.server.html, 'text/html; charset=utf-8')
            if path == '/health':
                return self.reply(200, {'service': 'mastery-tutor', 'root': str(self.server.store.root)})
            if path == '/api/connection':
                return self.reply(200, {'token': self.server.token})
            if self.headers.get('X-Study-Token') != self.server.token:
                return self.reply(403, {'error': '학습 화면을 다시 열어 주세요.'})
            self.get_data(path)
        except (StoreError, ValueError, KeyError, TypeError) as error:
            self.reply(400, {'error': str(error)})

    def get_data(self, path):
        if path.startswith('/api/images/'):
            return self.get_image(path.removeprefix('/api/images/'))
        if path == '/api/providers':
            return self.reply(200, {'providers': available_providers()})
        if path.startswith('/api/events/'):
            return self.stream_updates(path.removeprefix('/api/events/'))
        if path == '/api/sessions':
            records = self.server.store.records('sessions')
            return self.reply(200, {'sessions': [session_summary(record) for record in records]})
        if path.startswith('/api/conversations/'):
            session_id = Store.valid_id(path.removeprefix('/api/conversations/'))
            if not self.server.store.read('sessions', session_id):
                return self.reply(404, {'error': '학습 기록을 찾지 못했습니다.'})
            query = parse_qs(urlsplit(self.path).query)
            before = query.get('before', [None])[0]
            jobs = self.server.jobs.history(session_id)
            limit = None if query.get('all') == ['1'] else 1
            return self.reply(200, self.server.jobs.conversation_page(jobs, before=before, limit=limit))
        if path.startswith('/api/sessions/'):
            session_id = path.removeprefix('/api/sessions/')
            record = self.server.store.read('sessions', session_id)
            if not record:
                return self.reply(404, {'error': '학습 기록을 찾지 못했습니다.'})
            cards = {card['id']: card for card in self.server.store.records('concepts')}
            detail = session_detail(record, cards)
            question_ids = [question['id'] for question in detail['questions']]
            detail.update(self.server.jobs.session_history(session_id, question_ids))
            return self.reply(200, detail)
        self.reply(404, {'error': '페이지를 찾지 못했습니다.'})

    def get_image(self, path):
        job_id, image_id = path.split('/')
        job = self.server.store.read_json(self.server.jobs.directory / Store.valid_id(job_id) / 'job.json')
        images = job.get('request', {}).get('images', []) if job else []
        metadata = next((image for image in images if image['id'] == image_id), None)
        if not metadata:
            return self.reply(404, {'error': '이미지를 찾지 못했습니다.'})
        file = image_path(self.server.jobs.directory, metadata)
        try:
            return self.reply(200, file.read_bytes(), metadata['mime_type'])
        except OSError:
            return self.reply(404, {'error': '이미지 파일을 찾지 못했습니다.'})

    def stream_updates(self, session_id):
        if not self.server.store.read('sessions', Store.valid_id(session_id)):
            return self.reply(404, {'error': '학습 기록을 찾지 못했습니다.'})
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        previous = None
        try:
            while True:
                job, version = self.server.jobs.snapshot(session_id)
                message = json.dumps({'job': job}, ensure_ascii=False)
                packet = f'event: job\ndata: {message}\n\n' if message != previous else ': keepalive\n\n'
                self.wfile.write(packet.encode('utf-8'))
                self.wfile.flush()
                previous = message
                self.server.jobs.wait_for_update(session_id, version)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    def do_POST(self):
        try:
            if not self.allowed() or self.headers.get('X-Study-Token') != self.server.token:
                return self.reply(403, {'error': '학습 화면에서 다시 제출해 주세요.'})
            path = urlsplit(self.path).path
            if path not in ('/api/submit', '/api/cancel'):
                return self.reply(404, {'error': '요청 경로를 찾지 못했습니다.'})
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 26 * 1024 * 1024:
                return self.reply(413, {'error': '요청 크기를 줄여 주세요.'})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict) or not isinstance(payload.get('answers', {}), dict):
                raise StoreError('올바른 답안 형식이 아닙니다.')
            action = self.server.jobs.cancel if path == '/api/cancel' else self.server.jobs.submit
            self.reply(202, action(payload))
        except (StoreError, ValueError, KeyError, TypeError) as error:
            self.reply(409, {'error': str(error)})


def serve(root, port):
    store = Store(root, holder='web:study')
    web = store.root / 'web'
    web.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (web / 'server.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        server.store = store
        server.jobs = Jobs(store.root)
        server.token = load_token(web)
        server.html = render_html(server.token)
        url = f'http://127.0.0.1:{server.server_port}/'
        redirect = f'<script>if(location.protocol === "file:") location.replace("{url}");</script>'
        store.atomic_text(web / 'index.html', server.html.replace('<head>', '<head>' + redirect))
        store.atomic_json(web / 'server.json', {'url': url, 'pid': os.getpid()})
        print(url, flush=True)
        server.serve_forever()


def running_url(root):
    store = Store(root)
    metadata = store.read_json(store.root / 'web/server.json')
    if not metadata:
        return None
    try:
        with urlopen(metadata['url'] + 'health', timeout=1) as response:
            health = json.load(response)
        if health == {'service': 'mastery-tutor', 'root': str(store.root)}:
            return metadata['url']
    except (OSError, ValueError):
        pass
    return None


def start(root, port):
    existing = running_url(root)
    if existing:
        return print(existing)
    web = Store(root).root / 'web'
    web.mkdir(parents=True, exist_ok=True, mode=0o700)
    command = [sys.executable, str(Path(__file__).resolve()), 'serve',
               '--root', str(root), '--port', str(port)]
    with (web / 'server.log').open('a') as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
    for _ in range(30):
        time.sleep(0.1)
        url = running_url(root)
        if url:
            return print(url)
        if process.poll() is not None:
            break
    raise StoreError(f'학습 화면을 시작하지 못했습니다. 로그: {web / "server.log"}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['start', 'serve', 'status'])
    parser.add_argument('--root', default=str(Store().root))
    parser.add_argument('--port', type=int, default=8766)
    args = parser.parse_args()
    root = Path(args.root).expanduser().resolve()
    if args.command == 'serve':
        serve(root, args.port)
    elif args.command == 'start':
        start(root, args.port)
    else:
        print(running_url(root) or 'stopped')


if __name__ == '__main__':
    main()
