#!/usr/bin/env python3
"""Machine steps of the rules-refresh skill: rule metrics, PR cases, sandboxed review replay, launchd run."""

import argparse
import calendar
from collections import Counter, defaultdict
import datetime
import difflib
import hashlib
import html
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import traceback

HOME = Path.home()
REPO = HOME / 'git/mac-setup'
NOTES = HOME / 'plans/ai-rules-refresh/notes'
CLAUDE = HOME / '.local/bin/claude'
LABEL = 'local.rules-refresh'
PLIST = HOME / f'Library/LaunchAgents/{LABEL}.plist'

TARGETS = ('claude/CLAUDE.md', 'codex/AGENTS.md', 'claude/lib', 'private/claude/lib',
           'private/claude/instructions', 'claude/skills', 'private/claude/skills', 'scripts')
RULE_SUFFIXES = ('.md', '.yaml')
CODE_SUFFIXES = ('.sh', '.py', '.js', '.mjs', '.cjs', '.html', '.css')
SKIPPED_DIRS = {'vendor', '__pycache__', 'node_modules'}
SECRET_NAME = re.compile(r'token|api_key|apikey|credential', re.I)
LIST_ITEM = re.compile(r'^\s*(?:[-*]|\d+\.)\s+')
TABLE_RULE = re.compile(r'^\|[\s:|-]+$')
DUPLICATE_MIN_CHARS = 20

AI_REVIEW_MARK = '🤖 ai-review가 작성한 리뷰입니다.'
REVIEW_BOTS = HOME / '.claude/lib/review-bots/index.md'
REVIEW_LOG_HEADER = re.compile(r'^## (\d{4}-\d{2}-\d{2}) (\S+) (?:전체|증분) ([0-9a-f]{7,40})\.\.([0-9a-f]{7,40})')
HTML_HEADS = (r'대상(?: 커밋)? (?:<code>)?([0-9a-f]{7,40})\b',
              r'(?<![/\w])(?:head|HEAD) (?:<(?:span class="mono"|code)>)?([0-9a-f]{7,40})\b')
REVIEW_LOG_FINDING = re.compile(r'^- (AUTO-FIXED|승인 후 수정|보류|기각|남김) · ([^·]+?) · (.+)$')
PATCH_LINES_PER_FILE = 150
TEXT_LIMIT = 4000

PROTECTED = ('claude/skills/productivity/rules-refresh', 'claude/settings.json', 'private/claude/settings.json',
             'claude/hooks', 'private/claude/hooks', 'codex/hooks', 'codex/hooks.json', 'codex/config.toml',
             'private/claude/lib/security', 'claude/lib/review/security-gate.md', 'claude/lib/owasp.md',
             'claude/skills/engineering/cso', 'private/claude/skills/sec-review')
CRITERIA = (HOME / 'Downloads/Obsidian Vault/개발 방법론.md', HOME / 'Downloads/Obsidian Vault/Simple Design.md')
APPROVAL_WORDS = re.compile(r'승인|허용|권한|묻지 않|재확인|확인 없이')
RUN_TRAILER = 'Rules-Refresh:'
PERIODIC_PROMPT = ('~/.claude/CLAUDE.md와 그 파일의 @ 줄이 가리키는 파일을 Read하고 따른다. '
                   '그다음 ~/.claude/skills/rules-refresh/SKILL.md를 Read하고 인자 `주기`로 수행한다.')
EDITABLE = ('~/git/mac-setup/claude/**', '~/git/mac-setup/private/claude/lib/**', '~/git/mac-setup/private/claude/skills/**',
            '~/git/mac-setup/private/claude/instructions/**', '~/git/mac-setup/scripts/**', '~/git/mac-setup/README.md',
            '~/.claude/CLAUDE.md', '~/.claude/lib/**', '~/.claude/instructions/**', '~/.claude/skills/**',
            '~/.claude/projects/*/memory/**', '~/plans/ai-rules-refresh/notes/**')
READABLE = EDITABLE + ('~/git/mac-setup/codex/**', '~/.codex/AGENTS.md', '~/.codex/history.jsonl',
                       '~/Downloads/Obsidian Vault/개발 방법론.md', '~/Downloads/Obsidian Vault/Simple Design.md')
