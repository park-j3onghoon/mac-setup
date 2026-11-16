"""Restart a live Claude Code session after an account switch so it uses the new login.

Claude Code 2.1.323 keeps the access token it holds until the token expires, a request gets
401, or a usage-limit error occurs (2026-11-13: sessions still used the old account seven
minutes after a switch). The switcher service records each switch time (record_switch).
cmux lets only processes started inside cmux type into its tabs ("socketControlMode":
"cmuxOnly"), so the restart runs from each session's own Stop/StopFailure hook
(refresh_hook.py), which runs inside cmux; a detached helper keeps that access.

When a session that started before the latest switch ends a turn, the hook starts a helper
(SelfRestart) that waits until the session is idle, its input box is empty and no
background work runs, then types the built-in `/restart`. `/restart` re-executes in the
same pid and resumes the same session id with a new registry startedAt (measured
2026-11-13). After a turn that ended with a usage-limit error, the helper types
CONTINUE_PROMPT once the session is back.

Background work means a child shell (Bash or Monitor tasks) under the session's process, or
a subagent transcript written in the last SUBAGENT_QUIET_SECONDS. The footer's "← N agents"
is the agent-view hint, also shown by a fresh session, and Claude Code's own
`caffeinate -i -t 300` outlives a turn by up to five minutes, so neither is used.
"""

import json
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
READY_TIMEOUT_SECONDS = 600
RESTART_TIMEOUT_SECONDS = 120
WAIT_STEP_SECONDS = 3
SUBAGENT_QUIET_SECONDS = 120
WORKING_CHILDREN = frozenset({'zsh', 'bash', 'sh'})
LIMIT_ERROR = re.compile(r'hit your .*limit|usage limit reached', re.I)
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


def is_command_echo(entry):
    content = (entry.get('message') or {}).get('content')
    text = content if isinstance(content, str) else ''
    return entry.get('isMeta') or text.lstrip().startswith(('<command-', '<local-command'))


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
        if entry.get('type') == 'user' and not is_command_echo(entry):
            return False
        if entry.get('type') == 'assistant':
            content = (entry.get('message') or {}).get('content') or []
            text = ''.join(c.get('text', '') for c in content if isinstance(c, dict))
            return bool(entry.get('isApiErrorMessage')) and bool(LIMIT_ERROR.search(text))
    return False


def live_sessions(config_home, runner=subprocess.run):
    """Interactive sessions whose registered pid still belongs to the same process."""
    registered = {}
    for path in (Path(config_home) / 'sessions').glob('*.json'):
        try:
            entry = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(entry.get('pid'), int) and entry.get('kind') == 'interactive':
            registered[entry['pid']] = entry
    if not registered:
        return []
    result = runner(['/bin/ps', '-o', 'pid=,tty=,lstart=', '-p', ','.join(map(str, registered))],
                    capture_output=True, text=True, timeout=5, check=False,
                    env={'LC_ALL': 'C', 'TZ': 'UTC'})
    sessions = []
    for line in result.stdout.splitlines():
        pid, tty, started = (line.split(None, 2) + ['', '', ''])[:3]
        entry = registered.get(int(pid)) if pid.isdigit() else None
        if entry and entry.get('procStart') == started.strip():
            sessions.append(dict(entry, tty=tty))
    return sessions


def process_children(runner):
    result = runner(['/bin/ps', '-ax', '-o', 'pid=,ppid=,comm='], capture_output=True,
                    text=True, timeout=5, check=False)
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


class SelfRestart:
    """Restart one session through its own cmux surface after an account switch."""

    def __init__(self, state, config_home, session_id, surface, runner=subprocess.run,
                 sleep=time.sleep, clock=time.time, cmux=None):
        self.state, self.config_home = state, Path(config_home)
        self.session_id, self.surface = session_id, surface
        self.runner, self.sleep, self.clock = runner, sleep, clock
        self.cmux_path = cmux or find_cmux()
        self.projects = self.config_home / 'projects'

    def session(self):
        return next((s for s in live_sessions(self.config_home, self.runner)
                     if s['sessionId'] == self.session_id), None)

    def needed(self):
        """True when the latest switch happened after this session's process started."""
        since = switch_pending(self.state, self.clock())
        session = self.session() if since else None
        return bool(session and session.get('startedAt', 0) / 1000 < since)

    def run(self):
        """Wait for a quiet moment, restart, and continue after a limit stop."""
        session = self.wait_until_ready(None, READY_TIMEOUT_SECONDS)
        if session is None:
            return 'not_ready'
        limited = ended_with_limit_error(self.projects, self.session_id)
        self.type('/restart')
        if self.wait_until_ready(session.get('startedAt'), RESTART_TIMEOUT_SECONDS) is None:
            return 'restart_unconfirmed'
        if not limited:
            return 'restarted'
        self.type(CONTINUE_PROMPT)
        return 'restarted_and_continued'

    def wait_until_ready(self, old_started, timeout):
        deadline = self.clock() + timeout
        while True:
            session = self.session()
            if session and session.get('startedAt') != old_started and self.ready(session):
                return session
            if self.clock() >= deadline:
                return None
            self.sleep(WAIT_STEP_SECONDS)

    def ready(self, session):
        limited = ended_with_limit_error(self.projects, self.session_id)
        if session.get('status') != 'idle' and not limited:
            return False
        if background_work(session, process_children(self.runner), self.projects, self.clock()):
            return False
        return input_ready(self.cmux('read-screen', '--surface', self.surface, '--lines', '12'))

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
