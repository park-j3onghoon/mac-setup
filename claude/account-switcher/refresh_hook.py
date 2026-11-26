#!/usr/bin/env python3
"""Claude Code Stop/StopFailure hook: restart this session after an account switch, and continue
a turn that sleep or a lost connection cut.

The hook itself only checks and returns, so a turn never waits on it. When the session
stopped at a usage limit or started before the latest switch, it launches a detached helper
(`--helper`) that waits for the switch and does the restart through the session's own terminal
pane (see refresh.py). When an interruption cut the turn, a `--resume` helper types the
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

from refresh import (DEFAULT_TERMINAL, LIMIT_ERROR, SelfRestart, SessionEnded,  # noqa: E402
                     SessionUnavailable,
                     hook_ancestors, receipt_name, stuck_sessions, switch_pending)
from storage import LockBusy, State, SwitcherError, read_json  # noqa: E402
from switchcore.choices import pick  # noqa: E402

DEFAULT_STATE = HERE.parents[1] / 'private/claude/account-switcher'
LOG = 'session-restarts.log'
# Only a process started inside cmux may read or type into a surface ("Access denied - only
# processes started inside cmux can connect", 2026-11-25), so sessions' own hooks start the sweep.
SWEEP_SECONDS = 60


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
        state = State(state_dir())
        try:
            terminal_name, terminal = configured_terminal(state)
        except ValueError:
            record_outcome(state, payload.get('session_id'), 'config_error:terminal')
            return 0
        session_id, pane = payload.get('session_id'), terminal.pane_in(os.environ)
        if not isinstance(session_id, str) or not session_id.replace('-', '').isalnum() or not pane:
            return 0
        sweep_if_due(state)
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
        restart = SelfRestart(state, Path.home() / '.claude', session_id, pane, terminal)
        hint = transcript_hint(session_id, payload.get('transcript_path'))
        restart.transcript = hint
        pending = restart.pending()
        # limited() first: needed() runs ps, which timed out when many sessions stopped at a
        # limit at once (2026-11-16 11:08).
        # StopFailure runs before Claude Code writes the error entry (2026-11-24 11:17: the
        # transcript still ended with the prompt). Its own error text tells a limit stop, and any
        # other failure starts the resume helper, which reads the transcript later.
        failed = payload.get('hook_event_name') == 'StopFailure'
        error = payload.get('last_assistant_message') if failed else None
        interrupted = False
        try:
            limited = (isinstance(error, str) and bool(LIMIT_ERROR.search(error))
                       or restart.limited(retry_replacement=False))
            interrupted = not limited and (failed or restart.interrupted())
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
        environment['CLAUDE_SWITCHER_TERMINAL'] = terminal_name
        if hint:
            environment['CLAUDE_SWITCHER_TRANSCRIPT'] = str(hint)
        if isinstance(restart.last_session, dict):
            environment['CLAUDE_SWITCHER_REGISTRY_PID'] = str(restart.last_session['pid'])
        for mode in modes:
            launch([mode, session_id, pane], environment)
    except (SessionEnded, SwitcherError, OSError, ValueError, subprocess.SubprocessError):
        pass
    return 0


def configured_terminal(state):
    """The name and an instance of the terminal config.json names, read here because a turn end
    must not import service.py (its HTTP and TLS modules)."""
    name = state.load('config').get('terminal', DEFAULT_TERMINAL)
    return name, pick('terminal', name)()


def record_outcome(state, session_id, outcome):
    with (state.root / LOG).open('a') as stream:
        stream.write(json.dumps({'at': time.time(), 'session': str(session_id)[:8],
                                 'outcome': outcome}) + '\n')


def launch(arguments, environment):
    subprocess.Popen([sys.executable, __file__, *arguments],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True, env=environment)


def helper_lock(mode, session_id, pane):
    return ('restart-resume-' if mode == '--resume' else 'restart-') + \
        receipt_name(session_id, pane).removeprefix('handoff-')


def sweep_if_due(state):
    """Start a detached sweep at most once a SWEEP_SECONDS from any session's turn end."""
    now = time.time()
    if now - state.load('sweep').get('at', 0) < SWEEP_SECONDS:
        return
    state.save('sweep', {'at': now})
    launch(['--sweep'], os.environ.copy())


def run_sweep():
    state = State(state_dir())
    try:
        with state.lock('sweep'):
            sweep(state)
    except (LockBusy, SwitcherError, OSError, ValueError, subprocess.SubprocessError):
        pass  # the next turn end tries again
    return 0


def sweep(state):
    """Start a helper for each stopped session that none handles now. The helpers inherit this
    process's terminal access and type into the stopped session's own pane."""
    terminal_name, terminal = configured_terminal(state)
    for session_id, pane, pid, mode in stuck_sessions(Path.home() / '.claude', state, terminal):
        try:
            with state.lock(helper_lock(mode, session_id, pane)):
                pass  # free: no helper holds this session
        except LockBusy:
            continue
        environment = os.environ.copy()
        environment.pop('CLAUDE_SWITCHER_ANCESTORS', None)
        environment.pop('CLAUDE_SWITCHER_TRANSCRIPT', None)
        environment.update(ACCOUNT_SWITCHER_STATE_DIR=str(state.root),
                           CLAUDE_SWITCHER_REGISTRY_PID=str(pid), CLAUDE_SWITCHER_TERMINAL=terminal_name)
        launch([mode, session_id, pane], environment)


def helper(session_id, pane, mode='--helper'):
    state = State(state_dir())
    resume = mode == '--resume'
    # A resume helper waits for the one before it: that one may have just typed the prompt whose
    # turn failed again and started this helper.
    try:
        terminal = pick('terminal', os.environ.get('CLAUDE_SWITCHER_TERMINAL', DEFAULT_TERMINAL))()
        restart = SelfRestart(state, Path.home() / '.claude', session_id, pane, terminal)
        with state.lock(helper_lock(mode, session_id, pane), blocking=resume):
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
    record_outcome(state, session_id, outcome)
    return 0


if __name__ == '__main__':
    if len(sys.argv) == 4 and sys.argv[1] in ('--helper', '--resume'):
        sys.exit(helper(sys.argv[2], sys.argv[3], sys.argv[1]))
    if sys.argv[1:] == ['--sweep']:
        sys.exit(run_sweep())
    sys.exit(hook())
