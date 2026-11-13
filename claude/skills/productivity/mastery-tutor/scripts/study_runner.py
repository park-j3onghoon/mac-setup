"""Provider-specific CLI streams; publish only learner-facing reply text."""

import json
import base64
from datetime import datetime, timezone
import os
import re
import selectors
import shutil
import subprocess
import threading
import time

from learning_store import StoreError
from study_cancel import check_cancelled

PROVIDERS = {'codex': 'Codex', 'claude': 'Claude'}
CODEX_MODEL = 'gpt-6.1-sol'
CODEX_REASONING_EFFORT = 'xhigh'
CODEX_SERVICE_TIER = 'default'


class RetryableProviderError(StoreError):
    """A transient provider failure before any learning checkpoint is committed."""


def provider_failure(message):
    text = message.lower()
    permanent = ('unauthorized', 'authentication', 'login', 'quota', 'usage limit', 'credit',
                 'permission', 'access denied', 'context length', 'context window', 'billing')
    if re.search(r'\b(401|403)\b', text) or any(word in text for word in permanent):
        return StoreError(message)
    transient = ('timeout', 'timed out', 'temporarily', 'connection reset', 'connection closed',
                 'stream disconnected', 'network', 'overloaded', 'failed to connect',
                 'rate limit', 'econnreset', 'etimedout', 'service unavailable')
    if re.search(r'\b(429|500|502|503|504)\b', text) or any(word in text for word in transient):
        return RetryableProviderError(message)
    return StoreError(message)


def available_providers():
    return [{'id': key, 'name': name, 'available': bool(shutil.which(key))}
            for key, name in PROVIDERS.items()]


def provider_name(provider):
    if provider not in PROVIDERS:
        raise StoreError('Codex 또는 Claude를 선택해 주세요.')
    return PROVIDERS[provider]


def provider_command(provider, directory, schema, image_paths=()):
    name = provider_name(provider)
    executable = shutil.which(provider)
    if not executable:
        raise StoreError(f'{name} 실행 파일을 찾지 못했습니다. 다른 AI를 선택해 주세요.')
    if provider == 'claude':
        image_input = ['--input-format', 'stream-json'] if image_paths else []
        return [executable, '--safe-mode', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                '--tools', '', '--disable-slash-commands', '--no-session-persistence', '--no-chrome',
                '-p', '--output-format', 'stream-json', '--verbose', '--include-partial-messages',
                '--json-schema', json.dumps(schema), *image_input]
    schema_path = directory / 'schema.json'
    schema_path.write_text(json.dumps(schema))
    image_flags = []
    for path in image_paths:
        image_flags.extend(['--image', str(path)])
    return [executable, 'exec', '--ignore-user-config', '--sandbox', 'read-only', '--ephemeral',
            '--model', CODEX_MODEL, '-c', f'model_reasoning_effort="{CODEX_REASONING_EFFORT}"',
            '-c', f'service_tier="{CODEX_SERVICE_TIER}"',
            '--skip-git-repo-check', '-C', str(directory), '--output-schema', str(schema_path),
            '--output-last-message', str(directory / 'result.json'), '--color', 'never', '--json',
            *image_flags, '-']


def partial_string(text):
    escaped = False
    for index, char in enumerate(text[1:], 1):
        if char == '"' and not escaped:
            return json.loads(text[:index + 1])
        escaped = char == '\\' and not escaped
    for trim in range(min(7, len(text))):
        candidate = text[:len(text) - trim] + '"'
        try:
            return json.loads(candidate).encode('utf-8', errors='ignore').decode('utf-8')
        except (ValueError, UnicodeError):
            continue
    return ''


def reply_prefix(text):
    remaining = text.lstrip()
    if not remaining.startswith('{'):
        return ''
    decoder = json.JSONDecoder()
    remaining = remaining[1:].lstrip()
    try:
        while remaining and not remaining.startswith('}'):
            key, end = decoder.raw_decode(remaining)
            remaining = remaining[end:].lstrip()
            if not remaining.startswith(':'):
                return ''
            remaining = remaining[1:].lstrip()
            if key == 'reply' and remaining.startswith('"'):
                return partial_string(remaining)
            _, end = decoder.raw_decode(remaining)
            remaining = remaining[end:].lstrip()
            if not remaining.startswith(','):
                return ''
            remaining = remaining[1:].lstrip()
    except ValueError:
        pass
    return ''