TOOL = '~/.claude/skills/rules-refresh/refresh.py'
COMMANDS = tuple(f'git -C ~/git/mac-setup {verb}*' for verb in
                 ('status', 'log', 'diff', 'show', 'add', 'commit', 'rev-parse', 'ls-files')) + (
    'bash ~/git/mac-setup/scripts/*', 'python3 ~/git/mac-setup/scripts/*', f'python3 {TOOL} *',
    'mkdir -p ~/plans/ai-rules-refresh/notes/*', 'date*', 'wc *', 'cd *', 'gh api repos/*/commits/*',
    '/bin/cp -p ~/git/mac-setup/private/* ~/plans/ai-rules-refresh/notes/backups/*',
    '/bin/cp -p ~/.claude/projects/* ~/plans/ai-rules-refresh/notes/backups/*',
)
PERIODIC_COMMANDS = tuple(f'Bash({c})' for c in COMMANDS) + tuple(f'Bash({c.replace("~", str(HOME))})' for c in COMMANDS)
PERIODIC_DENIED = tuple(f'Edit(~/git/mac-setup/{path})' for path in PROTECTED) + tuple(
    f'Edit({path})' for path in (
        '~/.claude/skills/rules-refresh/**', '~/.claude/settings.json', '~/.claude/hooks/**', '~/.claude/lib/security/**',
        '~/Downloads/Obsidian Vault/**')) + tuple(
    f'Bash(python3 {tool} {verb}*)' for tool in (TOOL, TOOL.replace('~', str(HOME))) for verb in ('run', 'install')) + tuple(
    f'Bash(gh api * {flag}*)' for flag in ('-X', '--method', '-f', '-F', '--field', '--raw-field', '--input')) + (
    'Read(**/.env)', 'Read(~/.claude/.credentials.json)', 'Read(~/.codex/auth.json)', 'Read(**/*token*)',
    'Read(**/*api_key*)', 'WebFetch', 'WebSearch')
CODEX_HISTORY = HOME / '.codex/history.jsonl'
MEMORY_GLOB = '.claude/projects/*/memory/feedback_*.md'

REPLAY_PROMPT = (
    '리뷰 재생이다. {review}/find-issues.md를 Read하고 1·2·3·5절을 수행한다. 4절 다른 AI 교차 검증과 '
    '`~/.claude/lib/coding/load-rules.md` 5번(계획·review-log)은 건너뛴다. 입력: diff 파일 {diff}, '
    '기준 커밋 {base}, 대상 커밋 {head}, 대상 경로 {repo}, 의도 {intent}(PR 제목·본문), '
    '바뀐 파일의 최근 커밋 기록 {history}. git 명령 대신 이 파일들과 대상 경로의 코드를 읽는다. '
    '리뷰 기준 파일은 {review} 아래 것을 읽는다. 마지막에 이슈 리포트 전체를 {result}에 Write한다.'
)
REPLAY_FORBIDDEN_TOOLS = {'Bash', 'WebFetch', 'WebSearch'}
HEADLESS_MODEL = ('--model', 'opus', '--effort', 'xhigh')
HEADLESS_TIMEOUT_HOURS = 6


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('metrics', help='Count rule files, sections, rules, lines and duplicate lines')
    inputs = commands.add_parser('inputs', help='Print criteria hashes, git status and everything changed since SINCE')
    inputs.add_argument('since', help='ISO time')
    diff = commands.add_parser('diff', help='Write the git diff of PATHS plus backup diffs of DAY to OUT')
    diff.add_argument('out', type=Path)
    diff.add_argument('day', help='YYYY-MM-DD backup folder')
    diff.add_argument('paths', nargs='*', help='mac-setup paths this run changed (all when empty)')
    codex = commands.add_parser('codex', help='Run the codex-companion script with the given arguments')
    codex.add_argument('rest', nargs=argparse.REMAINDER)
    collect = commands.add_parser('pr-collect', help='Write one case file per PR merged in MONTH')
    collect.add_argument('month', help='YYYY-MM')
    collect.add_argument('out', type=Path)
    tally = commands.add_parser('pr-tally', help='Sum the judged files of a month folder')
    tally.add_argument('folder', type=Path)
    replay = commands.add_parser('replay', help="Replay my review at the case's first external review commit")
    replay.add_argument('case', type=Path)
    replay.add_argument('out', type=Path)
    replay.add_argument('--rules', type=Path, help='Directory holding a changed copy of lib/review')
    commands.add_parser('run', help='Run the periodic mode headless and notify (launchd entry)')
    commands.add_parser('install', help='Register the weekly LaunchAgent')
    args = parser.parse_args()
    if args.command == 'metrics':
        print(json.dumps(measure_rules(REPO), ensure_ascii=False, indent=2))
    elif args.command == 'inputs':
        print(periodic_inputs(args.since))
    elif args.command == 'diff':
        notes_path(args.out).write_text(run_diff(NOTES / 'backups' / args.day, args.paths))
        print(args.out)
    elif args.command == 'codex':
        script = sorted(HOME.glob('.claude/plugins/cache/openai-codex/codex/*/scripts/codex-companion.mjs'))[-1]
        sys.exit(subprocess.run(['node', str(script), *args.rest]).returncode)
    elif args.command == 'pr-collect':
        collect_cases(args.month, notes_path(args.out))
    elif args.command == 'pr-tally':
        print(tally_judged([json.loads(p.read_text()) for p in sorted((args.folder / 'judged').glob('*.json'))]))
    elif args.command == 'replay':
        print(json.dumps(replay_review(json.loads(args.case.read_text()), notes_path(args.out), args.rules),
                         ensure_ascii=False, indent=2))
    elif args.command == 'run':
        sys.exit(run_periodic())
    else:
        install_agent()


