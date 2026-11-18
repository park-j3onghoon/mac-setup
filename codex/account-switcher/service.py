"""Start the user-owned supervisor only when an automatic session is requested."""

from pathlib import Path
import subprocess
import sys
import time

from policy import UsageUnavailable
from runtime import SOCKET, prepare_home
from state import load


def process_start(pid):
    """PID 재사용을 구분하며 명령 인자나 환경의 인증정보는 읽지 않는다."""
    if not isinstance(pid, int) or pid < 2:
        return None
    try:
        result = subprocess.run(['/bin/ps', '-o', 'lstart=', '-p', str(pid)],
                                capture_output=True, text=True, timeout=2, check=False,
                                env={'LC_ALL': 'C', 'TZ': 'UTC'})
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def running(state):
    updated = state.get('updated_at', 0)
    if (state.get('status') in ('stopped', 'failed') or not state.get('pid_start')
            or not isinstance(updated, (int, float)) or not 0 <= time.time() - updated < 120):
        return False
    return process_start(state.get('pid')) == state['pid_start']


def ensure():
    prepare_home()
    state = load()
    started_at = time.time()
    if not running(state):
        subprocess.Popen(
            [sys.executable, str(Path(__file__).with_name("supervisor.py"))],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = load()
        if running(state) and state.get("active") and SOCKET.exists():
            return state
        if state.get("status") == "failed" and state.get("updated_at", 0) >= started_at:
            raise UsageUnavailable("Automatic account service could not start")
        time.sleep(0.2)
    raise UsageUnavailable("Automatic account service is not ready; saved logins are unchanged")