class ProviderStream:
    def __init__(self, provider, emit):
        self.provider = provider
        self.emit = emit
        self.result = None
        self.error = ''
        self.blocks = {}
        self.preview = ''
        self.activity_count = 0

    def publish_text(self, text):
        reply = reply_prefix(text)
        if reply and reply != self.preview:
            self.preview = reply
            self.emit({'status': 'responding', 'reply_preview': reply})

    def consume(self, event):
        self.activity_count += 1
        self.emit({'last_activity_at': datetime.now(timezone.utc).isoformat(),
                   'activity_count': self.activity_count})
        if self.provider == 'codex':
            self.consume_codex(event)
        else:
            self.consume_claude(event)

    def consume_codex(self, event):
        item = event.get('item', {})
        if item.get('type') == 'agent_message':
            self.publish_text(item.get('text', ''))
        if event.get('type') in ('turn.failed', 'error'):
            error = event.get('error', event)
            self.error = error.get('message', 'Codex 요청이 실패했습니다.')

    def consume_claude(self, event):
        kind = event.get('type')
        if kind == 'system' and event.get('model'):
            self.emit({'model': event['model']})
        elif kind == 'stream_event' and not event.get('parent_tool_use_id'):
            self.consume_claude_delta(event['event'])
        elif kind == 'assistant' and not event.get('parent_tool_use_id'):
            self.consume_claude_message(event.get('message', {}))
        elif kind == 'result':
            self.result = event.get('structured_output')
            if event.get('is_error'):
                self.error = str(event.get('result') or event.get('errors') or 'Claude 요청이 실패했습니다.')
            if self.result:
                self.publish_text(json.dumps(self.result, ensure_ascii=False))

    def consume_claude_message(self, message):
        for block in message.get('content', []):
            if block.get('type') == 'text':
                self.publish_text(block.get('text', ''))
            if block.get('type') == 'tool_use' and block.get('name') == 'StructuredOutput':
                self.publish_text(json.dumps(block.get('input', {}), ensure_ascii=False))

    def consume_claude_delta(self, event):
        kind = event.get('type')
        index = event.get('index', 0)
        if kind == 'message_start':
            self.blocks = {}
        elif kind == 'content_block_start':
            block = event.get('content_block', {})
            allowed = block.get('type') == 'text' or block.get('name') == 'StructuredOutput'
            self.blocks[index] = {'allowed': allowed, 'text': block.get('text', '')}
        elif kind == 'content_block_delta' and self.blocks.get(index, {}).get('allowed'):
            delta = event.get('delta', {})
            if delta.get('type') in ('text_delta', 'input_json_delta'):
                self.blocks[index]['text'] += delta.get('text', delta.get('partial_json', ''))
                self.publish_text(self.blocks[index]['text'])


def feed_prompt(process, prompt):
    try:
        process.stdin.write(prompt.encode('utf-8'))
    except (BrokenPipeError, OSError):
        pass
    finally:
        try:
            process.stdin.close()
        except (BrokenPipeError, OSError):
            pass


def consume_line(line, stream, log):
    log.write(line + b'\n')
    log.flush()
    try:
        event = json.loads(line)
    except ValueError:
        return
    if isinstance(event, dict):
        stream.consume(event)


def read_stream(process, stream, log, deadline, directory):
    buffered = b''
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            check_cancelled(directory)
            if not selector.select(timeout=max(0, min(1, deadline - time.monotonic()))):
                continue
            data = os.read(process.stdout.fileno(), 65536)
            if not data:
                if buffered:
                    consume_line(buffered, stream, log)
                return
            buffered += data
            while b'\n' in buffered:
                line, buffered = buffered.split(b'\n', 1)
                consume_line(line, stream, log)
            if len(buffered) > 20_000_000:
                raise StoreError('응답이 너무 커 처리를 중단했습니다. 제출한 답은 보존됩니다.')
    raise RetryableProviderError('AI 응답 시간이 초과됐습니다. 제출한 답은 보존됩니다.')


def execute_stream(command, prompt, directory, stream):
    environment = {key: value for key, value in os.environ.items() if not key.startswith('CMUX_')}
    environment.update(CMUX_CODEX_HOOKS_DISABLED='1', CMUX_CLAUDE_HOOKS_DISABLED='1')
    for key in ('CODEX_THREAD_ID', 'CLAUDE_CODE_SESSION_ID', 'CLAUDECODE'):
        environment.pop(key, None)
    with (directory / 'runner.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=log, env=environment)
        threading.Thread(target=feed_prompt, args=(process, prompt), daemon=True).start()
        deadline = time.monotonic() + 600
        try:
            read_stream(process, stream, log, deadline, directory)
            code = wait_for_exit(process, directory, deadline)
            if code or stream.error:
                message = stream.error or f'{PROVIDERS[stream.provider]} 실행이 실패했습니다.'
                raise provider_failure(message[:2000])
        except subprocess.TimeoutExpired as error:
            raise RetryableProviderError('AI 응답 시간이 초과됐습니다. 제출한 답은 보존됩니다.') from error
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
            process.stdout.close()


def wait_for_exit(process, directory, deadline):
    while time.monotonic() < deadline:
        check_cancelled(directory)
        try:
            return process.wait(timeout=min(0.2, max(0.01, deadline - time.monotonic())))
        except subprocess.TimeoutExpired:
            continue
    raise subprocess.TimeoutExpired(process.args, 600)


def image_prompt(prompt, paths):
    mime_types = {'.png': 'image/png', '.jpg': 'image/jpeg', '.webp': 'image/webp'}
    content = [{'type': 'text', 'text': prompt}]
    for path in paths:
        source = {'type': 'base64', 'media_type': mime_types[path.suffix],
                  'data': base64.b64encode(path.read_bytes()).decode()}
        content.append({'type': 'image', 'source': source})
    return json.dumps({'type': 'user', 'message': {'role': 'user', 'content': content},
                       'parent_tool_use_id': None}) + '\n'


def run_provider(provider, prompt, schema, directory, emit, image_paths=()):
    command = provider_command(provider, directory, schema, image_paths)
    if provider == 'claude' and image_paths:
        prompt = image_prompt(prompt, image_paths)
    stream = ProviderStream(provider, emit)
    execute_stream(command, prompt, directory, stream)
    if provider == 'codex':
        output = directory / 'result.json'
        if not output.exists():
            raise RetryableProviderError('Codex 결과가 없습니다. 제출한 답은 보존됩니다.')
        try:
            stream.result = json.loads(output.read_text())
        except json.JSONDecodeError as error:
            raise RetryableProviderError('AI 결과 형식을 읽지 못했습니다. 제출한 답은 보존됩니다.') from error
    if not isinstance(stream.result, dict):
        raise RetryableProviderError(f'{PROVIDERS[provider]}가 학습 결과를 반환하지 않았습니다.')
    return stream.result