def notes_path(path):
    resolved = path.expanduser().resolve()
    if NOTES.resolve() not in resolved.parents:
        sys.exit(f'{path} is outside {NOTES}')
    return resolved


def is_secret(path):
    return path.name == '.env' or bool(SECRET_NAME.search(path.name))


def measure_rules(repo):
    rules = {'files': 0, 'lines': 0, 'sections': 0, 'rules': 0}
    code = {'files': 0, 'lines': 0}
    seen = defaultdict(list)
    for path in target_files(repo):
        text = path.read_text(encoding='utf-8', errors='replace')
        bucket = rules if path.suffix in RULE_SUFFIXES else code
        bucket['files'] += 1
        bucket['lines'] += text.count('\n')
        if bucket is code:
            continue
        for kind, line in rule_lines(text):
            rules[kind + 's'] += 1
            key = re.sub(r'[\s`*_|]+', ' ', LIST_ITEM.sub('', line)).strip()
            if kind == 'rule' and len(key) >= DUPLICATE_MIN_CHARS:
                seen[key].append(str(path.relative_to(repo)))
    repeated = {key: places for key, places in seen.items() if len(places) > 1}
    rules['duplicates'] = sum(len(places) - 1 for places in repeated.values())
    top = sorted(repeated.items(), key=lambda item: -len(item[1]))[:10]
    rules['top_duplicates'] = [{'line': key[:120], 'places': places} for key, places in top]
    return {'rules': rules, 'code': code}


def target_files(repo):
    for target in TARGETS:
        path = repo / target
        files = [path] if path.is_file() else sorted(p for p in path.rglob('*') if p.is_file())
        for file in files:
            if (not file.is_symlink() and SKIPPED_DIRS.isdisjoint(file.parts) and not is_secret(file)
                    and file.suffix in RULE_SUFFIXES + CODE_SUFFIXES):
                yield file


def rule_lines(text):
    lines = text.split('\n')
    if lines[0] == '---' and '---' in lines[1:]:
        lines = lines[lines.index('---', 1) + 1:]
    fenced = False
    for line in lines:
        if line.lstrip().startswith('```'):
            fenced = not fenced
        elif fenced or not line.strip() or TABLE_RULE.match(line.strip()):
            continue
        elif line.startswith('#'):
            yield 'section', line
        elif LIST_ITEM.match(line) or not line[0].isspace():
            yield 'rule', line


def periodic_inputs(since):
    moment = datetime.datetime.fromisoformat(since.replace('Z', '+00:00')).astimezone()
    epoch = moment.timestamp()
    private = [p for root in ('lib', 'skills', 'instructions') for p in sorted((REPO / 'private/claude' / root).rglob('*'))
               if p.is_file() and SKIPPED_DIRS.isdisjoint(p.parts) and not is_secret(p)]
    messages = [json.loads(line) for line in CODEX_HISTORY.read_text(encoding='utf-8').split('\n') if line.startswith('{')]
    return '\n'.join([
        '# 기준 sha256', *(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p}' for p in CRITERIA),
        '# 작업 중 경로(git status)', git(REPO, 'status', '--short').rstrip(),
        '# 다른 세션이 고친 규칙(git log)',
        git(REPO, 'log', f'--since={moment.isoformat()}', '--date=iso', '--format=%h %ad %s', '--name-only', '--',
            'claude', 'codex/AGENTS.md', 'scripts').rstrip(),
        '# git 밖 private 변경', *changed_since(private, epoch),
        '# 바뀐 피드백 메모리', *changed_since(sorted(HOME.glob(MEMORY_GLOB)), epoch),
        '# Codex 사용자 메시지',
        *(f"{datetime.datetime.fromtimestamp(m['ts']):%Y-%m-%d %H:%M} {' '.join(m['text'].split())[:1000]}"
          for m in messages if m['ts'] > epoch),
    ])


def changed_since(paths, epoch):
    return [f'{datetime.datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M} {p}' for p in paths
            if p.stat().st_mtime > epoch]


def run_diff(day, paths):
    parts = [git(REPO, 'diff', 'HEAD', '--', *paths)]
    for path in git(REPO, 'ls-files', '--others', '--exclude-standard', '--', *paths).splitlines():
        if not is_secret(Path(path)):
            parts.append(unified('/dev/null', path, '', (REPO / path).read_text(encoding='utf-8', errors='replace')))
    for backup in sorted(p for p in day.rglob('*') if p.is_file() and not is_secret(p)):
        original = HOME / backup.relative_to(day)
        now = original.read_text(encoding='utf-8', errors='replace') if original.exists() else ''
        parts.append(unified(f'backup/{backup.relative_to(day)}', str(original),
                             backup.read_text(encoding='utf-8', errors='replace'), now))
    return '\n'.join(parts)


def unified(old_name, new_name, old, new):
    return ''.join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), old_name, new_name))


