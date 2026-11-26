#!/usr/bin/env python3
"""정한 사람이 나에게 직접 보낸 리뷰 요청을 ai-review 스킬로 리뷰하는 봇. 자동 레포는 확인 뒤 GitHub에 올리고,
나머지는 초안으로 둔다. 같은 요청은 한 번만 리뷰하고, 다시 요청이 와야 다시 리뷰한다.

launchd가 10분마다 `run`을 부른다.
- 켜기: /usr/bin/python3 review_bot.py install --requester LOGIN [--auto-repo OWNER/REPO]
  (처음 켤 때 이미 기다리던 요청은 건너뛴다)
- 끄기: launchctl bootout gui/$(id -u)/local.review-bot
- 한 PR 바로 초안 만들기: /usr/bin/python3 review_bot.py review --repo OWNER/REPO NUMBER
기록은 ~/pr_reviews/review-bot 아래 state.json, bot.log, runs/(리뷰마다 권한 설정, 대화 기록, review.json)에 남는다.
초안은 그 리뷰 폴더에서 `claude --resume {세션}`으로 리뷰 세션을 이어 받아 확인하고 올린다.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import datetime
import enum
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import uuid

HOME = Path.home()
CLAUDE = HOME / '.local/bin/claude'
CLAUDE_HOME = HOME / '.claude'
URL_LOG = HOME / 'pr_reviews/ai-review-urls.txt'
DEFAULT_STATE_DIR = HOME / 'pr_reviews/review-bot'
SIMPLE_DESIGN = HOME / 'Downloads/Obsidian Vault/Simple Design.md'
CODEX_GLOB = '.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs'
LABEL = 'local.review-bot'
PLIST = HOME / 'Library/LaunchAgents' / f'{LABEL}.plist'
# 사람은 리뷰 요청을 몇 시간 안에 보므로 10분 지연은 짧고, 요청 직후 이어지는 push는 한 번에 리뷰한다.
INTERVAL_SECONDS = 600
MAX_ATTEMPTS = 2
# 대시보드 「봇이 올린 리뷰」가 7일을 보인다.
RECORD_DAYS = 7
POLL_FAILURES_TO_NOTIFY = 3
COMMAND_TIMEOUT_SECONDS = 60
REVIEW_TIMEOUT_SECONDS = 90 * 60
MODEL_ARGS = ('--model', 'opus', '--effort', 'xhigh')
TOOLS = 'Read,Grep,Glob,Edit,Write,Bash,Agent'
REQUEST_SEARCH = 'is:pr is:open archived:false draft:false user-review-requested:@me'
# PR마다 마지막 100개 리뷰 요청을 받는다. 다음 페이지는 gh --paginate가 $endCursor로 받는다.
REQUEST_QUERY = '''query($q: String!, $endCursor: String) {
  search(query: $q, type: ISSUE, first: 100, after: $endCursor) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title url headRefOid isCrossRepository repository { nameWithOwner }
      timelineItems(itemTypes: [REVIEW_REQUESTED_EVENT], last: 100) {
        nodes { ... on ReviewRequestedEvent { createdAt actor { login } requestedReviewer { ... on User { login } } } }
      }
    } }
  }
}'''
# ai-review 4단계가 --draft에서 마지막에 내는 결과 한 줄의 꼴이다.
DRAFT_LINE = re.compile(r'초안 · (APPROVE|COMMENT) · CRITICAL (\d+) · INFO (\d+)')
EVENTS = ('APPROVE', 'COMMENT')
# 남이 쓴 PR을 읽은 모델의 초안이라, 토큰 꼴 문자열이 섞였으면 올리지 않는다.
SECRET_PATTERN = re.compile(r'AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_|-----BEGIN [A-Z ]*PRIVATE KEY-----'
                            r'|sk-ant-|xox[abpr]-')
NOTICES = {
    'draft': '{note}. 대시보드에서 「세션으로 가기」로 확인해 주세요.',
    'posted': '{note} · {reviewUrl}',
    'closed': '{note}이라 올리지 않았습니다.',
    'failed': '리뷰 실패({attempts}/{max_attempts}): {note}. 기록 {runDir}',
    'skipped': '{note}',
}
GIT_READ_VERBS = ('log', 'diff', 'show', 'rev-parse', 'merge-base', 'rev-list', 'ls-files', 'ls-tree', 'cat-file',
                  'blame', 'grep', 'status', 'describe')
# 읽기 명령에 붙어도 파일을 쓰거나(--output), 저장소 밖 파일을 읽거나(--no-index, --contents), 명령을 실행한다(-O).
GIT_DENIED_OPTIONS = ('--output', '--no-index', '--contents', '-O', '--open-files-in-pager')
GH_WRITE_OPTIONS = ('-X', '--method', '-f', '-F', '--field', '--raw-field', '--input')
SECRET_FILES = ('**/.env*', '**/*.pem', '**/*.key')
# launchd의 PATH는 짧다. -p는 마지막 턴 10분 뒤 백그라운드 서브에이전트를 멈추므로 끝까지 기다리게 하고,
# 전체 시간은 REVIEW_TIMEOUT_SECONDS로 끊는다.
ENV = {
    'HOME': str(HOME), 'USER': os.environ.get('USER', HOME.name), 'SHELL': '/bin/bash', 'LANG': 'ko_KR.UTF-8',
    'PATH': f'{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
    'TMPDIR': os.environ.get('TMPDIR', '/tmp'), 'CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS': '0',
}


class Status(str, enum.Enum):
    DRAFT = 'draft'
    POSTED = 'posted'
    CLOSED = 'closed'
    FAILED = 'failed'
    SKIPPED = 'skipped'


class Mode(str, enum.Enum):
    AUTO = 'auto'  # 봇이 확인 뒤 올린다.
    DRAFT = 'draft'  # 사람이 리뷰 세션을 이어 받아 올린다.


@dataclass(frozen=True)
class ClaudeRun:
    exit_code: int | None  # None이면 시간 안에 끝나지 않아 멈췄다.
    final_text: str
    denied: tuple[str, ...]


class ReviewRejected(Exception):
    """GitHub가 리뷰 게시를 거절했다. 메시지는 응답 본문이라 토큰이 없다."""

    def __init__(self, status, message):
        super().__init__(f'HTTP {status}: {message}')
        self.status = status


def main(argv=None):
    args = parse_args(argv)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with hold_lock(state_dir) as locked:
        if not locked:
            print('다른 리뷰 봇 실행이 돌고 있어 끝낸다')
        elif args.command == 'run':
            poll(set(args.requester), set(args.auto_repo), state_dir)
        elif args.command == 'review':
            review_now(args.repo, args.number, state_dir)
        else:
            install(args.requester, args.auto_repo, state_dir)
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description='정한 사람이 나에게 직접 보낸 리뷰 요청을 ai-review로 리뷰한다')
    parser.add_argument('--state-dir', default=str(DEFAULT_STATE_DIR))
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'install'):
        command = commands.add_parser(name)
        command.add_argument('--requester', action='append', required=True, help='이 GitHub login이 보낸 요청만 리뷰한다')
        command.add_argument('--auto-repo', action='append', default=[], help='확인 없이 리뷰를 올릴 레포')
    review = commands.add_parser('review')
    review.add_argument('--repo', required=True)
    review.add_argument('number', type=int)
    return parser.parse_args(argv)


@contextlib.contextmanager
def hold_lock(state_dir):
    with (state_dir / 'lock').open('w') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True


def poll(requesters, auto_repos, state_dir):
    state = load_state(state_dir)
    try:
        login = current_login()
        requests = parse_review_requests(fetch_review_request_pages(), login)
        recover(state, login, state_dir)
        for request in requests:
            if request['request'] is None:
                log(state_dir, f'{request["key"]} 마지막 100개 리뷰 요청에 나에게 온 것이 없어 건너뜀')
            elif request['requester'] in requesters:
                handle(request, mode_of(request, auto_repos), state, state_dir, login)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        state['poll_failures'] += 1
        log(state_dir, f'GitHub 조회 실패 {state["poll_failures"]}번째: {detail}')
        if state['poll_failures'] == POLL_FAILURES_TO_NOTIFY:
            notify(f'GitHub 조회가 {POLL_FAILURES_TO_NOTIFY}번 연속 실패했습니다: {detail[:200]}')
    else:
        state['poll_failures'] = 0
        prune(state, requests)
        state['polledAt'] = now_utc()
    save_state(state_dir, state)


def handle(request, mode, state, state_dir, login):
    """요청 하나를 처리한다. 같은 요청은 한 번만 리뷰하고, 그 요청에 새 커밋만 오면 head만 갱신한다."""
    key = request['key']
    entry = state['prs'].get(key)
    if entry is not None and entry['request'] == request['request']:
        entry['head'] = request['head']
        if entry['status'] == Status.DRAFT and entry['mode'] == Mode.AUTO:
            start_running(state, state_dir, key, Path(entry['runDir']), entry['session'])
            finish(key, deliver(request, entry, state, state_dir), state, state_dir)
        elif entry['status'] == Status.FAILED and entry['attempts'] < MAX_ATTEMPTS:
            review(request, mode, entry['attempts'] + 1, state, state_dir)
    elif request['fork']:
        skip(request, mode, 'fork PR은 봇이 head를 받지 못해 손수 리뷰해 주세요.', state, state_dir)
    elif last_review_commit(request['repo'], request['number'], login) == request['head']:
        skip(request, mode, '같은 커밋으로 리뷰를 다시 요청받았습니다. 직접 확인해 주세요.', state, state_dir)
    else:
        review(request, mode, 1, state, state_dir)


def mode_of(request, auto_repos):
    return Mode.AUTO if request['repo'] in auto_repos else Mode.DRAFT


def skip(request, mode, note, state, state_dir):
    state['prs'][request['key']] = record(request, mode, note=note)
    save_state(state_dir, state)
    log(state_dir, f'{request["key"]} 건너뜀: {note}')
    notify(f'{short_name(request["key"])} {note}')


def prune(state, requests):
    """요청 목록에 없고 마지막 기록이 RECORD_DAYS 지난 기록을 지운다. 리뷰 폴더와 세션 파일은 남긴다."""
    listed = {request['key'] for request in requests}
    cutoff = now() - datetime.timedelta(days=RECORD_DAYS)
    state['prs'] = {key: entry for key, entry in state['prs'].items() if key in listed or parse_utc(entry['at']) > cutoff}


def recover(state, login, state_dir):
    """앞 실행이 리뷰나 게시 중에 죽어 남은 running을 GitHub와 맞춘 뒤 지운다. 게시가 받아들여지면 GitHub가
    요청을 지워 그 PR이 다시 검색되지 않으므로, 이것이 그 리뷰를 posted로 적을 유일한 단서다."""
    running = state['running']
    if running is None:
        return
    entry = state['prs'].get(running['key'])
    if entry is not None and entry['status'] == Status.DRAFT:
        repo, number = running['key'].rsplit('#', 1)
        url = review_url_on(repo, int(number), entry['sha'], login)
        if url:
            state['prs'][running['key']] = {**entry, 'status': Status.POSTED.value, 'reviewUrl': url,
                                            'note': '앞 실행이 올린 뒤 멈춰 다음 실행이 기록함', 'at': now_utc()}
            append_url_log(url)
    state['running'] = None
    save_state(state_dir, state)


def review_now(repo, number, state_dir):
    """손수 실행: 그 PR을 초안으로 리뷰한다. 그때 기다리던 요청이 있으면 그 요청을 끝낸 것으로 적는다."""
    state = load_state(state_dir)
    login = current_login()
    recover(state, login, state_dir)
    key, pull = f'{repo}#{number}', view_pull_request(repo, number)
    waiting = next((request for request in parse_review_requests(fetch_review_request_pages(), login)
                    if request['key'] == key), {})
    request = {'key': key, 'repo': repo, 'number': number, 'title': pull['title'], 'url': pull['url'],
               'head': pull['headRefOid'], 'request': waiting.get('request'), 'requester': waiting.get('requester')}
    review(request, Mode.DRAFT, 1, state, state_dir)


def install(requesters, auto_repos, state_dir):
    """launchd에 등록한다. 처음 설치할 때만 이미 기다리던 요청을 건너뛴 것으로 적어, 오래 밀린 요청을 한꺼번에
    리뷰하지 않는다. 다시 설치할 때는 기록을 건드리지 않아 그사이 온 요청도 그대로 리뷰한다."""
    state = load_state(state_dir)
    if state['installedAt'] is None:
        for request in parse_review_requests(fetch_review_request_pages(), current_login()):
            if request['requester'] in requesters:
                waiting = record(request, mode_of(request, auto_repos), note='설치 전부터 대기')
                state['prs'].setdefault(request['key'], waiting)
        state['installedAt'] = now_utc()
        save_state(state_dir, state)
    register_launch_agent({
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/python3', str(Path(__file__).resolve()), '--state-dir', str(state_dir), 'run',
                             *options('--requester', requesters), *options('--auto-repo', auto_repos)],
        'StartInterval': INTERVAL_SECONDS,
        'RunAtLoad': True,
        'StandardOutPath': str(state_dir / 'launchd.log'),
        'StandardErrorPath': str(state_dir / 'launchd.log'),
    })
    print(f'{LABEL} 등록: {INTERVAL_SECONDS // 60}분마다 {", ".join(requesters)}의 리뷰 요청 확인 -> {PLIST}')


def options(flag, values):
    return [arg for value in values for arg in (flag, value)]


def review(request, mode, attempt, state, state_dir):
    """PR 하나를 초안으로 리뷰하고, 자동 레포면 이어서 올린 뒤 결과를 기록하고 알린다."""
    entry = draft_review(request, mode, attempt, state, state_dir)
    if mode is Mode.AUTO:
        entry = deliver(request, entry, state, state_dir)
    finish(request['key'], entry, state, state_dir)


def draft_review(request, mode, attempt, state, state_dir):
    """ai-review --draft로 초안을 만든다. 올리기 전에 죽어도 다음 실행이 맞출 수 있게 결과를 바로 기록한다."""
    key, repo, number, head = request['key'], request['repo'], request['number'], request['head']
    started = datetime.datetime.now()
    run_dir = state_dir / 'runs' / f'{repo.split("/")[1]}-{number}-{head[:8]}-{started:%Y%m%d-%H%M%S-%f}'
    run_dir.mkdir(parents=True)
    session = str(uuid.uuid4())
    codex = codex_script()
    settings = run_dir / 'settings.json'
    settings.write_text(json.dumps(sandbox_settings(repo, number, run_dir, codex), ensure_ascii=False, indent=1))
    start_running(state, state_dir, key, run_dir, session)
    run = run_claude(review_prompt(request['url'], run_dir, codex), settings, run_dir, session)
    entry = record(request, mode, runDir=str(run_dir), session=session, attempts=attempt, **judge(run, run_dir))
    log(state_dir, f'{key} {head[:8]} {entry["status"]} {entry["note"]} · 거부 {len(run.denied)}개 · {run_dir}')
    state['prs'][key] = entry
    save_state(state_dir, state)
    return entry


def record(request, mode, **fields):
    """state.json의 PR 기록 한 건. 칸은 대시보드가 읽는 상태 파일 계약 그대로다."""
    return {'request': request['request'], 'requester': request['requester'], 'title': request['title'][:300],
            'url': request['url'], 'mode': mode.value, 'sha': None, 'head': request['head'], 'since': None,
            'status': Status.SKIPPED.value, 'event': None, 'critical': None, 'info': None, 'runDir': None,
            'session': None, 'reviewUrl': None, 'attempts': 0, 'note': '', **fields, 'at': now_utc()}


def judge(run, run_dir):
    """마지막 줄이 결과 줄이고 review.json이 같은 event의 올바른 초안이면 초안, 아니면 실패 이유."""
    lines = run.final_text.strip().splitlines()
    line = DRAFT_LINE.fullmatch(lines[-1].strip(' `')) if lines else None
    if line is None:
        if run.exit_code is None:
            return failure(f'{REVIEW_TIMEOUT_SECONDS // 60}분 안에 끝나지 않음')
        return failure(f'종료 코드 {run.exit_code}' if run.exit_code else '결과 줄 없음')
    try:
        draft = read_draft(run_dir)
    except ValueError as error:
        return failure(str(error))
    if draft['event'] != line.group(1):
        return failure(f'결과 줄 event {line.group(1)}와 review.json event {draft["event"]}가 다름')
    return {'status': Status.DRAFT.value, 'sha': draft['commit_id'], 'event': draft['event'],
            'critical': int(line.group(2)), 'info': int(line.group(3)), 'note': line.group(0)}


def failure(note):
    return {'status': Status.FAILED.value, 'sha': None, 'event': None, 'critical': None, 'info': None, 'note': note}


def read_draft(run_dir):
    """리뷰 폴더의 review.json. ai-review 3단계 6번의 꼴이 아니면 ValueError."""
    try:
        draft = json.loads((run_dir / 'review.json').read_text())
        valid = (draft['event'] in EVENTS and re.fullmatch(r'[0-9a-f]{40}', draft['commit_id'])
                 and isinstance(draft['body'], str) and all(is_line_comment(comment) for comment in draft['comments']))
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'review.json을 읽지 못함({error})') from error
    if not valid:
        raise ValueError('review.json 꼴이 ai-review 3단계 6번과 다름')
    return draft


def is_line_comment(comment):
    if not (isinstance(comment['path'], str) and isinstance(comment['line'], int) and comment['side'] == 'RIGHT'
            and isinstance(comment['body'], str)):
        return False
    return 'start_line' not in comment or (isinstance(comment['start_line'], int) and comment['start_side'] == 'RIGHT')


def deliver(request, entry, state, state_dir):
    """자동 레포 초안을 올린다. 올리기 직전에 head가 바뀌었으면 새 head로 한 번 다시 리뷰한다(ai-review 3단계 5번)."""
    entry = post(request, entry)
    if is_moved(entry):
        moved = {**request, 'head': entry['head']}
        entry = post(request, draft_review(moved, Mode.AUTO, entry['attempts'], state, state_dir))
    if is_moved(entry):
        return {**entry, 'mode': Mode.DRAFT.value, 'note': '올리기 직전에 새 커밋이 또 와서 초안으로 둠'}
    return entry


def is_moved(entry):
    return entry['status'] == Status.DRAFT and entry['head'] != entry['sha']


def post(request, entry):
    """초안을 확인한 뒤 올린다. head가 바뀌었으면 올리지 않고 새 head만 적어 돌려준다."""
    if entry['status'] != Status.DRAFT:
        return entry
    pull = view_pull_request(request['repo'], request['number'])
    if pull['state'] != 'OPEN':
        return {**entry, 'status': Status.CLOSED.value, 'note': f'PR {pull["state"]}'}
    if pull['headRefOid'] != entry['sha']:
        return {**entry, 'head': pull['headRefOid']}
    try:
        draft = read_draft(Path(entry['runDir']))
    except ValueError as error:
        return {**entry, **failure(str(error))}
    if any(SECRET_PATTERN.search(text) for text in (draft['body'], *(comment['body'] for comment in draft['comments']))):
        return {**entry, **failure('초안에 비밀값 꼴 문자열이 있어 올리지 않음')}
    try:
        url = submit_review(request['repo'], request['number'], draft)
    except ReviewRejected as error:
        return {**entry, **failure(f'게시 거절 {error}')}
    append_url_log(url)
    return {**entry, 'status': Status.POSTED.value, 'reviewUrl': url,
            'note': f'{entry["event"]} 올림 · CRITICAL {entry["critical"]} · INFO {entry["info"]}'}


def submit_review(repo, number, draft):
    """리뷰를 올려 그 주소를 돌려준다. 줄을 찾지 못했다는 422면 줄 코멘트를 본문 끝으로 옮겨 한 번 더 보낸다."""
    try:
        return send_review(repo, number, draft)
    except ReviewRejected as error:
        if error.status != 422 or 'line' not in str(error).lower():
            raise
    moved = '\n'.join(f'- `{comment["path"]}:{comment["line"]}` {comment["body"]}' for comment in draft['comments'])
    return send_review(repo, number, {**draft, 'body': f'{draft["body"]}\n\n{moved}', 'comments': []})


def start_running(state, state_dir, key, run_dir, session):
    repo, number = key.rsplit('#', 1)
    state['running'] = {'pid': os.getpid(), 'key': key, 'runDir': str(run_dir),
                        'worktree': str(review_worktree(repo, number)), 'session': session, 'startedAt': now_utc()}
    save_state(state_dir, state)


def finish(key, entry, state, state_dir):
    state['prs'][key] = {**entry, 'at': now_utc()}
    state['running'] = None
    save_state(state_dir, state)
    log(state_dir, f'{key} 끝 {entry["status"]} {entry["note"]}')
    notify(f'{short_name(key)} {NOTICES[entry["status"]].format(**entry, max_attempts=MAX_ATTEMPTS)}')


def short_name(key):
    return key.split('/', 1)[1]


def now():
    return datetime.datetime.now(datetime.timezone.utc)


def now_utc():
    return now().strftime('%Y-%m-%dT%H:%M:%SZ')


def parse_utc(text):
    return datetime.datetime.strptime(text, '%Y-%m-%dT%H:%M:%S%z')


def review_prompt(url, run_dir, codex):
    lines = [
        '리뷰 봇 실행이다. 이 실행은 리뷰 초안만 만들고 GitHub에 올리지 않으며, 질문에 답할 사람이 없다.',
        '1. `~/.claude/CLAUDE.md`와 그 파일의 `@` 줄이 가리키는 파일을 Read하고 따른다.',
        f'2. `~/.claude/skills/ai-review/SKILL.md`를 Read하고 인자 `{url} --draft`로 수행한다. `{{스크래치}}`는 `{run_dir}`이다.',
        '실행 환경: Bash는 허용한 꼴만 돈다. 경로는 따옴표 없는 절대경로로 쓰고, `cd` 대신 `git -C {경로}`를 쓴다.',
    ]
    if codex:
        lines.append(f'Codex 동반 스크립트는 `node {codex} ... --cwd {{작업 디렉토리}}`로 부른다.')
    return '\n'.join(lines)


def clone_path(repo):
    owner, name = repo.split('/')
    return HOME / owner.lower() / name  # ai-review lib/review/prepare.md의 메인 클론 위치


def review_worktree(repo, number):
    return clone_path(repo) / '.claude/worktrees' / f'review-{number}'  # 같은 문서 3절의 리뷰 worktree


def sandbox_settings(repo, number, run_dir, codex):
    """이 PR 하나를 읽고 초안을 리뷰 폴더에만 쓸 수 있는 권한을 만든다. PR 본문과 코드는 남이 쓴 입력이라
    GitHub에 쓰는 권한은 주지 않는다."""
    clone, worktree = clone_path(repo), review_worktree(repo, number)
    readable = [clone, run_dir, SIMPLE_DESIGN, *instruction_paths()]
    # 다른 레포는 로컬 클론 대신 GitHub에서 읽는다. 클론 옆에는 비밀값 파일과 개인 작업 폴더가 섞여 있다.
    commands = [
        'gh pr view *', 'gh pr diff *', 'gh pr list *', 'gh search *', 'gh api repos/*', 'gh api user', 'gh api user --jq .login',
        *(f'git -C {c} fetch {args}' for c in spellings(clone) for args in ('origin', 'origin --quiet', '--quiet origin')),
        *(f'git -C {c} worktree {verb}*' for c in spellings(clone) for verb in ('list', 'prune')),
        *(f'git -C {c} worktree add --detach {w} *' for c in spellings(clone) for w in spellings(worktree)),
        *(f'git -C {c} worktree remove {force}{w}*' for c in spellings(clone) for w in spellings(worktree)
          for force in ('', '--force ')),
        *(f'git -C {w} checkout --detach *' for w in spellings(worktree)),
        *(f'git -C {p} {verb}{rest}' for p in (*spellings(clone), *spellings(worktree)) for verb in GIT_READ_VERBS
          for rest in ('', ' *')),
    ]
    deny = [*(f'Read({pattern})' for pattern in SECRET_FILES), *(f'Bash(git * {option}*)' for option in GIT_DENIED_OPTIONS),
            *(f'Bash(gh api repos/* {option}*)' for option in GH_WRITE_OPTIONS)]
    if codex:
        commands.append(f'node {codex} *')
        deny += [f'Bash(node {codex} setup*)', f'Bash(node {codex} * --write*)']
    allow = ['Agent', *(read_rule(path) for path in readable), f'Edit({rule_path(run_dir)}/**)',
             *(f'Bash({command})' for command in commands)]
    return {'permissions': {'allow': allow, 'deny': deny}}


def instruction_paths():
    """~/.claude의 지침 파일과 심볼릭 링크가 가리키는 실제 위치. 권한 검사는 링크를 따라간 실제 경로로도 한다."""
    links = [CLAUDE_HOME / 'CLAUDE.md', CLAUDE_HOME / 'instructions', CLAUDE_HOME / 'lib', CLAUDE_HOME / 'skills',
             *(CLAUDE_HOME / 'lib').iterdir(), *(CLAUDE_HOME / 'skills').iterdir()]
    return sorted({*links, *(link.resolve() for link in links)})


def read_rule(path):
    return f'Read({rule_path(path)}/**)' if path.is_dir() else f'Read({rule_path(path)})'


def rule_path(path):
    """권한 규칙의 경로 꼴. /로 시작하면 설정 파일 기준 상대 경로라 집 밖의 절대경로는 //로 쓴다."""
    return f'~/{path.relative_to(HOME)}' if path.is_relative_to(HOME) else f'/{path}'


