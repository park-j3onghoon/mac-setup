"""Guide existing, unmanaged Claude sessions through an account change on their own cmux surface.

The terminal offers no conditional empty-input submission. A local notification lets the user
finish their draft and run /restart. Keep the handoff until Claude publishes its new startedAt,
then offer continuation if the original limit stop is still the last real conversation event.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

CMUX_PATHS = ('/opt/homebrew/bin/cmux', '/Applications/cmux.app/Contents/Resources/bin/cmux')
CONTINUE_PROMPT = (
    '계정 전환 전에 하던 작업을 이어서 해줘. 먼저 마지막 요청, 실행 중인 프로세스와 남은 결과를 '
    '확인해줘. 완료된 작업은 반복하지 말고, 아직 실행 중이면 그 결과를 기다려줘. 중단되거나 실패한 '
    '작업은 이어갈 수 있는 지점부터 계속하고, 이어갈 수 없으면 그 작업만 처음부터 다시 실행해줘. '
    '이미 반영됐을 수 있는 작업은 실제 반영 여부부터 확인하고, 사용자 승인이나 답변이 필요하면 다시 물어봐.'
)
STATE = 'session_refresh'
# Access tokens last 8 hours (2026-11-16: refreshed at 04:50 and 08:27, expiring at 12:50 and
# 16:27); after that every session reads the live login on its next request.
REFRESH_WINDOW_SECONDS = 8 * 3600
# Longer than the service's longest usage lookup interval, 9 minutes (policy.POLL_TIERS).
SWITCH_TIMEOUT_SECONDS = 900
READY_TIMEOUT_SECONDS = 600
WAIT_STEP_SECONDS = 3
# A session stopped at a limit ends no later turn to retry from (Claude Code waits for the reset
# itself), so past READY_TIMEOUT_SECONDS its helper waits out background work, such as a
# 14-minute timer on 2026-11-16 15:06~15:13, for the restart window, checking less often.
LIMIT_WAIT_STEP_SECONDS = 30
WORKING_CHILDREN = frozenset({'zsh', 'bash', 'sh'})
MCP_NAME = re.compile(r'(?:^|[/@._-])mcp(?:$|[/._-])', re.I)
LIMIT_ERROR = re.compile(r'hit your .*limit|usage limit reached', re.I)
# User entries Claude Code writes itself. Background task notifications keep arriving after a
# limit stop (2026-11-16 11:08~11:09), so they do not mean the user asked to go on.
GENERATED_PREFIXES = ('<command-', '<local-command', '<task-notification>')
RULE_MIN_DASHES = 10
TAIL_BYTES = 262144


def find_cmux():
    return next((path for path in CMUX_PATHS if Path(path).is_file()), None)


def record_switch(state, switched_at):
    state.save(STATE, {'since': switched_at})


def switch_pending(state, now):
    """The latest switch time while sessions may still need a restart, else None."""
    since = state.load(STATE).get('since')
    if isinstance(since, (int, float)) and 0 <= now - since <= REFRESH_WINDOW_SECONDS:
        return since
    return None


def is_rule(line):
    """A border of the input box. A named session shows its name inside the top border
    (`──── my-session repo 947 ─`, 2026-11-13)."""
    text = line.strip()
    return text.startswith('─') and text.endswith('─') and text.count('─') >= RULE_MIN_DASHES


def input_ready(screen):
    """True when Claude's input box (❯ between two rules) is empty."""
    lines = screen.splitlines()
    prompts = [i for i, line in enumerate(lines) if line.strip().startswith('❯')]
    if not prompts:
        return False
    i = prompts[-1]
    if lines[i].strip() != '❯' or not 0 < i < len(lines) - 1:
        return False
    if not (is_rule(lines[i - 1]) and is_rule(lines[i + 1])):
        return False
    footer = [line.strip() for line in lines[i + 2:] if line.strip()]
    # The optional first status line names the workspace. A visible dialog below the
    # recognized mode line means the input border belongs to an older screen.
    return not footer or (len(footer) <= 2 and bool(re.fullmatch(
        r'(?:⏵⏵ |⏸ )?(?:auto mode on|accept edits on|plan mode on|bypass permissions on)'
        r'(?: \(shift\+tab to cycle\))?(?: · ← \d+ agents?)?', footer[-1], re.I)))