def collect_cases(month, out):
    me = gh(['api', 'user', '--jq', '.login']).strip()
    year, number = map(int, month.split('-'))
    period = f'{month}-01..{month}-{calendar.monthrange(year, number)[1]:02d}'
    prs = set()
    for role in ('--author=@me', '--reviewed-by=@me'):
        found = json.loads(gh(['search', 'prs', role, '--merged-at', period, '--limit', '300',
                               '--json', 'repository,number']))
        prs |= {(pr['repository']['nameWithOwner'], pr['number']) for pr in found}
    owners = {name.split('/')[1]: name.split('/')[0] for name, _ in prs}
    html_reviews = read_review_html(HOME / 'pr_reviews', owners)
    prs |= set(html_reviews)
    logs = read_review_logs(HOME / 'plans')
    markers = read_bot_markers(REVIEW_BOTS)
    (out / 'cases').mkdir(parents=True, exist_ok=True)
    index = []
    for name, pr_number in sorted(prs):
        pr = fetch_pr(name, pr_number)
        if not pr['mergedAt'] or not pr['mergedAt'].startswith(month):
            continue
        resolved = merge_resolutions(name, pr)
        case = build_case(name, pr, me, markers, html_reviews.get((name, pr_number)), logs.get(pr['headRefName'], []), resolved)
        patch_oids = sorted({oid for oids in case['post_commits'].values() for oid in oids})
        case['patches'] = {oid: truncated('(병합 충돌 해결)', resolved[oid]) if oid in resolved else commit_patch(name, oid)
                           for oid in patch_oids}
        path = out / 'cases' / f"{name.replace('/', '__')}__{pr_number}.json"
        path.write_text(json.dumps(case, ensure_ascii=False, indent=1))
        index.append({'pr': f'{name}#{pr_number}', 'case': str(path),
                      'groups': sorted({review['group'] for review in case['reviews']}),
                      'post_commits': len(patch_oids), 'first_external_commit': case['first_external_commit']})
    (out / 'prs.json').write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f'{len(index)} PRs merged in {month} -> {out}/prs.json')


def gh(args):
    return subprocess.run(['gh', *args], check=True, capture_output=True, text=True).stdout


def read_review_html(root, owners):
    reviews = {}
    for path in sorted(root.glob('*/*/review.html')):
        text = path.read_text(encoding='utf-8')
        repo_name, number = path.parent.parent.name, int(re.search(r'(\d+)$', path.parent.name).group(1))
        named = re.search(r'PR 리뷰 리포트 · ([\w.-]+)/([\w.-]+)<', text)
        owner = named.group(1) if named else owners.get(repo_name) or clone_owner(repo_name)
        head = next(filter(None, (re.search(pattern, text) for pattern in HTML_HEADS)), None)
        if not owner:
            continue
        findings = [html_finding(block.split('</section>')[0]) for block in text.split('<div class="issue issue--')[1:]]
        modified = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
        reviews[(f'{owner}/{repo_name}', number)] = {
            'group': 'mine', 'source': 'review-html', 'author': 'me', 'commit': head.group(1) if head else None,
            'at': to_utc(modified.isoformat()), 'findings': findings, 'body': ''}
    return reviews


def html_finding(block):
    loc = re.search(r'class="loc mono">(.*?)</span>', block, re.S)
    return {'severity': re.match(r'\w+', block).group(0).upper(), 'path': strip_tags(loc.group(1)) if loc else '',
            'text': ' '.join(strip_tags(re.split(r'class="desc"[^>]*>', block.split('>', 1)[-1], maxsplit=1)[-1]).split())[:TEXT_LIMIT]}


def clone_owner(repo_name):
    for clone in sorted(HOME.glob(f'*/{repo_name}/.git')):
        url = subprocess.run(['git', '-C', str(clone.parent), 'remote', 'get-url', 'origin'],
                             capture_output=True, text=True).stdout
        found = re.search(r'github\.com[:/]([\w.-]+)/', url)
        if found:
            return found.group(1)
    return None


def to_utc(timestamp):
    moment = datetime.datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
    return moment.astimezone(datetime.timezone.utc).isoformat()


def strip_tags(fragment):
    return html.unescape(re.sub(r'<[^>]+>', '', fragment)).strip()


def read_review_logs(root):
    entries = defaultdict(list)
    for path in sorted(root.glob('**/review-log.md')):
        entry = None
        for line in path.read_text(encoding='utf-8').split('\n'):
            header = REVIEW_LOG_HEADER.match(line)
            if header:
                day, branch, _, head = header.groups()
                entry = {'group': 'mine', 'source': f'review-log {path}', 'author': 'me', 'commit': head,
                         'at': to_utc(f'{day}T23:59:59+09:00'), 'findings': [], 'body': ''}
                entries[branch].append(entry)
            elif line.startswith('## '):
                entry = None
            elif entry is not None:
                finding = REVIEW_LOG_FINDING.match(line)
                if finding:
                    outcome, location, text = finding.groups()
                    entry['findings'].append({'severity': outcome, 'path': location.strip(), 'text': text})
    return entries


