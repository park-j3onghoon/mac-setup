#!/usr/bin/env python3
"""나에게 직접 리뷰를 요청한 PR을 ai-review 스킬로 리뷰해 GitHub에 올리는 봇.

launchd가 10분마다 `run`을 부른다.
- 켜기: /usr/bin/python3 review_bot.py install --repo OWNER/REPO (켤 때 이미 기다리던 요청은 건너뛴다)
- 끄기: launchctl bootout gui/$(id -u)/local.review-bot
- 한 PR 바로 리뷰: /usr/bin/python3 review_bot.py review --repo OWNER/REPO NUMBER [--dry-run]
기록은 ~/pr_reviews/review-bot 아래 state.json, bot.log, runs/(실행마다 권한 설정과 대화 기록)에 남는다.
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
POLL_FAILURES_TO_NOTIFY = 3
COMMAND_TIMEOUT_SECONDS = 60
REVIEW_TIMEOUT_SECONDS = 90 * 60
MODEL_ARGS = ('--model', 'opus', '--effort', 'xhigh')
TOOLS = 'Read,Grep,Glob,Edit,Write,Bash,Agent'
# ai-review 4단계가 마지막에 내는 결과 한 줄의 꼴이다.
POSTED_LINE = re.compile(r'(APPROVE|COMMENT) · CRITICAL \d+ · INFO \d+ · https://github\.com/[^\s`)]+#pullrequestreview-\d+')
NOT_POSTED_LINE = re.compile(r'올리지 않음 · [^\n`]+')
GIT_READ_VERBS = ('log', 'diff', 'show', 'rev-parse', 'merge-base', 'rev-list', 'ls-files', 'ls-tree', 'cat-file',
                  'blame', 'grep', 'status', 'describe')
# 읽기 명령에 붙어도 파일을 쓰거나(--output), 저장소 밖 파일을 읽거나(--no-index, --contents), 명령을 실행한다(-O).
GIT_DENIED_OPTIONS = ('--output', '--no-index', '--contents', '-O', '--open-files-in-pager')
SECRET_FILES = ('**/.env*', '**/*.pem', '**/*.key')
# launchd의 PATH는 짧다. -p는 마지막 턴 10분 뒤 백그라운드 서브에이전트를 멈추므로 끝까지 기다리게 하고,
# 전체 시간은 REVIEW_TIMEOUT_SECONDS로 끊는다.
ENV = {
    'HOME': str(HOME), 'USER': os.environ.get('USER', HOME.name), 'SHELL': '/bin/bash', 'LANG': 'ko_KR.UTF-8',
    'PATH': f'{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
    'TMPDIR': os.environ.get('TMPDIR', '/tmp'), 'CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS': '0',
}


class Status(str, enum.Enum):
    POSTED = 'posted'
    FAILED = 'failed'
    SKIPPED = 'skipped'


@dataclass(frozen=True)
class ClaudeRun:
    exit_code: int | None  # None이면 시간 안에 끝나지 않아 멈췄다.
    final_text: str
    denied: tuple[str, ...]


def main(argv=None):
    args = parse_args(argv)
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with hold_lock(state_dir) as locked:
        if not locked:
            print('다른 리뷰 봇 실행이 돌고 있어 끝낸다')
        elif args.command == 'run':
            poll(args.repo, state_dir)
        elif args.command == 'review':
            review_now(args.repo, args.number, state_dir, args.dry_run)
        else:
            install(args.repo, state_dir)
    return 0


def parse_args(argv):
    parser = argparse.ArgumentParser(description='나에게 직접 리뷰를 요청한 PR을 ai-review로 리뷰해 올린다')
    parser.add_argument('--state-dir', default=str(DEFAULT_STATE_DIR))
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'install'):
        commands.add_parser(name).add_argument('--repo', required=True)
    review = commands.add_parser('review')
    review.add_argument('--repo', required=True)
    review.add_argument('number', type=int)
    review.add_argument('--dry-run', action='store_true')
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


def poll(repo, state_dir):
    state = load_state(state_dir)
    try:
        review_requests(repo, state_dir, state)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        detail = error.stderr.strip() if isinstance(error, subprocess.CalledProcessError) else str(error)
        state['poll_failures'] += 1
        log(state_dir, f'GitHub 조회 실패 {state["poll_failures"]}번째: {detail}')
        if state['poll_failures'] == POLL_FAILURES_TO_NOTIFY:
            notify(f'GitHub 조회가 {POLL_FAILURES_TO_NOTIFY}번 연속 실패했습니다: {detail[:200]}')
    else:
        state['poll_failures'] = 0
    save_state(state_dir, state)


def review_requests(repo, state_dir, state):
    login = None
    for pr in list_review_requests(repo):
        key, head = f'{repo}#{pr["number"]}', pr['headRefOid']
        entry = state['prs'].get(key)
        if is_settled(entry, head):
            continue
        login = login or current_login()
        if has_review_on(repo, pr['number'], head, login):
            state['prs'][key] = record(head, Status.SKIPPED, 0, '내 리뷰가 있는 커밋으로 다시 요청됨')
            log(state_dir, f'{key} {head[:8]} 같은 커밋 재요청이라 건너뜀')
            notify(f'{short_name(key)} 같은 커밋으로 리뷰를 다시 요청받았습니다. 직접 확인해 주세요.')
        else:
            retried = entry is not None and entry['sha'] == head and entry['status'] == Status.FAILED
            state['prs'][key] = review_pr(repo, pr, state_dir, entry['attempts'] if retried else 0)
        save_state(state_dir, state)


def is_settled(entry, head):
    """이 커밋에서 더 할 일이 없는지 본다: 건너뛰기로 정했거나 실패 횟수를 다 썼다."""
    if entry is None or entry['sha'] != head:
        return False
    return entry['status'] == Status.SKIPPED or (entry['status'] == Status.FAILED and entry['attempts'] >= MAX_ATTEMPTS)


def review_now(repo, number, state_dir, dry_run):
    entry = review_pr(repo, view_pull_request(repo, number), state_dir, 0, dry_run)
    if not dry_run:
        state = load_state(state_dir)
        state['prs'][f'{repo}#{number}'] = entry
        save_state(state_dir, state)


def install(repo, state_dir):
    state = load_state(state_dir)
    for pr in list_review_requests(repo):
        state['prs'].setdefault(f'{repo}#{pr["number"]}', record(pr['headRefOid'], Status.SKIPPED, 0, '설치 전부터 대기'))
    save_state(state_dir, state)
    register_launch_agent({
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/python3', str(Path(__file__).resolve()), '--state-dir', str(state_dir),
                             'run', '--repo', repo],
        'StartInterval': INTERVAL_SECONDS,
        'RunAtLoad': True,
        'StandardOutPath': str(state_dir / 'launchd.log'),
        'StandardErrorPath': str(state_dir / 'launchd.log'),
    })
    print(f'{LABEL} 등록: {INTERVAL_SECONDS // 60}분마다 {repo} 리뷰 요청 확인 -> {PLIST}')


def review_pr(repo, pr, state_dir, attempts, dry_run=False):
    key, head = f'{repo}#{pr["number"]}', pr['headRefOid']
    started = datetime.datetime.now()
    run_dir = state_dir / 'runs' / f'{repo.split("/")[1]}-{pr["number"]}-{head[:8]}-{started:%Y%m%d-%H%M%S-%f}'
    run_dir.mkdir(parents=True)
    codex = codex_script()
    settings = run_dir / 'settings.json'
    settings.write_text(json.dumps(sandbox_settings(repo, pr['number'], run_dir, codex, dry_run),
                                   ensure_ascii=False, indent=1))
    run = run_claude(review_prompt(pr['url'], run_dir, codex, dry_run), settings, run_dir)
    if dry_run:
        print(f'{run.final_text}\n기록 {run_dir} · 거부 {len(run.denied)}개')
        return None
    entry = judge(run, head, attempts + 1)
    log(state_dir, f'{key} {head[:8]} {entry["status"]} {entry["note"]} · 거부 {len(run.denied)}개 · {run_dir}')
    if entry['status'] == Status.FAILED:
        notify(f'{short_name(key)} 리뷰 실패({entry["attempts"]}/{MAX_ATTEMPTS}): {entry["note"]}. 기록 {run_dir}')
    else:
        notify(f'{short_name(key)} {entry["note"]}')
    return entry


def judge(run, head, attempts):
    posted = POSTED_LINE.search(run.final_text)
    if posted:
        return record(head, Status.POSTED, attempts, posted.group(0))
    not_posted = NOT_POSTED_LINE.search(run.final_text)
    if not_posted:
        return record(head, Status.SKIPPED, attempts, not_posted.group(0))
    if run.exit_code is None:
        reason = f'{REVIEW_TIMEOUT_SECONDS // 60}분 안에 끝나지 않음'
    elif run.exit_code:
        reason = f'종료 코드 {run.exit_code}'
    else:
        reason = '결과 줄 없음'
    return record(head, Status.FAILED, attempts, reason)


def record(sha, status, attempts, note):
    return {'sha': sha, 'status': status.value, 'attempts': attempts, 'note': note,
            'at': datetime.datetime.now().isoformat(timespec='seconds')}


def short_name(key):
    return key.split('/', 1)[1]


def review_prompt(url, run_dir, codex, dry_run):
    lines = [
        '리뷰 봇 실행이다. 사용자가 이 PR의 리뷰를 확인 없이 GitHub에 올리도록 미리 승인했고, 이 실행에는 질문에 답할 사람이 없다.',
        '1. `~/.claude/CLAUDE.md`와 그 파일의 `@` 줄이 가리키는 파일을 Read하고 따른다.',
        f'2. `~/.claude/skills/ai-review/SKILL.md`를 Read하고 인자 `{url} --auto`로 수행한다. `{{스크래치}}`는 `{run_dir}`이다.',
        '실행 환경: Bash는 허용한 꼴만 돈다. 경로는 따옴표 없는 절대경로로 쓰고, `cd` 대신 `git -C {경로}`를 쓴다.',
    ]
    if codex:
        lines.append(f'Codex 동반 스크립트는 `node {codex} ... --cwd {{작업 디렉토리}}`로 부른다.')
    if dry_run:
        lines.append('시험 실행이다: GitHub에 리뷰를 올리지 않는다. 리뷰를 올리는 `gh api` 명령 대신 `{스크래치}/review.json`까지만 쓰고, '
                     '마지막 줄을 `시험 · {event} · CRITICAL {x} · INFO {y} · {review.json 경로}`로 낸다.')
    return '\n'.join(lines)


def sandbox_settings(repo, number, run_dir, codex, dry_run):
    """이 PR 하나를 읽고 그 PR에만 리뷰 한 건을 올릴 수 있는 권한을 만든다. PR 본문과 코드는 남이 쓴 입력이다."""
    owner, name = repo.split('/')
    clone = HOME / owner.lower() / name  # ai-review lib/review/prepare.md의 메인 클론 위치
    worktree = clone / '.claude/worktrees' / f'review-{number}'
    readable = [clone, run_dir, HOME / 'plans', SIMPLE_DESIGN, *instruction_paths()]
    commands = [
        'gh pr view *', 'gh api user', 'gh api user --jq .login',
        *(f'git -C {c} fetch {args}' for c in spellings(clone) for args in ('origin', 'origin --quiet', '--quiet origin')),
        *(f'git -C {c} worktree {verb}*' for c in spellings(clone) for verb in ('list', 'prune')),
        *(f'git -C {c} worktree add --detach {w} *' for c in spellings(clone) for w in spellings(worktree)),
        *(f'git -C {c} worktree remove {force}{w}*' for c in spellings(clone) for w in spellings(worktree)
          for force in ('', '--force ')),
        *(f'git -C {w} checkout --detach *' for w in spellings(worktree)),
        *(f'git -C {p} {verb}{rest}' for p in (*spellings(clone), *spellings(worktree)) for verb in GIT_READ_VERBS
          for rest in ('', ' *')),
    ]
    deny = [*(f'Read({pattern})' for pattern in SECRET_FILES), *(f'Bash(git * {option}*)' for option in GIT_DENIED_OPTIONS)]
    if codex:
        commands.append(f'node {codex} *')
        deny += [f'Bash(node {codex} setup*)', f'Bash(node {codex} * --write*)']
    if not dry_run:
        commands += [f'gh api -X POST repos/{repo}/pulls/{number}/reviews --input {p}' for p in spellings(run_dir / 'review.json')]
        commands += [f'jq -r .html_url {p}' for p in spellings(run_dir / 'posted.json')]
        commands += [f'tee -a {p}' for p in spellings(URL_LOG)]
    allow = ['Agent', *(read_rule(path) for path in readable), f'Edit({rule_path(run_dir)}/**)', f'Edit({rule_path(URL_LOG)})',
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
    path = state_dir / 'state.json'
    return json.loads(path.read_text()) if path.exists() else {'prs': {}, 'poll_failures': 0}


def save_state(state_dir, state):
    path = state_dir / 'state.json'
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=1))
    temporary.replace(path)


def log(state_dir, message):
    with (state_dir / 'bot.log').open('a') as stream:
        stream.write(f'{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {message}\n')


def list_review_requests(repo):
    """나에게 직접 요청된(팀 요청 제외) 열린 PR 중 draft가 아닌 것."""
    return json.loads(gh('pr', 'list', '-R', repo, '--search', 'user-review-requested:@me draft:false',
                         '--json', 'number,headRefOid,url', '--limit', '100'))


def view_pull_request(repo, number):
    return json.loads(gh('pr', 'view', str(number), '-R', repo, '--json', 'number,headRefOid,url'))


def current_login():
    return gh('api', 'user', '--jq', '.login').strip()


def has_review_on(repo, number, head, login):
    query = f'.[] | select(.user.login == "{login}" and .commit_id == "{head}") | .id'
    return bool(gh('api', f'repos/{repo}/pulls/{number}/reviews', '--paginate', '--jq', query).strip())


def gh(*args):
    return subprocess.run(['gh', *args], env=ENV, capture_output=True, text=True, check=True,
                          timeout=COMMAND_TIMEOUT_SECONDS).stdout


def run_claude(prompt, settings, run_dir):
    command = [str(CLAUDE), '-p', prompt, *MODEL_ARGS, '--setting-sources', 'local', '--settings', str(settings),
               '--strict-mcp-config', '--no-chrome', '--permission-mode', 'dontAsk', '--tools', TOOLS,
               '--output-format', 'stream-json', '--verbose']
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
