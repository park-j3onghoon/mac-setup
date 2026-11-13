"""Start the user-owned supervisor only when an automatic session is requested."""

import os
from pathlib import Path
import subprocess
import sys
import time

from policy import UsageUnavailable
from runtime import SOCKET, prepare_home
from state import load


def running(state):
    pid = state.get("pid")
    if not isinstance(pid, int) or pid < 2:
        return False
    try:
        os.kill(pid, 0)
        return state.get("status") not in ("stopped", "failed")
    except ProcessLookupError:
        return False
    except PermissionError:
        # Sandboxed Codex tools may read state but cannot send even signal 0.
        return (state.get("status") not in ("stopped", "failed")
                and time.time() - state.get("updated_at", 0) < 120)


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
