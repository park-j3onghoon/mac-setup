"""Restart a live Claude Code session after an account switch so it uses the new login.

Claude Code 2.1.323 keeps the access token it holds until the token expires, a request gets
401, or a usage-limit error occurs (2026-11-13: sessions still used the old account seven
minutes after a switch). The switcher service records each switch time (record_switch).
cmux lets only processes started inside cmux type into its tabs ("socketControlMode":
"cmuxOnly"), so the restart runs from each session's own Stop/StopFailure hook
(refresh_hook.py), which runs inside cmux; a detached helper keeps that access.

When a session that started before the latest switch, or that stopped at a usage limit, ends
a turn, the hook starts a helper (SelfRestart). The helper first waits for a switch newer than
the session (a limit can come before the service notices and switches), then until the
session is idle, its input box is empty and no background work runs, and types the built-in
`/restart`. `/restart` re-executes in the same pid and resumes the same session id with a new
registry startedAt (measured 2026-11-13). After a turn that ended with a usage-limit error,
the helper types CONTINUE_PROMPT once the session is back.

Background work means a child shell (Bash or Monitor tasks) under the session's process, or
a subagent transcript written in the last SUBAGENT_QUIET_SECONDS. The footer's "← N agents"
is the agent-view hint, also shown by a fresh session, and Claude Code's own
`caffeinate -i -t 300` outlives a turn by up to five minutes, so neither is used.
"""

import json
import os
from pathlib import Path
import re
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
RESTART_TIMEOUT_SECONDS = 120
WAIT_STEP_SECONDS = 3
# A session stopped at a limit ends no later turn to retry from (Claude Code waits for the reset
# itself), so past READY_TIMEOUT_SECONDS its helper waits out background work, such as a
# 14-minute timer on 2026-11-16 15:06~15:13, for the restart window, checking less often.
LIMIT_WAIT_STEP_SECONDS = 30
SUBAGENT_QUIET_SECONDS = 120
WORKING_CHILDREN = frozenset({'zsh', 'bash', 'sh'})
LIMIT_ERROR = re.compile(r'hit your .*limit|usage limit reached', re.I)
# User entries Claude Code writes itself. Background task notifications keep arriving after a
# limit stop (2026-11-16 11:08~11:09), so they do not mean the user asked to go on.
GENERATED_PREFIXES = ('<command-', '<local-command', '<task-notification>')
# Claude Code 2.1.325 titles its usage-limit and billing choices this way. They covered the input
# box of a session restarted while still limited (2026-11-16 11:35); Esc cancels them, the same
# as "Stop and wait for limit to reset".
LIMIT_CHOICES_TITLE = 'What do you want to do?'
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
    return is_rule(lines[i - 1]) and is_rule(lines[i + 1])


def is_generated(entry):
    content = (entry.get('message') or {}).get('content')
    text = content if isinstance(content, str) else ''
    return entry.get('isMeta') or text.lstrip().startswith(GENERATED_PREFIXES)


def latest_message(projects_dir, session_id):
    """Newest real conversation entry; skip local commands and task notifications."""
    paths = sorted(Path(projects_dir).glob(f'*/{session_id}.jsonl'),
                   key=lambda path: path.stat().st_mtime)
    return last_entry(paths[-1]) if paths else None


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


def ended_with_limit_error(projects_dir, session_id, transcript=None):
    entry = last_entry(transcript) if transcript is not None else latest_message(projects_dir, session_id)
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


def live_session(config_home, session_id, runner=subprocess.run, prior=None):
    """This interactive session's registry entry while its pid still belongs to the same process.

    `ps -p` gets one pid: with all 15 registered pids it took 0.16 s of system time, with one
    under 0.01 s (2026-11-16)."""
    unreadable = False
    registry = Path(config_home) / 'sessions'
    paths = (registry / f"{prior['pid']}.json",) if prior else registry.glob('*.json')
    for path in paths:
        try:
            entry = json.loads(path.read_text())
        except FileNotFoundError:
            continue
        except (OSError, ValueError):
            unreadable |= prior is not None
            continue
        if (entry.get('sessionId') != session_id or entry.get('kind') != 'interactive'
                or not isinstance(entry.get('pid'), int)):
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
            return entry
    if unreadable:
        raise SessionUnavailable("Session registry temporarily unreadable")
    return None


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