def read_bot_markers(path):
    if not path.exists():
        return {}
    section = path.read_text(encoding='utf-8').split('## 봇 리뷰 판별', 1)
    if len(section) == 1:
        return {}
    markers = {}
    for accounts, marker in re.findall(r'^\| (`[^|]+) \| `([^`]+)` \|$', section[1].split('\n## ')[0], re.M):
        for account in re.findall(r'`([^`]+)`', accounts):
            markers[account] = marker
    return markers


def fetch_pr(name, number):
    owner, repo = name.split('/')
    query = '''query($owner:String!,$repo:String!,$number:Int!){repository(owner:$owner,name:$repo){
      pullRequest(number:$number){number title url mergedAt baseRefName headRefName headRefOid author{login}
        commits(last:250){nodes{commit{oid committedDate messageHeadline parents(first:2){nodes{oid}}}}}
        reviews(first:100){nodes{author{login __typename} body submittedAt commit{oid}
          comments(first:100){nodes{path line originalLine body}}}}
        comments(first:100){nodes{author{login __typename} body createdAt}}
        timelineItems(itemTypes:[REVIEW_REQUESTED_EVENT],last:100){nodes{... on ReviewRequestedEvent{createdAt}}}}}}'''
    data = json.loads(gh(['api', 'graphql', '-f', f'query={query}', '-F', f'owner={owner}', '-F', f'repo={repo}',
                          '-F', f'number={number}']))
    return data['data']['repository']['pullRequest']


def build_case(name, pr, me, markers, html_review, log_reviews, resolved):
    author = (pr['author'] or {}).get('login', '')
    commits = [{'oid': node['commit']['oid'], 'at': to_utc(node['commit']['committedDate']),
                'headline': node['commit']['messageHeadline'],
                'parents': [parent['oid'] for parent in node['commit']['parents']['nodes']]}
               for node in pr['commits']['nodes']]
    reviews = []
    for node in pr['reviews']['nodes']:
        group = classify(node['author'], node['body'], author, me, markers)
        if group:
            findings = [{'path': c['path'], 'line': c['line'] or c['originalLine'], 'text': c['body'][:TEXT_LIMIT]}
                        for c in node['comments']['nodes']]
            reviews.append({'group': group, 'source': 'github-review', 'author': node['author']['login'],
                            'commit': (node['commit'] or {}).get('oid'), 'at': to_utc(node['submittedAt']),
                            'findings': findings, 'body': node['body'][:TEXT_LIMIT]})
    skipped = 0
    for node in pr['comments']['nodes']:
        group = classify(node['author'], node['body'], author, me, markers)
        if group == 'bot' and node['author']['login'] not in markers:
            skipped += 1
        elif group:
            reviews.append({'group': group, 'source': 'issue-comment', 'author': node['author']['login'],
                            'commit': None, 'at': to_utc(node['createdAt']), 'findings': [],
                            'body': node['body'][:TEXT_LIMIT]})
    if html_review:
        reviews.append(html_review)
    reviews.extend(dict(review) for review in log_reviews
                   if author == me and any(c['oid'].startswith(review['commit']) for c in commits))
    reviews.sort(key=lambda review: review['at'])
    chain = first_parent_chain(commits, pr['headRefOid'])
    post = {str(i): post_commits(chain, review['commit'], review['at'], resolved) for i, review in enumerate(reviews)}
    requests = [to_utc(node['createdAt']) for node in pr['timelineItems']['nodes']]
    external = [review for review in reviews if review['group'] != 'mine']
    return {
        'pr': {'name': name, 'number': pr['number'], 'url': pr['url'], 'title': pr['title'], 'author': author,
               'merged_at': pr['mergedAt'], 'base': pr['baseRefName'], 'head_ref': pr['headRefName'],
               'head': pr['headRefOid']},
        'commits': commits,
        'reviews': reviews,
        'skipped_bot_comments': skipped,
        'commits_truncated': len(commits) >= 250,
        'post_commits': post,
        'miss_commits': {i: before_next_request(chain, oids, reviews[int(i)]['at'], requests) for i, oids in post.items()},
        'unresolved_merges': sorted(c['oid'] for c in chain if len(c['parents']) > 1 and c['oid'] not in resolved),
        'first_external_commit': (external[0]['commit'] or seen_commit(commits, chain, None, external[0]['at'])) if external else None,
    }


def classify(account, body, author, me, markers):
    if not account or account['login'] == author:
        return 'mine' if account and account['login'] == me and AI_REVIEW_MARK in body else None
    login = account['login']
    if login == me and AI_REVIEW_MARK in body:
        return 'mine'
    if account['__typename'] == 'Bot' or (login in markers and markers[login] in body):
        return 'bot'
    return 'human'


def first_parent_chain(commits, head):
    by_oid = {commit['oid']: commit for commit in commits}
    chain, oid = [], head
    while oid in by_oid:
        chain.append(by_oid[oid])
        oid = (by_oid[oid]['parents'] or [None])[0]
    return chain[::-1]


def seen_commit(commits, chain, commit, at):
    match = next((c['oid'] for c in commits if commit and c['oid'].startswith(commit)), None)
    before = [c['oid'] for c in chain if c['at'] <= at]
    return match or (before[-1] if before else None)


