"""Reopen the foreground Claude process on a committed local account switch."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import termios
import threading
import time
from uuid import UUID

from refresh import CONTINUE_PROMPT, background_work, completed, latest_message, process_children
from refresh_hook import state_dir
from storage import State, SwitcherError, read_json
from switcher import check_environment


# Only reconstruct launch options whose meaning survives a new process. Other command
# lines go straight through to the native CLI, including auth, print and background agents.
VALUE_OPTIONS = {'--effort', '--model', '--agent', '--permission-mode', '--name', '-n',
                 '--fallback-model', '--setting-sources', '--system-prompt-snapshot',
                 '--append-system-prompt', '--system-prompt', '--system-prompt-file',
                 '--append-system-prompt-file', '--agents', '--autocompact', '--plugin-dir',
                 '--permission-prompts'}
LIST_OPTIONS = {'--add-dir', '--allowedTools', '--allowed-tools', '--disallowedTools',
                '--disallowed-tools', '--tools', '--mcp-config'}
FLAGS = {'--verbose', '--chrome', '--no-chrome', '--ide', '--strict-mcp-config', '--brief',
         '--restricted', '--ax-screen-reader', '--exclude-dynamic-system-prompt-sections',
         '--disable-slash-commands', '--allow-dangerously-skip-permissions',
         '--dangerously-skip-permissions'}
COMMANDS = {'agents', 'attach', 'auth', 'auto-mode', 'doctor', 'gateway', 'import', 'install',
            'logs', 'mcp', 'plugin', 'plugins', 'purge', 'respawn', 'rm', 'setup-token',
            'stop', 'kill', 'ultrareview', 'update', 'upgrade', 'help'}


def resume_options(args):
    """Return options to preserve; omit the original task and any old session selector."""
    keep = []
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg == '--':
            break
        flag, equals, _ = arg.partition('=')
        if flag in VALUE_OPTIONS or flag == '--session-id':
            if not equals:
                if i == len(args) or args[i].startswith('-'):
                    return None
                i += 1
            if flag != '--session-id':
                keep.extend([arg] if equals else [arg, args[i - 1]])
        elif flag in LIST_OPTIONS:
            keep.append(arg)
            if not equals:
                start = i
                while i < len(args) and not args[i].startswith('-'):
                    i += 1
                if i == start:
                    return None
                keep.extend(args[start:i])
        elif arg in FLAGS:
            keep.append(arg)
        elif flag in ('-r', '--resume'):
            if not equals and i < len(args) and not args[i].startswith('-'):
                i += 1
        elif arg in ('-c', '--continue', '--fork-session'):
            continue
        elif arg.startswith('-') or arg in COMMANDS:
            return None
    return keep


def claim_continuation(state, sid, since, launch=None):
    # Two terminals may have opened the same transcript. Share a single submission
    # per conversation, retaining only the most recent account switch.
    with state.lock('resume-prompts', blocking=True):
        previous = state.load('resume_prompts')
        if previous.get('since', 0) > since:
            return launch(False) if launch else False
        sent = previous.get('sessions', []) if previous.get('since') == since else []
        if sid in sent:
            return launch(False) if launch else False
        child = launch(True) if launch else True
        try:
            state.save('resume_prompts', {'since': since, 'sessions': [*sent, sid]})
        except (SwitcherError, OSError, ValueError):
            if not launch:
                raise
            print('[claude] 복구 지시 전달 기록을 저장하지 못했습니다.', file=sys.stderr)
        return child


def switch_target(pid, launched, since, config_home):
    """Use the owned child's registry and an existing transcript before interrupting it."""
    session = read_json(config_home / 'sessions' / f'{pid}.json')
    if (session.get('pid') != pid or session.get('kind') != 'interactive'
            or not int(launched * 1000) <= session.get('startedAt', 0) < since * 1000):
        return None
    sid = str(UUID(session['sessionId']))
    directory = Path(session['cwd'])
    if not directory.is_absolute() or not directory.is_dir():
        return None
    projects = config_home / 'projects'
    entry = latest_message(projects, sid)
    if not entry:
        return None  # Claude cannot --resume a session before its first persisted message.
    status = session.get('status')
    if not status:
        return None
    unfinished = (status != 'idle' or not completed(entry)
                  or background_work(session, process_children(subprocess.run), projects,
                                     time.time(), check_completion=True))
    return sid, directory, unfinished, entry.get('uuid'), since


