"""Restart existing, unmanaged Claude sessions after an account change on their own cmux surface,
and continue turns that sleep or a lost connection cut.

The helper types `/restart` only into an empty input box and leaves a draft alone: the turn the
user ends by sending it runs the hook again. Keep the receipt until Claude publishes its new
startedAt, then continue if the original limit stop is still the last real conversation event.
A turn an interruption cut gets RESUME_PROMPT once the Mac is fully awake; the tries are counted
from the transcript itself, so a turn that ends normally starts the count again.
"""

import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

from macos import system_awake

CMUX_PATHS = ('/opt/homebrew/bin/cmux', '/Applications/cmux.app/Contents/Resources/bin/cmux')
# What to check before going on, after a restart or an interruption.
CONTINUE_STEPS = (
    '먼저 마지막 요청, 실행 중인 프로세스와 남은 결과를 '
    '확인해줘. 완료된 작업은 반복하지 말고, 아직 실행 중이면 그 결과를 기다려줘. 중단되거나 실패한 '
    '작업은 이어갈 수 있는 지점부터 계속하고, 이어갈 수 없으면 그 작업만 처음부터 다시 실행해줘. '
    '이미 반영됐을 수 있는 작업은 실제 반영 여부부터 확인하고, 사용자 승인이나 답변이 필요하면 다시 물어봐. '
    '직전 프롬프트가 부족하거나 이상하면 질문하고 이어서 해.'
)
CONTINUE_PROMPT = '계정 전환 전에 하던 작업을 이어서 해줘. ' + CONTINUE_STEPS
RESUME_PROMPT = '잠자기나 연결 끊김으로 응답이 중간에 끊겼어. 하던 작업을 이어서 해줘. ' + CONTINUE_STEPS
# API errors that cut a turn without anyone deciding to stop (transcripts of 2026-11-10~24:
# computer_slept 10, no_response 4, connection_failed 3, stream_idle_timeout 2). A usage limit
# waits for the account switch and model_requires_usage_credits needs the user.
INTERRUPTIONS = frozenset({'computer_slept', 'connection_failed', 'no_response',
                           'stream_idle_timeout'})
# The user's rule (2026-11-24): 30 seconds after an error, at most 3 tries at one stuck point and
# 10 in all until a turn ends normally.
RESUME_GAP_SECONDS = 30
RESUME_ATTEMPTS = 3
RESUME_TOTAL = 10
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
WORKING_CHILDREN = frozenset({'zsh', 'bash', 'sh'})
MCP_NAME = re.compile(r'(?:^|[/@._-])mcp(?:$|[/._-])', re.I)
LIMIT_ERROR = re.compile(r'hit your .*limit|usage limit reached', re.I)
# User entries Claude Code writes itself. Background task notifications keep arriving after a
# limit stop (2026-11-16 11:08~11:09), so they do not mean the user asked to go on.
GENERATED_PREFIXES = ('<command-', '<local-command', '<task-notification>')
# Dimmed hints Claude Code 2.1.331 puts in an empty prompt after an API error (`Tlo`); read-screen
# returns them as plain text (2026-11-24: 「❯ Resend your message to try again」 after
# connection_failed, the hint for every error in INTERRUPTIONS).
PROMPT_HINTS = ('Resend your message to try again', 'Once fixed, resend your message',
                'Run /rewind to go back')
RULE_MIN_DASHES = 10


def find_cmux():
    return next((path for path in CMUX_PATHS if Path(path).is_file()), None)


def record_switch(state, switched_at):
    state.save(STATE, {'since': switched_at})


def last_switch(state):
    since = state.load(STATE).get('since')
    return since if isinstance(since, (int, float)) else None


def switch_pending(state, now):
    """The latest switch time while sessions may still need a restart, else None."""
    since = last_switch(state)
    return since if since is not None and 0 <= now - since <= REFRESH_WINDOW_SECONDS else None


def is_rule(line):
    """A border of the input box. A named session shows its name inside the top border
    (`──── my-session repo 947 ─`, 2026-11-13)."""
    text = line.strip()
    return text.startswith('─') and text.endswith('─') and text.count('─') >= RULE_MIN_DASHES