def spellings(path):
    """모델이 명령에 쓰는 경로 꼴들. 권한 규칙은 글자 그대로 맞춰 보므로 꼴마다 규칙이 필요하다."""
    forms = [str(path), f'"{path}"']
    if path.is_relative_to(HOME):
        forms.append(f'~/{path.relative_to(HOME)}')
    return forms


def codex_script():
    scripts = sorted(HOME.glob(CODEX_GLOB))
    return scripts[-1] if scripts else None


def load_state(state_dir):
    """state.json. 요청 시각이 없는 옛 꼴(커밋 기준 봇) 기록은 버린다."""
    path = state_dir / 'state.json'
    saved = json.loads(path.read_text()) if path.exists() else {}
    state = {'prs': {}, 'running': None, 'quota': None, 'installedAt': None, 'polledAt': None, 'poll_failures': 0, **saved}
    state['prs'] = {key: entry for key, entry in state['prs'].items() if 'request' in entry}
    return state


def save_state(state_dir, state):
    path = state_dir / 'state.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    temporary.replace(path)


def log(state_dir, message):
    with (state_dir / 'bot.log').open('a') as stream:
        stream.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}\n')


def append_url_log(url):
    with URL_LOG.open('a') as stream:
        stream.write(url + '\n')


def fetch_review_request_pages():
    """나에게 직접 온(팀 요청 제외) 열린 PR 검색 결과 페이지들. 응답에 errors가 있거나 한 페이지라도 실패하면
    gh가 실패로 끝나 CalledProcessError가 난다."""
    return json.loads(gh('api', 'graphql', '--paginate', '--slurp', '-f', f'query={REQUEST_QUERY}', '-f', f'q={REQUEST_SEARCH}'))