def notification_text(entry):
    message = entry.get('message')
    content = message.get('content') if isinstance(message, dict) else None
    if isinstance(content, str):
        return content
    origin = entry.get('origin')
    if isinstance(content, list) and (isinstance(origin, dict) and origin.get('kind') == 'task-notification'
                                      or entry.get('promptSource') == 'system'):
        return ''.join(block['text'] for block in content if isinstance(block, dict)
                       and block.get('type') == 'text' and isinstance(block.get('text'), str))
    return ''


def task_notification(entry):
    """The text of a background task notification Claude Code wrote, else ''."""
    attachment = entry.get('attachment')
    if entry.get('type') == 'attachment' and isinstance(attachment, dict):
        # Claude Code 2.1.330 queues a notification that arrives during a turn as an attachment
        # (2026-11-23: every finished agent of 10 idle sessions looked unfinished).
        prompt = attachment.get('prompt')
        return prompt if attachment.get('type') == 'queued_command' and isinstance(prompt, str) else ''
    return notification_text(entry) if entry.get('type') == 'user' and is_generated(entry) else ''


def is_generated(entry):
    origin = entry.get('origin')
    system = (entry.get('promptSource') == 'system' or
              isinstance(origin, dict) and origin.get('kind') == 'task-notification')
    return bool(entry.get('isMeta') or system and notification_text(entry).lstrip().startswith(GENERATED_PREFIXES))


def latest_message(projects_dir, session_id):
    """Newest real conversation entry; skip local commands and task notifications."""
    paths, vanished = [], False
    for path in Path(projects_dir).glob(f'*/{session_id}.jsonl'):
        try:
            paths.append((path.stat().st_mtime_ns, path))
        except FileNotFoundError:
            vanished = True
    for _, path in sorted(paths, reverse=True):
        try:
            entry = last_entry(path)
        except FileNotFoundError:
            vanished = True
            continue
        if entry is not None:
            return entry
    if vanished:
        raise SessionUnavailable('Session transcript is being replaced')
    return None


def last_entry(path):
    for line in transcript_lines(path):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        if entry.get('type') == 'assistant' or entry.get('type') == 'user' and not is_generated(entry):
            return entry
    return None


def completed(entry):
    return bool(entry and entry['type'] == 'assistant' and not entry.get('isApiErrorMessage')
                and (entry.get('message') or {}).get('stop_reason') in ('end_turn', 'stop_sequence'))