def input_ready(screen):
    """True when Claude's input box (❯ between two rules) is empty or shows only a hint."""
    lines = screen.splitlines()
    prompts = [i for i, line in enumerate(lines) if line.strip().startswith('❯')]
    if not prompts:
        return False
    i = prompts[-1]
    typed = lines[i].strip().removeprefix('❯').strip()
    if typed and typed not in PROMPT_HINTS or not 0 < i < len(lines) - 1:
        return False
    if not (is_rule(lines[i - 1]) and is_rule(lines[i + 1])):
        return False
    footer = [line.strip() for line in lines[i + 2:] if line.strip()]
    # The current input box ends the screen with its mode line, below notices such as a usage-limit
    # wait in varying words (2026-11-23) and the workspace name. A dialog below the mode line means
    # the input border belongs to an older screen.
    return not footer or bool(re.fullmatch(
        r'(?:⏵⏵ |⏸ )?(?:auto mode on|accept edits on|plan mode on|bypass permissions on)'
        r'(?: \(shift\+tab to cycle\))?(?: · ← \d+ agents?)?', footer[-1], re.I))


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
        if (entry.get('type') == 'assistant' or entry.get('type') == 'user' and not is_generated(entry)
                or limit_notice(entry)):
            return entry
    return None


def limit_notice(entry):
    """Claude Code 2.1.330 records a limit stop after a wrap-up answer only as a system note
    (2026-11-23: 「Usage limit reached · continuing automatically at 3pm · esc to cancel」)."""
    content = entry.get('content')
    return (entry.get('type') == 'system' and entry.get('subtype') == 'informational'
            and isinstance(content, str) and bool(LIMIT_ERROR.search(content)))


def completed(entry):
    return bool(entry and entry['type'] == 'assistant' and not entry.get('isApiErrorMessage')
                and (entry.get('message') or {}).get('stop_reason') in ('end_turn', 'stop_sequence'))


def last_message(projects_dir, session_id, transcript=None):
    if transcript is not None:
        return last_entry(transcript)
    return latest_message(projects_dir, session_id)


def ended_with_limit_error(projects_dir, session_id, transcript=None):
    return is_limit_error(last_message(projects_dir, session_id, transcript))


def is_interruption(entry):
    """Sleep or a lost connection cut the turn (Claude Code 2.1.330 `apiError`, 2026-11-23)."""
    return bool(entry and entry['type'] == 'assistant' and entry.get('isApiErrorMessage')
                and entry.get('apiError') in INTERRUPTIONS)


def prompt_counts(path, prompt):
    """How often `prompt` was typed since the model last answered, and since a turn last ended
    normally."""
    attempts = total = 0
    answered = False
    for line in transcript_lines(path):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict) or 'type' not in entry:
            continue
        if completed(entry):
            break
        if entry['type'] == 'assistant' and not entry.get('isApiErrorMessage'):
            answered = True
        elif entry['type'] == 'user' and notification_text(entry).strip() == prompt:
            total += 1
            attempts += not answered
    return attempts, total


def is_limit_error(entry):
    if not entry:
        return False
    if limit_notice(entry):
        return True
    if entry['type'] != 'assistant' or not entry.get('isApiErrorMessage'):
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
    """Treat task shells, children without stdio streams on fds 0 and 1, and running subagents as
    active work."""
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
        # A task, also one a shell execs, keeps /dev/null or its task output file on fd 0 or 1
        # (2026-11-23: Bash and Monitor tasks).
        descriptors = runner(['/usr/sbin/lsof', '-nP', '-a', '-p', ','.join(servers), '-d', '0,1', '-Fft'],
                             capture_output=True, text=True, timeout=5, check=False)
        if descriptors.returncode not in (0, 1) or (descriptors.returncode and descriptors.stderr):
            raise SessionUnavailable('Could not check session task output')
        streams = set()
        pid = fd = None
        for field in descriptors.stdout.splitlines():
            if field.startswith('p'):
                pid = field[1:]
            elif field.startswith('f'):
                fd = field[1:]
            elif field in ('tPIPE', 'tFIFO', 'tunix'):
                streams.add((pid, fd))
        if any((pid, fd) not in streams for pid in servers for fd in ('0', '1')):
            return True
    # Agents run inside the Claude process, so one last written before this process started died
    # with an earlier process (2026-11-23: 22c0f27e kept agents killed on 11-13).
    started = session.get('startedAt', 0) / 1000
    return any(path.stat().st_mtime >= started and not finished_agent(path)
               for path in Path(projects_dir).glob(f"*/{session['sessionId']}/subagents/*.jsonl"))