def parse_review_requests(pages, login):
    """PR마다 나에게 온 마지막 리뷰 요청. 마지막 100개 요청 기록에 나에게 온 것이 없으면 request가 None이다."""
    requests = []
    for page in pages:
        for node in page['data']['search']['nodes']:
            mine = [event for event in node['timelineItems']['nodes']
                    if (event['requestedReviewer'] or {}).get('login') == login]
            last = mine[-1] if mine else {}
            repo = node['repository']['nameWithOwner']
            requests.append({'key': f'{repo}#{node["number"]}', 'repo': repo, 'number': node['number'],
                             'title': node['title'], 'url': node['url'], 'head': node['headRefOid'],
                             'fork': node['isCrossRepository'], 'request': last.get('createdAt'),
                             'requester': (last.get('actor') or {}).get('login')})
    return requests


def view_pull_request(repo, number):
    return json.loads(gh('pr', 'view', str(number), '-R', repo, '--json', 'number,headRefOid,url,state,title'))


def current_login():
    return gh('api', 'user', '--jq', '.login').strip()


def last_review_commit(repo, number, login):
    """내가 그 PR에 마지막으로 단 리뷰의 커밋. 없으면 None."""
    query = f'.[] | select(.user.login == "{login}") | .commit_id'
    commits = gh('api', f'repos/{repo}/pulls/{number}/reviews', '--paginate', '--jq', query).split()
    return commits[-1] if commits else None


