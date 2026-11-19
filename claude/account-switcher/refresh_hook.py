#!/usr/bin/env python3
"""Claude Code Stop/StopFailure hook: restart this session after an account switch.

The hook itself only checks and returns, so a turn never waits on it. When the session
stopped at a usage limit or started before the latest switch, it launches a detached helper
(`--helper`) that waits for the switch and does the restart through the session's own cmux
surface (see refresh.py). Set ACCOUNT_SWITCHER_STATE_DIR to use another state directory (tests).
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from refresh import SelfRestart, SessionEnded, SessionUnavailable  # noqa: E402
from storage import LockBusy, State, SwitcherError, read_json  # noqa: E402

DEFAULT_STATE = HERE.parents[1] / 'private/claude/account-switcher'
LOG = 'session-restarts.log'


def state_dir():
    return Path(os.environ.get('ACCOUNT_SWITCHER_STATE_DIR') or DEFAULT_STATE)


def transcript_hint(session_id, value):
    if isinstance(value, str):
        path = Path(value).resolve()
        if path.name == f'{session_id}.jsonl' and path.is_relative_to(Path.home() / '.claude/projects'):
            return path
    return None


def hook():
    """Never fail or block a turn: any problem just skips the restart."""
    try:
        payload = json.load(sys.stdin)
        session_id, surface = payload.get('session_id'), os.environ.get('CMUX_SURFACE_ID')
        if not session_id or not surface:
            return 0
        if session_id == os.environ.get('MAC_SETUP_MANAGED_CLAUDE_SESSION_ID'):
            return 0
        managed_pid = os.environ.get('MAC_SETUP_MANAGED_CLAUDE_PID', '')
        if managed_pid.isdecimal():
            try:
                managed = read_json(Path.home() / '.claude/sessions' / f'{managed_pid}.json')
            except (FileNotFoundError, ValueError):
                managed = {}
            if managed.get('sessionId') == session_id:
                return 0
        restart = SelfRestart(State(state_dir()), Path.home() / '.claude', session_id, surface)
        hint = transcript_hint(session_id, payload.get('transcript_path'))
        restart.transcript = hint
        # limited() first: needed() runs ps, which timed out when many sessions stopped at a
        # limit at once (2026-11-16 11:08).
        try:
            needed = restart.limited(retry_replacement=False) or restart.needed()
        except SessionUnavailable:
            # The Stop hook must return while a temporarily missing transcript is republished.
            needed = True
        if needed:
            environment = os.environ.copy()
            if hint:
                environment['CLAUDE_SWITCHER_TRANSCRIPT'] = str(hint)
            if isinstance(restart.last_session, dict):
                environment['CLAUDE_SWITCHER_REGISTRY_PID'] = str(restart.last_session['pid'])
            subprocess.Popen([sys.executable, __file__, '--helper', session_id, surface],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, env=environment)
    except (SessionEnded, SwitcherError, OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def helper(session_id, surface):
    state = State(state_dir())
    lock = f'restart-{session_id}'
    try:
        with state.lock(lock):
            restart = SelfRestart(state, Path.home() / '.claude', session_id, surface)
            restart.transcript = transcript_hint(session_id, os.environ.get('CLAUDE_SWITCHER_TRANSCRIPT'))
            pid = os.environ.get('CLAUDE_SWITCHER_REGISTRY_PID', '')
            if pid.isdecimal():
                restart.registry_hint = {'pid': int(pid)}
            outcome = restart.run()
    except LockBusy:
        return 0  # Another helper already handles this session.
    except (SwitcherError, OSError, ValueError, subprocess.SubprocessError) as exc:
        outcome = f'error:{type(exc).__name__}'
    with (state.root / LOG).open('a') as stream:
        stream.write(json.dumps({'at': time.time(), 'session': session_id[:8],
                                 'outcome': outcome}) + '\n')
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] == '--helper':
        sys.exit(helper(sys.argv[2], sys.argv[3]))
    sys.exit(hook())