def agent_finished(path):
    """True when a subagent's newest step ended its turn or handed its report back."""
    for line in transcript_lines(path):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or entry.get('type') not in ('assistant', 'user') or is_generated(entry):
            continue
        blocks = (entry.get('message') or {}).get('content')
        blocks = [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []
        if entry['type'] == 'user' and blocks and all(block.get('type') == 'tool_result' for block in blocks):
            continue
        # Claude Code 2.1.330 subagents end by calling SubagentHandback, with no end_turn
        # (2026-11-23: all 135 agents of 7 idle sessions).
        return completed(entry) or any(block.get('name') == 'SubagentHandback' for block in blocks)
    return False


def ended_with_limit_error(projects_dir, session_id, transcript=None):
    entry = last_entry(transcript) if transcript is not None else latest_message(projects_dir, session_id)
    return is_limit_error(entry)


def is_limit_error(entry):
    if not entry or entry['type'] != 'assistant' or not entry.get('isApiErrorMessage'):
        return False
    content = (entry.get('message') or {}).get('content') or []
    text = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
    return bool(LIMIT_ERROR.search(text))


def transcript_lines(path):
    """Locate record boundaries backwards without retaining the preceding transcript."""
    with path.open('rb') as stream:
        end = offset = stream.seek(0, os.SEEK_END)
        while offset:
            size = min(offset, 32768)
            offset -= size
            stream.seek(offset)
            block = stream.read(size)
            cursor = len(block)
            while (boundary := block.rfind(b'\n', 0, cursor)) >= 0:
                start = offset + boundary + 1
                if end > start:
                    yield compact_record(stream, start, end)
                end = offset + boundary
                cursor = boundary
        if end:
            yield compact_record(stream, 0, end)


def compact_record(stream, start, end):
    """Keep JSON structure and the prefix used to recognize synthetic user messages.

    Long string values contain tool output or message text. Stop retaining their
    bytes once their prefix is known, while continuing to honor escaped quotes.
    """
    stream.seek(start)
    if end - start <= 32768:
        return stream.read(end - start)
    result = bytearray()
    inside = escaped = False
    literal = bytearray()
    truncated = False
    delimiters = re.compile(br'["\\]')
    while stream.tell() < end:
        data = stream.read(min(32768, end - stream.tell()))
        if not data:
            break
        pos = 0
        while pos < len(data):
            if not inside:
                quote = data.find(b'"', pos)
                if quote < 0:
                    result.extend(data[pos:])
                    break
                result.extend(data[pos:quote + 1])
                inside, truncated = True, False
                literal.clear()
                pos = quote + 1
                continue
            if escaped:
                if len(literal) < 4096:
                    literal.extend(data[pos:pos + 1])
                else:
                    truncated = True
                pos += 1
                escaped = False
                continue
            mark = delimiters.search(data, pos)
            stop = mark.start() if mark else len(data)
            room = 4096 - len(literal)
            literal.extend(data[pos:min(stop, pos + room)])
            truncated |= stop - pos > room
            if not mark:
                break
            pos = stop + 1
            if data[stop] == 92:
                escaped = True
                if len(literal) < 4096:
                    literal.append(92)
                else:
                    truncated = True
            else:
                if truncated:
                    # Only ASCII prefixes identify generated commands. Re-encode
                    # the prefix so a cut through an escape/UTF-8 sequence is valid.
                    prefix = bytes(literal).split(b'\\', 1)[0].decode('utf-8', 'ignore')
                    result.extend(json.dumps(prefix)[1:-1].encode())
                else:
                    result.extend(literal)
                result.append(34)
                inside = False
    if b'isApiErrorMessage' in result:
        try:
            entry = json.loads(result)
        except ValueError:
            return result
        if isinstance(entry, dict) and entry.get('isApiErrorMessage'):
            stream.seek(start)
            return stream.read(end - start)
    return result


def live_session(config_home, session_id, runner=subprocess.run, prior=None, ancestors=None):
    """This interactive session's registry entry while its pid still belongs to the same process.

    `ps -p` gets one pid: with all 15 registered pids it took 0.16 s of system time, with one
    under 0.01 s (2026-11-16)."""
    unreadable = False
    registry = Path(config_home) / 'sessions'
    pids = [prior['pid']] if prior else ancestors
    paths = (registry / f'{pid}.json' for pid in pids) if pids is not None else registry.glob('*.json')
    matches = []
    for path in paths:
        try:
            entry = json.loads(path.read_text())
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            unreadable = True
            continue
        if not isinstance(entry, dict):
            unreadable = True
            continue
        if (entry.get('sessionId') != session_id or entry.get('kind') != 'interactive'
                or type(entry.get('pid')) is not int or str(entry['pid']) != path.stem):
            continue
        result = runner(['/bin/ps', '-o', 'lstart=', '-p', str(entry['pid'])], capture_output=True,
                        text=True, timeout=5, check=False, env={'LC_ALL': 'C', 'TZ': 'UTC'})
        if result.returncode:
            try:
                os.kill(entry['pid'], 0)
            except ProcessLookupError:
                continue
            except PermissionError:
                pass
            raise subprocess.CalledProcessError(result.returncode, '/bin/ps')
        if result.stdout.strip() == entry.get('procStart'):
            if prior and prior.get('procStart', entry['procStart']) != entry['procStart']:
                continue
            if pids is not None and not unreadable:
                return entry
            matches.append(entry)
    if unreadable:
        raise SessionUnavailable("Session registry temporarily unreadable")
    if len(matches) > 1:
        raise SessionUnavailable('More than one process has this conversation open')
    return matches[0] if matches else None


def hook_ancestors():
    result = subprocess.run(['/bin/ps', '-ax', '-o', 'pid=,ppid='], capture_output=True,
                            text=True, timeout=3, check=True)
    parents = {}
    for line in result.stdout.splitlines():
        pair = line.split()
        if len(pair) == 2 and all(value.isdecimal() for value in pair):
            parents[int(pair[0])] = int(pair[1])
    chain = []
    pid = os.getppid()
    while pid > 1 and pid not in chain:
        chain.append(pid)
        pid = parents.get(pid, 0)
    return chain


def process_children(runner):
    result = runner(['/bin/ps', '-ax', '-o', 'pid=,ppid=,comm='], capture_output=True,
                    text=True, timeout=5, check=False)
    if result.returncode:
        raise subprocess.CalledProcessError(result.returncode, '/bin/ps')
    children = {}
    for line in result.stdout.splitlines():
        parts = line.split(None, 2)
        if len(parts) == 3 and parts[0].isdigit() and parts[1].isdigit():
            children.setdefault(int(parts[1]), []).append((int(parts[0]), Path(parts[2]).name))
    return children


def wraps_mcp(descendants, runner):
    if len(descendants) != 1:
        return False
    pid, name = descendants[0]
    if MCP_NAME.search(name):
        return True
    if name not in ('node', 'npm', 'npx', 'bun', 'uv', 'uvx', 'python', 'python3'):
        return False
    command = runner(['/bin/ps', '-p', str(pid), '-o', 'args='], capture_output=True,
                     text=True, timeout=5, check=False)
    try:
        argv = shlex.split(command.stdout) if not command.returncode else []
    except ValueError:
        return False
    # Only inspect the package or program that the interpreter runs, not its task arguments.
    program = next((arg for arg in argv[1:] if not arg.startswith('-')), '')
    return bool(MCP_NAME.search(program))


def background_work(session, children, projects_dir, now, runner=subprocess.run, *, check_completion=False):
    """Treat task shells, children without stdio streams, task output and unfinished subagent
    transcripts as active work."""
    servers, stack = [], [session['pid']]
    while stack:
        for child, name in children.get(stack.pop(), []):
            if name == 'caffeinate':
                continue
            # Ordinary task shells remain busy. A shell that wraps an identifiable MCP server and
            # every other child must talk over stdio streams like Claude Code's own MCP servers
            # (2026-11-23: `uv run …/mcp_server.py` and its python over unix sockets).
            if name in WORKING_CHILDREN and not wraps_mcp(children.get(child, []), runner):
                return True
            servers.append(str(child))
            stack.append(child)
    if servers:
        # A shell can exec the task, which then still writes the session's task output.
        descriptors = runner(['/usr/sbin/lsof', '-nP', '-a', '-p', ','.join(servers),
                              '-d', '0,1,2', '-Fftn'], capture_output=True, text=True,
                             timeout=5, check=False)
        if descriptors.returncode not in (0, 1) or (descriptors.returncode and descriptors.stderr):
            raise SessionUnavailable('Could not check session task output')
        regular = False
        streams = set()
        pid = fd = None
        for field in descriptors.stdout.splitlines():
            if field.startswith('p'):
                pid = field[1:]
                regular = False
            elif field.startswith('f'):
                fd = field[1:]
                regular = False
            elif field.startswith('t'):
                regular = field == 'tREG'
                if field in ('tPIPE', 'tFIFO', 'tunix'):
                    streams.add((pid, fd))
            elif regular and field.startswith('n'):
                path = Path(field[1:])
                if (path.parent.name == 'tasks' and path.parent.parent.name == session['sessionId']
                        and path.suffix == '.output'):
                    return True
        if any((pid, fd) not in streams for pid in servers for fd in ('0', '1')):
            return True
    pattern = f"*/{session['sessionId']}/subagents/*.jsonl"
    unfinished = set()
    transcripts = set()
    for path in Path(projects_dir).glob(pattern):
        if not agent_finished(path):
            unfinished.add(path.stem.removeprefix('agent-'))
            transcripts.add(path.parent.parent.with_suffix('.jsonl'))
    for path in transcripts:
        if not path.is_file():
            continue
        for line in transcript_lines(path):
            if b'<task-notification>' not in line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            content = task_notification(entry) if isinstance(entry, dict) else ''
            if content.lstrip().startswith('<task-notification>'):
                task = re.search(r'<task-id>([\w-]+)</task-id>', content)
                if task and re.search(r'<status>(completed|failed|killed|stopped)</status>', content):
                    unfinished.discard(task[1].removeprefix('agent-'))
                    if not unfinished:
                        return False
    return bool(unfinished)


class SessionUnavailable(OSError):
    pass


class SessionEnded(Exception):
    pass


class SelfRestart:
    """Observe one terminal and offer a handoff through local cmux notifications."""

    def __init__(self, state, config_home, session_id, surface, runner=subprocess.run,
                 sleep=time.sleep, clock=time.time, cmux=None, monotonic=None):
        self.state, self.config_home = state, Path(config_home)
        self.session_id, self.surface = session_id, surface
        self.runner, self.sleep, self.clock = runner, sleep, clock
        self.cmux_path = cmux or find_cmux()
        self.projects = self.config_home / 'projects'
        self.monotonic = monotonic or (time.monotonic if clock is time.time else clock)
        self.transcript = None
        self.last_session = None
        self.registry_hint = None
        self.ancestors = None
        self.first_lookup = self.monotonic()
        self.receipt = 'handoff-' + hashlib.sha256(f'{session_id}/{surface}'.encode()).hexdigest()[:32]

    def session(self):
        session = live_session(self.config_home, self.session_id, self.runner,
                               self.last_session or self.registry_hint, self.ancestors)
        if session:
            self.last_session = session
        else:
            if self.last_session is None:
                if self.ancestors is not None and self.monotonic() - self.first_lookup < 15:
                    raise SessionUnavailable('Waiting for the source process registration')
                raise SessionEnded
            pid = self.last_session['pid']
            try:
                os.kill(pid, 0)
            except ProcessLookupError as error:
                raise SessionEnded from error
            except PermissionError:
                return None
            result = self.runner(['/bin/ps', '-o', 'lstart=', '-p', str(pid)], capture_output=True,
                                 text=True, timeout=5, check=False, env={'LC_ALL': 'C', 'TZ': 'UTC'})
            if result.returncode == 0 and result.stdout.strip() != self.last_session['procStart']:
                raise SessionEnded
        return session

    def limited(self, *, retry_replacement=True):
        def check():
            if self.transcript is not None and not self.transcript.is_file():
                self.transcript = None
                if retry_replacement:
                    raise SessionUnavailable('Session transcript is being replaced')
            return (ended_with_limit_error(self.projects, self.session_id, self.transcript),)

        try:
            return check()[0]
        except (FileNotFoundError, SessionUnavailable):
            self.transcript = None
            if not retry_replacement:
                raise SessionUnavailable('Session transcript is being replaced') from None
            # A replacement may not have been published yet. Retry until evidence returns
            # or the short replacement window closes, without treating a draft as a limit.
            def replacement():
                entry = latest_message(self.projects, self.session_id)
                return (is_limit_error(entry),) if entry is not None else None

            result = self.wait(replacement, 10)
            return bool(result and result[0])

    def pending(self):
        receipt = self.state.load(self.receipt)
        since = receipt.get('since')
        return receipt if (receipt.get('phase') == 'waiting' and type(since) in (int, float)
                           and 0 <= self.clock() - since <= REFRESH_WINDOW_SECONDS) else {}

    def needed(self):
        """True when the latest switch happened after this session's process started."""
        since = switch_pending(self.state, self.clock())
        if not since:
            return False
        session = self.session()
        return bool(session and session.get('startedAt', 0) / 1000 < since)

    def run(self):
        """Wait for the switch and a quiet moment, restart, and continue after a limit stop."""
        try:
            return self._run()
        except SessionEnded:
            return 'session_ended'

    def _run(self):
        pending = self.pending()
        if pending:
            return self.confirm(pending)
        was_limited = self.limited()

        def awaiting_switch():
            if self.needed():
                return True
            if was_limited:
                self.session()
                if not self.limited():
                    raise SessionEnded
            return False

        if not self.wait(awaiting_switch, REFRESH_WINDOW_SECONDS if was_limited else SWITCH_TIMEOUT_SECONDS):
            return 'no_switch'
        since = switch_pending(self.state, self.clock())
        if since is None:
            return 'no_switch'
        def ready_before_expiry():
            if switch_pending(self.state, self.clock()) is None:
                raise SessionEnded
            return self.ready(None)
        expires = since + REFRESH_WINDOW_SECONDS
        session = self.wait(ready_before_expiry, min(READY_TIMEOUT_SECONDS,
                                                     max(0, expires - self.clock())))
        if session is None and self.limited():
            session = self.wait(ready_before_expiry, max(0, expires - self.clock()),
                                LIMIT_WAIT_STEP_SECONDS)
        if session is None:
            return 'not_ready'
        since = switch_pending(self.state, self.clock())
        if not since or session['startedAt'] / 1000 >= since:
            return 'already_restarted'
        pending = {'phase': 'waiting', 'pid': session['pid'], 'procStart': session['procStart'],
                   'startedAt': session['startedAt'], 'since': since, 'limited': self.limited()}
        self.state.save(self.receipt, pending)
        return self.confirm(pending)

    def confirm(self, pending):
        self.last_session = {key: pending[key] for key in ('pid', 'procStart', 'startedAt')}
        if not pending.get('notified'):
            current = self.wait(self.session, 15)
            if not current:
                return 'not_ready'
            if current['startedAt'] == pending['startedAt']:
                self.cmux('notify', '--surface', self.surface, '--title', 'Claude 계정 전환',
                          '--body', '초안과 실행 중인 작업을 마친 뒤 이 창에서 /restart 를 입력하세요.')
            pending['notified'] = True
            self.state.save(self.receipt, pending)

        def restarted():
            current = self.session()
            return (current and current['startedAt'] > pending['startedAt']
                    and current['startedAt'] >= pending['since'] * 1000)

        if not self.wait(restarted, max(0, pending['since'] + REFRESH_WINDOW_SECONDS - self.clock())):
            return 'awaiting_user_restart'
        if pending['limited'] and self.limited():
            self.cmux('notify', '--surface', self.surface, '--title', 'Claude 이어하기',
                      '--body', '새 계정이 적용되었습니다. 한도에서 멈춘 작업을 계속하려면 이 대화에 이어서 해 달라고 입력하세요.')
            outcome = 'continuation_offered'
        else:
            outcome = 'restarted'
        self.state.save(self.receipt, {'phase': outcome, 'since': pending['since']})
        return outcome

    def wait(self, check, timeout, step=WAIT_STEP_SECONDS):
        """Check immediately, then back off to 30 seconds; every check reads fresh state."""
        deadline = self.monotonic() + timeout
        while True:
            try:
                result = check()
                if result:
                    return result
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError, SessionUnavailable):
                # 2026-11-16 11:08: many sessions stopped at a limit at once and five helpers gave
                # up on one slow ps; a slow check only means "not ready yet".
                pass
            if self.monotonic() >= deadline:
                return None
            self.sleep(min(step, max(0, deadline - self.monotonic())))
            step = min(step * 2, LIMIT_WAIT_STEP_SECONDS)

    def ready(self, old_started):
        """Return the quiet session only when its own current prompt is visible and empty."""
        session = self.quiet_session(old_started)
        if not session:
            return None
        screen = self.cmux('read-screen', '--surface', self.surface, '--lines', '12')
        if input_ready(screen):
            return session
        return None

    def quiet_session(self, old_started):
        session = self.session()
        if not session or session.get('startedAt') == old_started:
            return None
        if session.get('status') != 'idle' and not self.limited():
            return None
        if background_work(session, process_children(self.runner), self.projects, self.clock(), self.runner):
            return None
        return session

    def cmux(self, *args):
        result = self.runner([self.cmux_path, *args], capture_output=True, text=True,
                             timeout=10, check=False)
        if result.returncode:
            if args[0] == 'read-screen':
                raise SessionUnavailable('Could not read the terminal screen')
            raise OSError(f'cmux {args[0]} failed: status={result.returncode}')
        return result.stdout