def post_commits(chain, commit, at, resolved):
    seen = seen_commit(chain, chain, commit, at)
    oids = [c['oid'] for c in chain]
    start = oids.index(seen) + 1 if seen else 0
    return [c['oid'] for c in chain[start:] if len(c['parents']) < 2 or resolved.get(c['oid'])]


def before_next_request(chain, oids, at, requests):
    """Keep the commits made before the first review request after `at`; with no later request, keep them all."""
    end = min((request for request in requests if request > at), default=None)
    made = {commit['oid']: commit['at'] for commit in chain}
    return [oid for oid in oids if end is None or made[oid] < end]


def tally_judged(judged):
    lines = [f'PR {len(judged)}개', '| 묶음 | 리뷰한 PR | 잡은 것 | 놓친 것 | 헛짚은 것 |', '|---|---|---|---|---|']
    for group, label in (('mine', '내 리뷰'), ('bot', '리뷰봇'), ('human', '사람 리뷰')):
        rows = [j['groups'][group] for j in judged if j['groups'].get(group)]
        sums = (sum(row.get(key, 0) for row in rows) for key in ('caught', 'missed', 'false_positive'))
        lines.append(f'| {label} | {len(rows)} | ' + ' | '.join(map(str, sums)) + ' |')
    classes = Counter(miss['class'] for j in judged for miss in j.get('my_misses', []))
    lines.append('내가 놓친 것: ' + ' · '.join(f'{name} {classes[name]}' for name in ('맥락 밖', '찾고 버림', '지식 공백', '탐지 공백')))
    criteria = Counter(caught['criterion'] for j in judged for caught in j.get('my_caught', []))
    lines.append('잡은 리뷰 기준: ' + (', '.join(f'{name} {count}' for name, count in criteria.most_common()) or '없음'))
    return '\n'.join(lines)


def commit_patch(name, oid):
    files = json.loads(gh(['api', f'repos/{name}/commits/{oid}', '--jq', '[.files[] | {filename, patch}]']))
    return [patch for f in files for patch in truncated(f['filename'], f.get('patch') or '')]


def truncated(name, text):
    lines = text.split('\n')
    return [{'file': name, 'patch': '\n'.join(lines[:PATCH_LINES_PER_FILE]), 'patch_lines': len(lines),
             'truncated': len(lines) > PATCH_LINES_PER_FILE}]


def merge_resolutions(name, pr):
    owner, repo = name.split('/')
    clone = HOME / owner.lower() / repo
    resolved = {}
    for node in pr['commits']['nodes']:
        oid = node['commit']['oid']
        if len(node['commit']['parents']['nodes']) > 1 and clone.is_dir() and not subprocess.run(
                ['git', '-C', str(clone), 'cat-file', '-e', f'{oid}^{{commit}}'], capture_output=True).returncode:
            resolved[oid] = hand_resolved(git(clone, 'show', '--cc', '--format=', oid))
    return resolved


def hand_resolved(combined):
    hunks, header = [], None
    for line in combined.split('\n'):
        if line.startswith('diff --cc'):
            header = line
        elif line.startswith('@@@'):
            hunks.append([header, line])
        elif hunks and line[:2] in ('++', '--') and not line.startswith(('+++ ', '--- ')):
            hunks[-1].append(line)
    kept, last = [], None
    for header, *lines in (hunk for hunk in hunks if len(hunk) > 2):
        kept += ([header] if header != last else []) + lines
        last = header
    return '\n'.join(kept)