def finished_agent(path):
    """Claude Code marks an agent that ended, failed or was stopped `finished` in its meta file and
    drops the mark when SendMessage resumes it (2026-11-23: 1,016 of 1,036 agents of two weeks; the
    other 20 were 7 resumed after a completion notice and 13 cut off with their process)."""
    try:
        return json.loads(path.with_suffix('.meta.json').read_text()).get('finished') is True
    except (FileNotFoundError, ValueError):
        return False


class SessionUnavailable(OSError):
    pass


class SessionEnded(Exception):
    pass


class WindowPassed(Exception):
    """REFRESH_WINDOW_SECONDS passed since the switch: the session's own token has expired."""


class SelfRestart:
    """Restart one terminal's session after an account switch and continue a limit stop."""

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

    def interrupted(self):
        return is_interruption(last_message(self.projects, self.session_id, self.transcript))

    def pending(self):
        receipt = self.state.load(self.receipt)
        since = receipt.get('since')
        return receipt if (receipt.get('phase') == 'waiting' and type(since) in (int, float)
                           and 0 <= self.clock() - since <= REFRESH_WINDOW_SECONDS) else {}

    def needed(self):
        """True when the latest switch happened after this session's process started."""
        return self.predates(switch_pending(self.state, self.clock()))

    def predates(self, since):
        session = self.session() if since else None
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
        if (was_limited and switch_pending(self.state, self.clock()) is None
                and self.predates(last_switch(self.state))):
            return self.continue_after_window()

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
        pending = {key: self.last_session[key] for key in ('pid', 'procStart', 'startedAt')}
        pending.update(phase='waiting', since=since)
        self.state.save(self.receipt, pending)
        return self.confirm(pending)

    def confirm(self, pending):
        """Type `/restart` once the session is quiet with an empty input box, then continue a
        limit stop in the restarted session."""
        self.last_session = {key: pending[key] for key in ('pid', 'procStart', 'startedAt')}

        def restarted():
            current = self.session()
            return (current and current['startedAt'] > pending['startedAt']
                    and current['startedAt'] >= pending['since'] * 1000)

        if not restarted():
            if not self.ready_before(pending['since']):
                # 2026-11-25 02:46: subagents kept the session busy until the window passed in
                # a lid-closed wake, and the session stayed stopped at its limit until the user
                # came back.
                return self.continue_after_window() if self.limited() else 'not_ready'
            # The user may restart meanwhile or start a draft after the last look.
            typed = self.type('/restart', only_if=lambda: not restarted())
            if not self.wait(restarted, RESTART_TIMEOUT_SECONDS if typed else 0):
                return 'restart_unconfirmed' if typed else 'not_ready'
        if not self.limited():
            outcome = 'restarted'
        elif (self.wait(self.ready, RESTART_TIMEOUT_SECONDS)
              and self.type(CONTINUE_PROMPT, only_if=self.limited)):
            outcome = 'restarted_and_continued'
        else:
            outcome = 'restarted_continuation_deferred'
        self.state.save(self.receipt, {'phase': outcome, 'since': pending['since']})
        return outcome

    def resume(self):
        """Type RESUME_PROMPT into the empty input box of a turn an interruption cut,
        RESUME_GAP_SECONDS after the failure and once the Mac is fully awake (a lid-closed
        maintenance wake wrote the 2026-11-23 19:25 sleep error two seconds before sleeping again)."""
        try:
            return self._resume()
        except SessionEnded:
            return 'session_ended'

    def _resume(self):
        # The hook starts this helper as the turn fails, before Claude Code writes the error
        # entry (2026-11-24 11:17: the transcript still ended with the prompt), so look later.
        self.sleep(RESUME_GAP_SECONDS)

        def due():
            path = self.transcript_path()
            try:
                entry, (attempts, total) = last_entry(path), prompt_counts(path, RESUME_PROMPT)
            except FileNotFoundError:
                self.transcript = None
                raise SessionUnavailable('Session transcript is being replaced') from None
            if not is_interruption(entry):
                return 'resume_superseded'
            if attempts >= RESUME_ATTEMPTS or total >= RESUME_TOTAL:
                return 'resume_gave_up'
            return entry if system_awake(self.runner) and self.answerable() else None

        # Waiting time counts only while the Mac is awake: time.monotonic stops in sleep
        # (2026-11-24: 95 hours behind the wall clock since the 11-18 boot).
        result = self.wait(due, REFRESH_WINDOW_SECONDS)
        if result is None:
            return 'resume_not_ready'
        if isinstance(result, str):
            return result

        def still_cut():
            # The user may continue meanwhile or start a draft after the last look.
            return last_message(self.projects, self.session_id, self.transcript_path()) == result

        return 'resumed' if self.type(RESUME_PROMPT, only_if=still_cut) else 'resume_not_ready'

    def transcript_path(self):
        """The hook's transcript, else the newest one of this session."""
        if self.transcript is not None and self.transcript.is_file():
            return self.transcript
        try:
            self.transcript = max(self.projects.glob(f'*/{self.session_id}.jsonl'),
                                  key=lambda path: path.stat().st_mtime_ns)
        except (ValueError, FileNotFoundError):  # none yet, or one vanished while comparing
            raise SessionUnavailable('Session transcript is being replaced') from None
        return self.transcript

    def answerable(self):
        """The session not answering, with an empty prompt; a dialog such as a permission prompt
        replaces the prompt. Unlike `/restart`, a prompt does not stop background tasks."""
        session = self.session()
        if not session or session.get('status') == 'busy':
            return None
        return session if self.input_empty() else None

    def ready_before(self, since):
        """The quiet session with an empty input box while the switch is pending, else None."""
        def ready_while_pending():
            if switch_pending(self.state, self.clock()) is None:
                raise WindowPassed
            return self.ready()
        expires = since + REFRESH_WINDOW_SECONDS
        try:
            session = self.wait(ready_while_pending,
                                min(READY_TIMEOUT_SECONDS, max(0, expires - self.clock())))
            if session is None and self.limited():
                session = self.wait(ready_while_pending, max(0, expires - self.clock()),
                                    LIMIT_WAIT_STEP_SECONDS)
        except WindowPassed:
            return None
        return session

    def continue_after_window(self):
        """Continue a limit stop past the window without a restart: the session's own token
        has expired, and Claude Code 2.1.331 renews it from the credential store, taking the
        stored login when it differs from the one it held
        (`tengu_oauth_token_refresh_race_resolved`). Once per stop, so a stop on the live account
        too cannot loop through the hook."""
        if prompt_counts(self.transcript_path(), CONTINUE_PROMPT)[1]:
            return 'continuation_already_tried'
        if (self.wait(self.ready, REFRESH_WINDOW_SECONDS, LIMIT_WAIT_STEP_SECONDS)
                and self.type(CONTINUE_PROMPT, only_if=self.limited)):
            return 'continued_after_window'
        return 'continuation_deferred'

    def type(self, text, only_if=None):
        """Paste text with Enter in one cmux request when a last look finds the input box empty."""
        if only_if and not only_if():
            return False
        if not self.input_empty():
            return False
        # cmux 0.64.22 dispatches paste and submit together on its main actor. It has no
        # empty-input precondition, so only text typed after the last look can still mix in.
        response = json.loads(self.cmux('rpc', 'terminal.paste', json.dumps({
            'surface_id': self.surface, 'text': text, 'submit_key': 'enter'})))
        if response.get('submitted') is not True:
            raise OSError('cmux accepted the paste without confirming submission')
        return True

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

    def ready(self):
        """The quiet session when its own current prompt is visible and empty, else None."""
        session = self.quiet_session()
        return session if session and self.input_empty() else None

    def input_empty(self):
        return input_ready(self.cmux('read-screen', '--surface', self.surface, '--lines', '12'))

    def quiet_session(self):
        session = self.session()
        if not session:
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
