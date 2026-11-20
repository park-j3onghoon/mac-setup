"""Reopen the foreground Claude process on a committed local account switch."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import NamedTuple
from uuid import NAMESPACE_URL, UUID, uuid5

from refresh import CONTINUE_PROMPT, background_work, completed, latest_message, process_children, transcript_lines
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


def continuation_id(sid, since):
    return str(uuid5(NAMESPACE_URL, f'claude-account-switcher/{sid}/{float(since).hex()}'))


def recovery_message(sid, since):
    return f'{CONTINUE_PROMPT}\n[계정 전환 복구 ID {continuation_id(sid, since)}]'


def receipt_in_history(projects, sid, since):
    """A durable user message is the receipt. Missing/unreadable history is inconclusive."""
    expected = recovery_message(sid, since)
    marker = continuation_id(sid, since).encode()
    readable = False
    incomplete = False
    for path in projects.glob(f'*/{sid}.jsonl'):
        try:
            for raw in transcript_lines(path):
                if readable and marker not in raw:
                    continue
                try:
                    entry = json.loads(raw)
                except ValueError:
                    incomplete = True
                    continue
                if isinstance(entry, dict) and entry.get('type') in ('user', 'assistant'):
                    readable = True
                if not isinstance(entry, dict) or entry.get('type') != 'user':
                    continue
                message = entry.get('message')
                if not isinstance(message, dict):
                    incomplete = True
                    continue
                content = message.get('content')
                if content == expected or isinstance(content, list) and any(
                        isinstance(block, dict) and block.get('type') == 'text' and block.get('text') == expected
                        for block in content):
                    return True
        except OSError:
            incomplete = True
    return False if readable and not incomplete else None


def notice(message):
    # OSC 9 is a terminal notification, so an active screen editor and its cursor
    # stay intact. Redirected stderr gets the same message as a normal log line.
    if sys.stderr.isatty():
        print(f'\033]9;[claude] {message}\007', end='', file=sys.stderr, flush=True)
    else:
        print(f'[claude] {message}', file=sys.stderr, flush=True)


def finish_receipt(state, sid, since, projects, *, clean_exit):
    """Resolve only our saved claim; a newer switch may already own the state file."""
    with state.lock('resume-prompts', blocking=True):
        record = state.load('resume_prompts')
        if record.get('since') != since or sid not in record.get('pending', []):
            return
        received = receipt_in_history(projects, sid, since)
        if received is not True and (not clean_exit or received is None):
            notice(f'복구 지시 접수 여부를 확인할 수 없습니다. 대화 {sid}의 마지막 입력을 확인해 주세요.')
            return
        record['pending'].remove(sid)
        if received:
            record.setdefault('sessions', []).append(sid)
        else:
            notice(f'대화 {sid}가 복구 지시를 기록하기 전에 종료했습니다. 같은 전환에서 다시 제출할 수 있습니다.')
        state.save('resume_prompts', record)


def claim_continuation(state, sid, since, launch=None, *, projects=None):
    # Save the claim before spawning. A crash across exec is uncertain until the
    # deterministic marker appears in the transcript; another terminal must not resend it.
    with state.lock('resume-prompts', blocking=True):
        previous = state.load('resume_prompts')
        current = state.load('session_refresh').get('since')
        if current is not None and current != since or current is None and previous.get('since', 0) > since:
            return launch(False) if launch else False
        record = previous if previous.get('since') == since else {'since': since, 'sessions': []}
        pending = record.setdefault('pending', [])
        if sid in record.get('sessions', []):
            return launch(False) if launch else False
        if projects is not None and receipt_in_history(projects, sid, since) is True:
            if sid in pending:
                pending.remove(sid)
            record.setdefault('sessions', []).append(sid)
            try:
                state.save('resume_prompts', record)
            except (OSError, SwitcherError, ValueError):
                notice(f'대화 {sid}에서 복구 접수를 확인했으나 상태를 저장하지 못했습니다.')
            return launch(False) if launch else False
        if sid in pending:
            if launch:
                notice(f'대화 {sid}의 복구 지시는 접수 확인 중입니다. 기존 대화 기록을 확인해 주세요.')
            return launch(False) if launch else False
        pending.append(sid)
        try:
            state.save('resume_prompts', record)
        except (SwitcherError, OSError, ValueError):
            if not launch:
                raise
            notice(f'대화 {sid}의 복구 예약을 저장할 수 없어 입력 없이 다시 엽니다.')
            return launch(False)
        if not launch:
            return True
        try:
            return launch(True)
        except OSError:
            # Popen reports an exec failure before the CLI can accept this input.
            pending.remove(sid)
            state.save('resume_prompts', record)
            raise


class Handoff(NamedTuple):
    sid: str
    cwd: Path
    unfinished: bool
    last_id: str | None
    since: float
    background: bool
    pid: int


def switch_target(pid, launched, since, config_home):
    """Identify the owned child and committed switch before offering a handoff."""
    if type(since) not in (int, float) or not launched < since <= time.time():
        return None
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
    background = background_work(session, process_children(subprocess.run), projects,
                                 time.time(), check_completion=True)
    return Handoff(sid, directory, status != 'idle' or not completed(entry) or background,
                   entry.get('uuid'), since, background, pid)


def run_session(binary, args, options, state, config_home, interval=2):
    child = None
    stopping = None
    projects = config_home / 'projects'

    def shutdown(signum, _frame):
        nonlocal stopping
        stopping = signum
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    def terminal_interrupt(_signum, _frame):
        # The child belongs to this same foreground process group and receives the key itself.
        pass

    handlers = {sig: signal.signal(sig, handler) for sig, handler in (
        (signal.SIGHUP, shutdown), (signal.SIGTERM, shutdown),
        (signal.SIGINT, terminal_interrupt), (signal.SIGQUIT, terminal_interrupt))}
    env = os.environ.copy()
    cwd = None
    sid = None
    continuation = None
    handled_switch = None
    try:
        while stopping is None:
            # A fresh process already reads the current login, even if the wall clock
            # moved backwards relative to the switch recorded before this launch.
            try:
                initial_switch = state.load('session_refresh').get('since')
            except (OSError, ValueError, SwitcherError):
                initial_switch = None
            launched = time.time()
            receipt = None

            def launch(continue_turn):
                nonlocal receipt
                command = [binary, *args]
                if continue_turn:
                    command.extend(['--', recovery_message(*continuation)])
                if cwd is not None:
                    process = subprocess.Popen(command, cwd=cwd,
                        env=dict(env, MAC_SETUP_MANAGED_CLAUDE_SESSION_ID=sid))
                else:
                    process = subprocess.Popen(['/bin/sh', '-c',
                        'export MAC_SETUP_MANAGED_CLAUDE_PID=$$; exec "$@"',
                        'managed-claude', *command], env=env)
                if continue_turn:
                    receipt = continuation
                return process

            if continuation:
                child = claim_continuation(state, *continuation, launch=launch, projects=projects)
                continuation = None
            else:
                child = launch(False)
            if stopping is not None:
                child.send_signal(stopping)
            restart = None
            shutdown_deadline = None
            warned_shutdown = False
            while True:
                try:
                    code = child.wait(timeout=interval)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if stopping is not None:
                    if shutdown_deadline is None:
                        shutdown_deadline = time.monotonic() + 10
                    if not warned_shutdown and time.monotonic() >= shutdown_deadline:
                        notice(f'Claude PID {child.pid}가 종료 신호에 응답하지 않습니다. 현재 프로세스를 확인해 주세요.')
                        warned_shutdown = True
                    continue
                try:
                    since = state.load('session_refresh').get('since')
                    if since is None or since in (initial_switch, handled_switch) or (restart and since == restart.since):
                        continue
                    target = switch_target(child.pid, launched, since, config_home)
                    if target and os.access(binary, os.X_OK) and child.poll() is None:
                        if restart is None:
                            notice(f'계정이 전환되었습니다. 초안을 보내거나 보관한 뒤 /exit 하면 같은 대화를 새 계정으로 엽니다. '
                                   f'종료가 지연되면 현재 Claude PID {child.pid}의 작업 상태를 먼저 확인해 주세요.')
                        restart = target
                except (OSError, KeyError, TypeError, ValueError, SwitcherError, subprocess.SubprocessError):
                    # The registry and first transcript may still be publishing.
                    continue
            child = None
            if receipt:
                try:
                    finish_receipt(state, *receipt, projects, clean_exit=code == 0)
                except (OSError, ValueError, SwitcherError):
                    notice(f'대화 {sid}의 복구 접수를 확인하지 못했습니다. 마지막 입력을 확인해 주세요.')
            if stopping is not None or restart is None or code != 0:
                return 128 - code if code < 0 else code
            # The native CLI owns its editor. Only its deliberate, clean exit hands
            # off the terminal; reading an idle registry cannot prove a draft is empty.
            sid, cwd, unfinished = restart.sid, restart.cwd, restart.unfinished
            handled_switch = restart.since
            try:
                last = latest_message(projects, sid)
                if last and last.get('uuid') and last['uuid'] != restart.last_id:
                    remaining = background_work({'pid': restart.pid, 'sessionId': sid},
                                                process_children(subprocess.run), projects,
                                                time.time(), check_completion=True)
                    unfinished = not completed(last) or restart.background or remaining
            except (OSError, KeyError, ValueError, SwitcherError, subprocess.SubprocessError):
                unfinished = True
            args = [*options, '--resume', sid]
            continuation = (sid, handled_switch) if unfinished else None
            env['CLAUDE_CODE_RESUME_INTERRUPTED_TURN'] = '0'
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
