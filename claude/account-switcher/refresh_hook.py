#!/usr/bin/env python3
"""Claude Code Stop/StopFailure hook: restart this session after an account switch, and continue
a turn that sleep or a lost connection cut.

The hook itself only checks and returns, so a turn never waits on it. When the session
stopped at a usage limit or started before the latest switch, it launches a detached helper
(`--helper`) that waits for the switch and does the restart through the session's own cmux
surface (see refresh.py). When an interruption cut the turn, a `--resume` helper types the
continue prompt once the Mac is awake. Set ACCOUNT_SWITCHER_STATE_DIR to use another state
directory (tests).
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from refresh import SelfRestart, SessionEnded, SessionUnavailable, hook_ancestors, switch_pending  # noqa: E402
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
        if not isinstance(session_id, str) or not session_id.replace('-', '').isalnum() or not surface:
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
        pending = restart.pending()
        # limited() first: needed() runs ps, which timed out when many sessions stopped at a
        # limit at once (2026-11-16 11:08).
        interrupted = False
        try:
            limited = restart.limited(retry_replacement=False)
            interrupted = not limited and restart.interrupted()
            switching = pending or switch_pending(restart.state, time.time())
            if not (limited or interrupted or switching):
                return 0
            restart.ancestors = hook_ancestors()
            needed = limited or bool(pending) or restart.needed()
        except SessionUnavailable:
            # The Stop hook must return while a temporarily missing transcript is republished.
            needed = True
        modes = [mode for mode, wanted in (('--resume', interrupted), ('--helper', needed))
                 if wanted]
        if not modes:
            return 0
        environment = os.environ.copy()
        environment.pop('CLAUDE_SWITCHER_REGISTRY_PID', None)
        environment.pop('CLAUDE_SWITCHER_TRANSCRIPT', None)
        chain = restart.ancestors if isinstance(restart.ancestors, (list, tuple)) else hook_ancestors()
        environment['CLAUDE_SWITCHER_ANCESTORS'] = ','.join(str(pid) for pid in chain)
        if hint:
            environment['CLAUDE_SWITCHER_TRANSCRIPT'] = str(hint)
        if isinstance(restart.last_session, dict):
            environment['CLAUDE_SWITCHER_REGISTRY_PID'] = str(restart.last_session['pid'])
        for mode in modes:
            subprocess.Popen([sys.executable, __file__, mode, session_id, surface],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True, env=environment)
    except (SessionEnded, SwitcherError, OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def helper(session_id, surface, mode='--helper'):
    state = State(state_dir())
    restart = SelfRestart(state, Path.home() / '.claude', session_id, surface)
    resume = mode == '--resume'
    # A resume helper waits for the one before it: that one may have just typed the prompt whose
    # turn failed again and started this helper.
    lock = ('restart-resume-' if resume else 'restart-') + restart.receipt.removeprefix('handoff-')
    try:
        with state.lock(lock, blocking=resume):
            chain = os.environ.get('CLAUDE_SWITCHER_ANCESTORS')
            if chain is not None:
                restart.ancestors = [int(pid) for pid in chain.split(',') if pid.isdecimal()]
            restart.transcript = transcript_hint(session_id, os.environ.get('CLAUDE_SWITCHER_TRANSCRIPT'))
            pid = os.environ.get('CLAUDE_SWITCHER_REGISTRY_PID', '')
            if pid.isdecimal():
                restart.registry_hint = {'pid': int(pid)}
            outcome = restart.resume() if resume else restart.run()
    except LockBusy:
        return 0  # Another helper already handles this session.
    except (SwitcherError, OSError, ValueError, subprocess.SubprocessError) as exc:
        outcome = f'error:{type(exc).__name__}'
    with (state.root / LOG).open('a') as stream:
        stream.write(json.dumps({'at': time.time(), 'session': session_id[:8],
                                 'outcome': outcome}) + '\n')
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] in ('--helper', '--resume'):
        sys.exit(helper(sys.argv[2], sys.argv[3], sys.argv[1]))
    sys.exit(hook())