def review_url_on(repo, number, sha, login):
    """그 커밋에 단 내 리뷰의 주소. 없으면 None."""
    query = f'.[] | select(.user.login == "{login}" and .commit_id == "{sha}") | .html_url'
    urls = gh('api', f'repos/{repo}/pulls/{number}/reviews', '--paginate', '--jq', query).split()
    return urls[0] if urls else None


def send_review(repo, number, draft):
    """리뷰 한 건을 올려 주소를 돌려준다. 거절되면 응답 본문을 담은 ReviewRejected."""
    result = subprocess.run(['gh', 'api', '-X', 'POST', f'repos/{repo}/pulls/{number}/reviews', '--input', '-'],
                            input=json.dumps(draft, ensure_ascii=False), env=ENV, capture_output=True, text=True,
                            timeout=COMMAND_TIMEOUT_SECONDS)
    if result.returncode == 0:
        return json.loads(result.stdout)['html_url']
    status = re.search(r'HTTP (\d{3})', result.stderr)
    raise ReviewRejected(int(status.group(1)) if status else None, (result.stdout or result.stderr).strip()[:500])


def gh(*args):
    return subprocess.run(['gh', *args], env=ENV, capture_output=True, text=True, check=True,
                          timeout=COMMAND_TIMEOUT_SECONDS).stdout