def background_work(session, children, projects_dir, now, runner=subprocess.run, *, check_completion=False):
    """True while a shell or a subagent of this session is still working."""
    candidates, stack = [], [session['pid']]
    while stack:
        for child, name in children.get(stack.pop(), []):
            if name in WORKING_CHILDREN:
                return True
            if name != 'caffeinate':
                candidates.append(str(child))
            stack.append(child)
    if candidates:
        # A shell can exec the foreground task. A long-lived MCP process normally has pipes.
        descriptors = runner(['/usr/sbin/lsof', '-nP', '-a', '-p', ','.join(candidates),
                              '-d', '1,2', '-Fftn'], capture_output=True, text=True,
                             timeout=5, check=False)
        if descriptors.returncode not in (0, 1) or (descriptors.returncode and descriptors.stderr):
            raise SessionUnavailable('Could not check session task output')
        regular = False
        for field in descriptors.stdout.splitlines():
            if field.startswith(('f', 'p')):
                regular = False
            elif field.startswith('t'):
                regular = field == 'tREG'
            elif regular and field.startswith('n'):
                path = Path(field[1:])
                if (path.parent.name == 'tasks' and path.parent.parent.name == session['sessionId']
                        and path.suffix == '.output'):
                    return True
    pattern = f"*/{session['sessionId']}/subagents/*.jsonl"
    unfinished = set()
    transcripts = set()
    for path in Path(projects_dir).glob(pattern):
        if not check_completion:
            if now - path.stat().st_mtime < SUBAGENT_QUIET_SECONDS:
                return True
        elif not completed(last_entry(path)):
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
            if not isinstance(entry, dict) or entry.get('type') != 'user':
                continue
            content = (entry.get('message') or {}).get('content')
            if isinstance(content, str) and content.lstrip().startswith('<task-notification>'):
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
    """Restart one session through its own cmux surface after an account switch."""

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
        self.watch_exit = True

    def session(self):
        session = live_session(self.config_home, self.session_id, self.runner,
                               self.last_session or self.registry_hint)
        if session:
            self.last_session = session
        elif self.watch_exit:
            if self.last_session is None:
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

    def limited(self):
        if self.transcript is not None and not self.transcript.is_file():
            self.transcript = None
        return ended_with_limit_error(self.projects, self.session_id, self.transcript)

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
        limited = self.limited()
        # 직접 요청한 재시작 중에는 registry와 프로세스가 잠시 사라질 수 있다.
        def still_needs_restart():
            current = self.quiet_session(None)
            since = switch_pending(self.state, self.clock())
            return (current and since and current['startedAt'] == session['startedAt']
                    and current['startedAt'] / 1000 < since)

        if not self.type('/restart', only_if=still_needs_restart):
            return 'not_ready'
        self.watch_exit = False
        if self.wait(lambda: self.ready(session.get('startedAt')), RESTART_TIMEOUT_SECONDS) is None:
            return 'restart_unconfirmed'
        if not limited or not self.limited():
            return 'restarted'
        if not self.type(CONTINUE_PROMPT, only_if=self.limited):
            return 'restarted_continuation_deferred'
        return 'restarted_and_continued'

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
        """This session once it is quiet with an empty input box, else None; usage-limit choices
        covering the box are closed for the next check. While the registry still shows
        old_started (its startedAt before `/restart`), the session has not come back yet."""
        session = self.quiet_session(old_started)
        if not session:
            return None
        screen = self.cmux('read-screen', '--surface', self.surface, '--lines', '12')
        if input_ready(screen):
            return session
        if LIMIT_CHOICES_TITLE in screen and 'Stop and wait for limit to reset' in screen:
            self.cmux('send-key', '--surface', self.surface, 'escape')
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

    def type(self, text, only_if=None):
        def inspect_input():
            if only_if and not only_if():
                return 'occupied'
            screen = self.cmux('read-screen', '--surface', self.surface, '--lines', '12')
            return 'empty' if input_ready(screen) else 'occupied'

        if self.wait(inspect_input, 10) != 'empty':
            return False
        # cmux 0.64.22 dispatches paste and submit together on its main actor. It does not
        # provide an atomic empty-input precondition, so the final screen check is still needed.
        response = json.loads(self.cmux('rpc', 'terminal.paste', json.dumps({
            'surface_id': self.surface, 'text': text, 'submit_key': 'enter',
        })))
        if response.get('submitted') is not True:
            raise OSError('cmux accepted the paste without confirming submission')
        return True