def replay_review(case, out, rules):
    name, number, head = case['pr']['name'], case['pr']['number'], case['first_external_commit']
    owner, repo_name = name.split('/')
    clone = HOME / owner.lower() / repo_name
    isolated = out / repo_name
    out.mkdir(parents=True, exist_ok=True)
    result, check_file = out / 'result.md', out / 'replay-check.json'
    result.unlink(missing_ok=True)
    check_file.unlink(missing_ok=True)
    if not head:
        sys.exit(f'{name}#{number}: no external review commit to pin')
    git(clone, 'fetch', 'origin', '--quiet')
    if subprocess.run(['git', '-C', str(clone), 'cat-file', '-e', f'{head}^{{commit}}']).returncode:
        git(clone, 'fetch', 'origin', '--quiet', head)
    base = git(clone, 'merge-base', f"refs/remotes/origin/{case['pr']['base']}", head).strip()
    subprocess.run(['git', 'init', '-q', str(isolated)], check=True)
    git(isolated, 'fetch', '--quiet', '--no-tags', str(clone), head)
    git(isolated, 'checkout', '--quiet', '--detach', head)
    (isolated / '.git/FETCH_HEAD').unlink(missing_ok=True)
    diff = out / f'{repo_name}-{number}.diff'
    diff.write_text(git(isolated, 'diff', '--no-ext-diff', '--no-textconv', base, head))
    history = out / 'history.txt'
    history.write_text('\n'.join(
        f'## {path}\n' + git(isolated, 'log', '-n', '20', '--format=%h %ad %an %s', '--date=short', head, '--', path)
        for path in git(isolated, 'diff', '--name-only', base, head).splitlines()))
    pr = json.loads(gh(['pr', 'view', str(number), '-R', name, '--json', 'title,body']))
    intent = out / 'intent.md'
    intent.write_text(f"# {pr['title']}\n\n{pr['body']}\n")
    review = rules_copy(rules, out) if rules else HOME / '.claude/lib/review'
    prompt = REPLAY_PROMPT.format(review=review, diff=diff, base=base, head=head, repo=isolated, intent=intent,
                                  history=history, result=result)
    allowed = ['Agent', f'Edit(/{result})', f'Read(/{out}/**)', 'Read(~/Downloads/Obsidian Vault/Simple Design.md)']
    allowed += [f'Read({root}/lib/**)' for root in ('~/.claude', '~/git/mac-setup/claude', '~/git/mac-setup/private/claude')]
    denied = ['Read(**/.env)']
    if rules:
        denied += [f'Read({root}/lib/review/**)' for root in ('~/.claude', '~/git/mac-setup/claude')]
    transcript = out / 'transcript.jsonl'
    code = run_headless(prompt, 'Read,Grep,Glob,Agent,Write', allowed, denied, out, transcript)
    check = check_replay(transcript, out, isolated, head, clone)
    check.update({'exit': code, 'base': base, 'result': str(result), 'result_written': result.is_file()})
    check_file.write_text(json.dumps(check, ensure_ascii=False, indent=1))
    return check


def git(path, *args):
    return subprocess.run(['git', '-C', str(path), *args], check=True, capture_output=True, text=True).stdout


def rules_copy(rules, out):
    target = out / 'review'
    target.mkdir(exist_ok=True)
    for source in rules.rglob('*.md'):
        destination = target / source.relative_to(rules)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(source.read_text(encoding='utf-8').replace('~/.claude/lib/review/', f'{target}/'))
    return target


def check_replay(transcript, out, isolated, head, clone):
    calls, denials = {}, []
    *lines, last = transcript.read_bytes().split(b'\n')
    events = [json.loads(line) for line in lines if line.startswith(b'{')]
    if last.startswith(b'{'):
        try:  # claude killed at run_headless's time limit can leave its last line cut, even inside a UTF-8 character
            events.append(json.loads(last))
        except ValueError:
            pass
    for event in events:
        if event.get('type') == 'assistant':
            calls.update({block['id']: block for block in event['message']['content'] if block.get('type') == 'tool_use'})
        if event.get('type') == 'result':
            denials = event.get('permission_denials', [])
    denied_ids = {denial['tool_use_id'] for denial in denials}
    calls.update({denial['tool_use_id']: {'name': denial['tool_name'], 'input': denial['tool_input']}
                  for denial in denials if denial['tool_use_id'] not in calls})
    attempts = [{'tool': call['name'], 'input': json.dumps(call['input'], ensure_ascii=False)[:300],
                 'blocked': call_id in denied_ids}
                for call_id, call in calls.items() if forbidden_call(call, out)]
    reachable = int(git(isolated, 'rev-list', '--count', head))
    actual = git(isolated, 'rev-parse', 'HEAD').strip()
    return {
        'head': actual,
        'head_pinned': actual == head,
        'refs': git(isolated, 'for-each-ref', '--format=%(refname)').split(),
        'commits_outside_head': int(git(isolated, 'rev-list', '--all', '--count')) - reachable,
        'clone_history_matches': reachable == int(git(clone, 'rev-list', '--count', head)),
        'tool_calls': len(calls),
        'forbidden_attempts': attempts,
        'forbidden_succeeded': sum(1 for attempt in attempts if not attempt['blocked']),
        'permission_denials': len(denials),
    }


def forbidden_call(call, out):
    if call['name'] in REPLAY_FORBIDDEN_TOOLS:
        return True
    text = json.dumps(call['input'], ensure_ascii=False)
    paths = re.findall(r'(?:/Users/[^/"\s]+|~)/(?:plans|pr_reviews)(?:/[^"\s]*)?', text)
    return any(not path.replace('~', str(HOME), 1).startswith(str(out)) for path in paths)


def run_periodic():
    started = datetime.datetime.now()
    run_dir = NOTES / 'runs' / started.strftime('%Y%m%d-%H%M%S')
    run_dir.mkdir(parents=True, exist_ok=True)
    try:
        final, message = periodic_result(started, run_dir)
    except Exception as error:
        # A crash must still notify, or a failed weekly run goes unnoticed until someone looks for its report.
        traceback.print_exc()
        final, message = 1, f'실행 중 오류 {type(error).__name__}: {error}'
    notify(f'규칙 갱신 종료 코드 {final}', f'{message} · 기록 {run_dir}')
    (run_dir / 'exit-code').write_text(f'{final}\n')
    return final