def run_claude(prompt, settings, run_dir, session):
    command = [str(CLAUDE), '-p', prompt, *MODEL_ARGS, '--session-id', session, '--setting-sources', 'local',
               '--settings', str(settings), '--strict-mcp-config', '--no-chrome', '--permission-mode', 'dontAsk',
               '--tools', TOOLS, '--output-format', 'stream-json', '--verbose']
    transcript = run_dir / 'transcript.jsonl'
    with transcript.open('w') as stream:
        try:
            exit_code = subprocess.run(command, cwd=run_dir, env=ENV, stdin=subprocess.DEVNULL, stdout=stream,
                                       stderr=subprocess.STDOUT, timeout=REVIEW_TIMEOUT_SECONDS).returncode
        except subprocess.TimeoutExpired:
            exit_code = None
    final_text, denied = '', []
    for line in transcript.read_text().splitlines():
        # stderr를 같은 파일에 합쳐 경고 같은 JSON 아닌 줄이 섞인다.
        if not line.startswith('{'):
            continue
        event = json.loads(line)
        if event['type'] == 'result':
            final_text = event.get('result') or final_text
            denied += [f'{d["tool_name"]} {json.dumps(d["tool_input"], ensure_ascii=False)}' for d in event['permission_denials']]
    return ClaudeRun(exit_code, final_text, tuple(denied))


def notify(message):
    script = 'on run argv\ndisplay notification (item 1 of argv) with title "리뷰 봇"\nend run'
    subprocess.run(['osascript', '-e', script, message], capture_output=True, timeout=COMMAND_TIMEOUT_SECONDS)


def register_launch_agent(plist):
    PLIST.write_bytes(plistlib.dumps(plist))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)
    subprocess.run(['launchctl', 'bootstrap', domain, str(PLIST)], check=True)


if __name__ == '__main__':
    raise SystemExit(main())
