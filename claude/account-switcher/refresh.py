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
CONTINUE_PROMPT = '이어서 해줘'
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


def ended_with_limit_error(projects_dir, session_id):
    """True when the newest conversation entry is Claude's usage-limit error."""
    paths = sorted(Path(projects_dir).glob(f'*/{session_id}.jsonl'),
                   key=lambda path: path.stat().st_mtime)
    if not paths:
        return False
    with paths[-1].open('rb') as stream:
        stream.seek(0, 2)
        stream.seek(max(0, stream.tell() - TAIL_BYTES))
        tail = stream.read().decode('utf-8', 'replace')
    for line in reversed(tail.splitlines()):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get('type') == 'user' and not is_generated(entry):
            return False
        if entry.get('type') == 'assistant':
            content = (entry.get('message') or {}).get('content') or []
            text = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
            return bool(entry.get('isApiErrorMessage')) and bool(LIMIT_ERROR.search(text))
    return False


def live_session(config_home, session_id, runner=subprocess.run):
    """This interactive session's registry entry while its pid still belongs to the same process.

    `ps -p` gets one pid: with all 15 registered pids it took 0.16 s of system time, with one
    under 0.01 s (2026-11-16)."""
    for path in (Path(config_home) / 'sessions').glob('*.json'):
        try:
            entry = json.loads(path.read_text())
        except (OSError, ValueError):
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


def background_work(session, children, projects_dir, now):
    """True while a shell or a subagent of this session is still working."""
    names, stack = set(), [session['pid']]
    while stack:
        for child, name in children.get(stack.pop(), []):
            names.add(name.strip())
            stack.append(child)
    if WORKING_CHILDREN & names:
        return True
    pattern = f"*/{session['sessionId']}/subagents/*.jsonl"
    return any(now - path.stat().st_mtime < SUBAGENT_QUIET_SECONDS
               for path in Path(projects_dir).glob(pattern))


class SessionEnded(Exception):
    pass


class SelfRestart:
    """Restart one session through its own cmux surface after an account switch."""

    def __init__(self, state, config_home, session_id, surface, runner=subprocess.run,
                 sleep=time.sleep, clock=time.time, cmux=None):
        self.state, self.config_home = state, Path(config_home)
        self.session_id, self.surface = session_id, surface
        self.runner, self.sleep, self.clock = runner, sleep, clock
        self.cmux_path = cmux or find_cmux()
        self.projects = self.config_home / 'projects'
        self.last_session = None
        self.watch_exit = True

    def session(self):
        session = live_session(self.config_home, self.session_id, self.runner)
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
        return ended_with_limit_error(self.projects, self.session_id)

    def needed(self):
        """True when the latest switch happened after this session's process started."""
        since = switch_pending(self.state, self.clock())
        session = self.session()
        return bool(since and session and session.get('startedAt', 0) / 1000 < since)

    def run(self):
        """Wait for the switch and a quiet moment, restart, and continue after a limit stop."""
        try:
            return self._run()
        except SessionEnded:
            return 'session_ended'

    def _run(self):
        if not self.wait(self.needed, SWITCH_TIMEOUT_SECONDS):
            return 'no_switch'
        session = self.wait(lambda: self.ready(None), READY_TIMEOUT_SECONDS)
        if session is None and self.limited():
            session = self.wait(lambda: self.ready(None), REFRESH_WINDOW_SECONDS,
                                LIMIT_WAIT_STEP_SECONDS)
        if session is None:
            return 'not_ready'
        limited = self.limited()
        # 직접 요청한 재시작 중에는 registry와 프로세스가 잠시 사라질 수 있다.
        self.watch_exit = False
        self.type('/restart')
        if self.wait(lambda: self.ready(session.get('startedAt')), RESTART_TIMEOUT_SECONDS) is None:
            return 'restart_unconfirmed'
        if not limited:
            return 'restarted'
        self.type(CONTINUE_PROMPT)
        return 'restarted_and_continued'

    def wait(self, check, timeout, step=WAIT_STEP_SECONDS):
        """Check immediately, then back off to 30 seconds; every check reads fresh state."""
        deadline = self.clock() + timeout
        while True:
            try:
                result = check()
                if result:
                    return result
            except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
                # 2026-11-16 11:08: many sessions stopped at a limit at once and five helpers gave
                # up on one slow ps; a slow check only means "not ready yet".
                pass
            if self.clock() >= deadline:
                return None
            self.sleep(min(step, max(0, deadline - self.clock())))
            step = min(step * 2, LIMIT_WAIT_STEP_SECONDS)

    def ready(self, old_started):
        """This session once it is quiet with an empty input box, else None; usage-limit choices
        covering the box are closed for the next check. While the registry still shows
        old_started (its startedAt before `/restart`), the session has not come back yet."""
        session = self.session()
        if not session or session.get('startedAt') == old_started:
            return None
        if session.get('status') != 'idle' and not self.limited():
            return None
        if background_work(session, process_children(self.runner), self.projects, self.clock()):
            return None
        screen = self.cmux('read-screen', '--surface', self.surface, '--lines', '12')
        if input_ready(screen):
            return session
        if LIMIT_CHOICES_TITLE in screen:
            self.cmux('send-key', '--surface', self.surface, 'escape')
        return None

    def cmux(self, *args):
        result = self.runner([self.cmux_path, *args], capture_output=True, text=True,
                             timeout=10, check=False)
        if result.returncode:
            raise OSError(f'cmux {args[0]} failed: status={result.returncode}')
        return result.stdout

    def type(self, text):
        self.cmux('send', '--surface', self.surface, '--', text)
        self.sleep(0.5)
        self.cmux('send-key', '--surface', self.surface, 'enter')