def periodic_result(started, run_dir):
    head, protected = git(REPO, 'rev-parse', 'HEAD').strip(), protected_digest()
    code = run_headless(PERIODIC_PROMPT, 'Read,Grep,Glob,Edit,Write,Bash,Agent',
                        ['Agent', *(f'Read({p})' for p in READABLE), *(f'Edit({p})' for p in EDITABLE), *PERIODIC_COMMANDS],
                        PERIODIC_DENIED, REPO, run_dir / 'transcript.jsonl')
    problems = run_problems(head, protected, started.timestamp())
    if code is None:
        problems.insert(0, f'{HEADLESS_TIMEOUT_HOURS}시간 안에 끝나지 않아 claude를 멈춤')
    report = latest_report(started.timestamp())
    if report is None:
        problems.append('리포트 없음')
    message = ' · '.join(problems) or report.read_text(encoding='utf-8').split('\n', 1)[0].lstrip('# ')
    return code or (3 if problems else 0), message


def run_headless(prompt, tools, allowed, denied, cwd, transcript):
    """Return claude -p's exit code, or None when it was killed after HEADLESS_TIMEOUT_HOURS."""
    command = [str(CLAUDE), '-p', prompt, *HEADLESS_MODEL, '--setting-sources', 'local', '--strict-mcp-config', '--no-chrome',
               '--permission-mode', 'dontAsk', '--tools', tools, '--allowedTools', *allowed, '--disallowedTools', *denied,
               '--output-format', 'stream-json', '--verbose']
    with transcript.open('w') as stream:
        try:
            return subprocess.run(command, cwd=cwd, env=headless_env(), stdin=subprocess.DEVNULL, stdout=stream,
                                  stderr=subprocess.STDOUT, timeout=HEADLESS_TIMEOUT_HOURS * 3600).returncode
        except subprocess.TimeoutExpired:
            return None


def headless_env():
    path = f'{HOME}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'
    # Print mode stops background subagents still running 10 minutes after the last turn, so a run that ends its turn
    # to wait for them exits without their results; 0 waits for them, and run_headless kills claude at its time limit.
    return {'HOME': str(HOME), 'USER': os.environ.get('USER', HOME.name), 'PATH': path, 'SHELL': '/bin/bash',
            'LANG': 'ko_KR.UTF-8', 'TMPDIR': os.environ.get('TMPDIR', '/tmp'), 'CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS': '0'}


def latest_report(since):
    try:
        state = json.loads((NOTES / 'state.json').read_text())
    except json.JSONDecodeError:
        return None
    report = Path(state.get('last_run', {}).get('report') or NOTES / 'none')
    return report if report.is_file() and report.stat().st_mtime >= since else None


def protected_digest():
    digest = hashlib.sha256()
    for path in [*CRITERIA, *(REPO / p for p in PROTECTED)]:
        for file in sorted([path] if path.is_file() else path.rglob('*') if path.is_dir() else []):
            if file.is_file() and '__pycache__' not in file.parts:
                digest.update(f'{file} {file.stat().st_mode:o}'.encode() + file.read_bytes())
    return digest.hexdigest()


def run_problems(head, protected, since):
    problems = []
    if protected_digest() != protected:
        problems.append('보호 파일 변경 감지(다른 세션 변경일 수 있음)')
    pushes = [line for line in git(REPO, 'reflog', '--all', '--date=unix', '--format=%gd %gs').splitlines()
              if line.endswith(' update by push') and int(re.search(r'@\{(\d+)\}', line).group(1)) >= since]
    if pushes:
        problems.append(f'push 감지 {len(pushes)}건(다른 세션일 수 있음)')
    for commit in git(REPO, 'rev-list', f'{head}..HEAD', f'--grep={RUN_TRAILER}').split():
        changed = git(REPO, 'show', '--format=', '--unified=0', commit)
        lines = [line for line in changed.split('\n') if line[:1] in '+-' and line[:3] not in ('+++', '---')]
        if any(APPROVAL_WORDS.search(line) for line in lines):
            problems.append(f'승인·권한 문장 변경 의심 {commit[:7]}')
    return problems


def notify(title, message):
    script = 'on run argv\ndisplay notification (item 2 of argv) with title (item 1 of argv)\nend run'
    subprocess.run(['osascript', '-e', script, title, message], check=False, capture_output=True)


def install_agent():
    (NOTES / 'runs').mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(plistlib.dumps({
        'Label': LABEL,
        'ProgramArguments': ['/usr/bin/python3', str(Path(__file__).resolve()), 'run'],
        'StartCalendarInterval': {'Weekday': 1, 'Hour': 8, 'Minute': 47},
        'StandardOutPath': str(NOTES / 'runs/launchd.log'),
        'StandardErrorPath': str(NOTES / 'runs/launchd.log'),
    }))
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'bootout', f'{domain}/{LABEL}'], capture_output=True)
    subprocess.run(['launchctl', 'bootstrap', domain, str(PLIST)], check=True)
    print(f'{LABEL} registered: every Monday 08:47 -> {PLIST}')


if __name__ == '__main__':
    main()
