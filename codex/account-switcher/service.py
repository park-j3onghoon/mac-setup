"""Start the user-owned supervisor only when an automatic session is requested."""

import os
from pathlib import Path
import plistlib
import subprocess
import sys
import tempfile
import time

from policy import UsageUnavailable
from runtime import SOCKET, prepare_home, process_start
from state import load


LABEL = 'local.codex-account-switcher'


def running(state):
    updated = state.get('updated_at', 0)
    if (state.get('status') in ('stopped', 'failed') or not state.get('pid_start')
            or not isinstance(updated, (int, float)) or not 0 <= time.time() - updated < 120):
        return False
    return process_start(state.get('pid')) == state['pid_start']


def install_service():
    domain = f'gui/{os.getuid()}'
    target = f'{domain}/{LABEL}'
    if subprocess.run(['/bin/launchctl', 'print', target], capture_output=True, timeout=10).returncode == 0:
        return
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
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{LABEL}-', dir=destination.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            plistlib.dump(configuration, stream)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
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
        if running(state) and state.get("active") and SOCKET.exists():
            return state
        if state.get("status") == "failed" and state.get("updated_at", 0) >= started_at:
            raise UsageUnavailable("Automatic account service could not start")
        time.sleep(0.2)
    raise UsageUnavailable("Automatic account service is not ready; saved logins are unchanged")
