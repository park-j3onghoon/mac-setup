"""Start the user-owned supervisor only when an automatic session is requested."""

import errno
import os
from pathlib import Path
import plistlib
import re
import socket
import subprocess
import sys
import tempfile
import time

from policy import UsageUnavailable
from runtime import SOCKET, prepare_home, process_start
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


def install_service():
    domain = f'gui/{os.getuid()}'
    target = f'{domain}/{LABEL}'
    destination = Path.home() / f'Library/LaunchAgents/{LABEL}.plist'
    destination.parent.mkdir(parents=True, exist_ok=True)
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
    registered = subprocess.run(['/bin/launchctl', 'print', target], capture_output=True, text=True, timeout=10)
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
        if already_loaded and saved == configuration:
            return
        if not already_loaded:
            result = subprocess.run(['/bin/launchctl', 'bootout', target], capture_output=True, timeout=10)
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
    result = subprocess.run(['/bin/launchctl', 'bootstrap', domain, str(destination)],
                            capture_output=True, timeout=10)
    if result.returncode and subprocess.run(['/bin/launchctl', 'print', target],
                                           capture_output=True, timeout=10).returncode:
        raise UsageUnavailable(f'Automatic supervisor registration failed: status={result.returncode}')


def ensure():
    prepare_home()
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
                return state
            except OSError as error:
                if not isinstance(error, TimeoutError) and error.errno not in (
                        errno.ECONNREFUSED, errno.ENOENT, errno.ENOTSOCK):
                    raise
        if state.get("status") == "failed" and state.get("updated_at", 0) >= started_at:
            raise UsageUnavailable("Automatic account service could not start")
        time.sleep(0.2)
    raise UsageUnavailable("Automatic account service is not ready; saved logins are unchanged")