def run_session(binary, args, options, state, config_home, interval=2):
    child = None
    stopping = None

    def shutdown(signum, _frame):
        nonlocal stopping
        stopping = signum
        if child is not None:
            child.send_signal(signum)

    def terminal_interrupt(_signum, _frame):
        # The child belongs to this same foreground process group and receives the key itself.
        pass

    handlers = {sig: signal.signal(sig, handler) for sig, handler in (
        (signal.SIGHUP, shutdown), (signal.SIGTERM, shutdown),
        (signal.SIGINT, terminal_interrupt), (signal.SIGQUIT, terminal_interrupt))}
    env = os.environ.copy()
    cwd = None
    continuation = None
    try:
        while stopping is None:
            launched = time.time()
            # exec preserves the PID in the session registry. Descendant Claude sessions
            # can distinguish their own Stop hook from this managed foreground session.
            def launch(continue_turn):
                command = [binary, *args]
                if continue_turn:
                    command.extend(['--', CONTINUE_PROMPT])
                if cwd is not None:
                    return subprocess.Popen(command, cwd=cwd,
                        env=dict(env, MAC_SETUP_MANAGED_CLAUDE_SESSION_ID=sid))
                return subprocess.Popen(['/bin/sh', '-c',
                    'export MAC_SETUP_MANAGED_CLAUDE_PID=$$; exec "$@"',
                    'managed-claude', *command], cwd=cwd, env=env)

            if continuation:
                child = claim_continuation(state, *continuation, launch=launch)
                continuation = None
            else:
                child = launch(False)
            if stopping is not None:
                child.send_signal(stopping)
            finished = threading.Event()
            restart = None

            def monitor():
                nonlocal restart
                while not finished.wait(interval):
                    try:
                        since = state.load('session_refresh').get('since', 0)
                        if since <= launched:
                            continue
                        target = switch_target(child.pid, launched, since, config_home)
                        if (target and os.access(binary, os.X_OK) and not finished.is_set()
                                and child.poll() is None):
                            restart = target
                            child.terminate()
                            return
                    except (OSError, KeyError, TypeError, ValueError, SwitcherError, subprocess.SubprocessError):
                        # The registry and transcript may still be publishing the first turn.
                        continue

            watcher = threading.Thread(target=monitor, name='claude-account-switch', daemon=True)
            watcher.start()
            try:
                code = child.wait()
            finally:
                finished.set()
                watcher.join()
            child = None
            if stopping is not None or restart is None:
                return 128 - code if code < 0 else code
            sid, cwd, unfinished, previous_message, since = restart
            if previous_message:
                try:
                    last = latest_message(config_home / 'projects', sid)
                    if last and last.get('uuid') and last['uuid'] != previous_message:
                        unfinished = not completed(last)
                except (OSError, ValueError):
                    pass
            args = [*options, '--resume', sid]
            continuation = (sid, since) if unfinished else None
            # Supply exactly one continuation. Claude also has an optional native auto-resume.
            env['CLAUDE_CODE_RESUME_INTERRUPTED_TURN'] = '0'
            if os.isatty(0) and os.tcgetpgrp(0) == os.getpgrp():
                termios.tcflush(0, termios.TCIFLUSH)
        return 128 + stopping
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)


def main(binary, args):
    options = resume_options(args)
    root = state_dir()
    try:
        check_environment()
        manage = (options is not None and os.isatty(0) and os.isatty(1)
                  and os.tcgetpgrp(0) == os.getpgrp() and (root / 'config.json').is_file())
        if manage:
            state = State(root)
    except (OSError, SwitcherError):
        manage = False
    if not manage:
        os.execv(binary, [binary, *args])
    return run_session(binary, args, options, state, Path.home() / '.claude')


if __name__ == '__main__':
    sys.exit(main(sys.argv[1], sys.argv[2:]))
