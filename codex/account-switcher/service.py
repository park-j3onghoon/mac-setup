"""Start the user-owned supervisor only when an automatic session is requested."""

from contextlib import closing
import errno
import fcntl
import os
from pathlib import Path
import plistlib
import re
import select
import socket
import subprocess
import sys
import tempfile
import time

from policy import UsageUnavailable
from runtime import SOCKET, peer_process, prepare_home, process_start
from state import RUNTIME, load


LABEL = 'local.codex-account-switcher'


def running(state):
    updated = state.get('updated_at', 0)
    if (state.get('status') in ('stopped', 'failed') or not state.get('pid_start')
            or not isinstance(updated, (int, float))):
        return False
    if not 0 <= time.time() - updated < 120:
        try:
            stamp = (RUNTIME / 'supervisor-heartbeat').stat().st_mtime
        except OSError:
            return False
        if (not updated <= stamp <= time.time() < stamp + 120
                or time.time() - updated > 300):
            return False
    return process_start(state.get('pid')) == state['pid_start']


def service_plist():
    return Path.home() / f'Library/LaunchAgents/{LABEL}.plist'


def launchctl(*args):
    try:
        return subprocess.run(['/bin/launchctl', *args], capture_output=True, text=True, timeout=10)
    except subprocess.TimeoutExpired as error:
        raise UsageUnavailable(f'launchctl {args[0]} timed out') from error


def job_status(target):
    return launchctl('print', target)


def matches_runtime(connection, state):
    try:
        return peer_process(connection) == (state.get('runtime_pid'), state.get('runtime_pid_start'))
    except UsageUnavailable:
        return False


def job_pid(output):
    match = re.search(r'^\s*pid = ([1-9]\d*)\s*$', output, re.M)
    return int(match[1]) if match else None


def start_reload_watcher(pending):
    with pending.open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--finish-reload', str(lock.fileno())],
                             pass_fds=(lock.fileno(),), start_new_session=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as error:
            print(f'Codex service registration is pending: {error}', file=sys.stderr)


def finish_pending_reload():
    target = f'gui/{os.getuid()}/{LABEL}'
    pending = service_plist().with_suffix('.reload-pending')
    while pending.exists():
        try:
            registered = job_status(target)
            pid = job_pid(registered.stdout) if registered.returncode == 0 else None
            if pid:
                with closing(select.kqueue()) as watcher:
                    watcher.control([select.kevent(pid, filter=select.KQ_FILTER_PROC, flags=select.KQ_EV_ADD,
                                                   fflags=select.KQ_NOTE_EXIT)], 0, 0)
                    # Recheck the job after registering so a recycled PID cannot strand this watcher.
                    if job_pid(job_status(target).stdout) == pid:
                        watcher.control([], 1, None)
            install_service(watch=False)
        except (OSError, subprocess.TimeoutExpired, UsageUnavailable):
            pass
        if pending.exists():
            time.sleep(2)


def install_service(*, watch=True):
    destination = service_plist()
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.with_suffix('.install-lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        install_registration(destination, watch)


def install_registration(destination, watch):
    domain = f'gui/{os.getuid()}'
    target = f'{domain}/{LABEL}'
    # Cellar의 패치 버전 경로는 Homebrew 업데이트로 사라질 수 있다.
    python = Path(f'/opt/homebrew/opt/python@{sys.version_info.major}.{sys.version_info.minor}'
                  f'/bin/python{sys.version_info.major}.{sys.version_info.minor}')
    if not python.is_file():
        python = Path(sys.executable)
    configuration = {
        'Label': LABEL,
        'ProgramArguments': [str(python), str(Path(__file__).with_name('supervisor.py').resolve())],
        'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 10,
        'AbandonProcessGroup': True, 'ProcessType': 'Background',
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null',
    }
    pending = destination.with_suffix('.reload-pending')
    registered = job_status(target)
    already_loaded = False
    if registered.returncode == 0:
        try:
            saved = plistlib.loads(destination.read_bytes())
        except (FileNotFoundError, ValueError, plistlib.InvalidFileException):
            saved = {}
        output = registered.stdout if isinstance(registered.stdout, str) else ''
        match = re.search(r'^\s*arguments = \{\n(.*?)^\s*\}', output, re.M | re.S)
        arguments = [line.strip() for line in match[1].splitlines() if line.strip()] if match else saved.get('ProgramArguments')
        already_loaded = arguments == configuration['ProgramArguments'] and all(
            Path(path).is_file() for path in arguments)
        properties = re.search(r'^\s*properties = (.+)$', output, re.M)
        stale = (saved != configuration or pending.exists() or properties is not None
                 and 'keepalive' not in properties[1].lower().split(' | '))
        if already_loaded and not stale:
            return
        inactive = re.search(r'^\s*state = (?:not running|exited|waiting|spawn scheduled)\s*$', output, re.M)
        if already_loaded and (not inactive or job_pid(output)):
            # Reload only once launchd reports that the existing supervisor has exited.
            if not pending.exists():
                pending.touch(mode=0o600)
            if watch and job_pid(output):
                start_reload_watcher(pending)
            if saved == configuration:
                return
        else:
            already_loaded = False
            result = launchctl('bootout', target)
            if result.returncode:
                raise UsageUnavailable("Could not replace the obsolete supervisor registration")
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{LABEL}-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            plistlib.dump(configuration, stream)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    if already_loaded:
        return
    result = launchctl('bootstrap', domain, str(destination))
    if result.returncode and job_status(target).returncode:
        raise UsageUnavailable(f'Automatic supervisor registration failed: status={result.returncode}')
    pending.unlink(missing_ok=True)


def ensure(settings):
    prepare_home(config=settings.server_config)
    install_service()
    started_at = time.time()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = load()
        if state.get("active") and state.get("upgrade_status") != "draining" and SOCKET.exists() and running(state):
            try:
                with socket.socket(socket.AF_UNIX) as probe:
                    probe.settimeout(.3)
                    probe.connect(str(SOCKET))
                    if matches_runtime(probe, state):
                        return state
            except OSError as error:
                if not isinstance(error, TimeoutError) and error.errno not in (
                        errno.ECONNREFUSED, errno.ENOENT, errno.ENOTSOCK):
                    raise
        if state.get("status") == "failed" and state.get("updated_at", 0) >= started_at:
            raise UsageUnavailable("Automatic account service could not start")
        time.sleep(0.2)
    raise UsageUnavailable("Automatic account service is not ready; saved logins are unchanged")


if __name__ == '__main__' and len(sys.argv) == 3 and sys.argv[1] == '--finish-reload':
    # The inherited flock keeps this the only watcher through exec and until exit.
    with os.fdopen(int(sys.argv[2]), 'a'):
        finish_pending_reload()
