"""Own an isolated app-server; account changes stay in that server's memory."""

import os
from pathlib import Path
import socket
import subprocess
import time

from policy import UsageUnavailable
from profiles import BINARY
from rpc import Rpc
from state import RUNTIME


SOCKET = RUNTIME / "auto.sock"


def prepare_home(home=RUNTIME):
    home = Path(home)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    home.chmod(0o700)
    source = Path.home() / ".codex"
    for name in ("config.toml", "AGENTS.md", "skills", "agents", "rules",
                 "plugins", "packages", "hooks.json", ".hook-trust"):
        target = home / name
        if not target.exists() and not target.is_symlink() and (source / name).exists():
            target.symlink_to(source / name, target_is_directory=(source / name).is_dir())


def all_idle(client):
    cursor = None
    while True:
        response = client.request("thread/loaded/list", {"cursor": cursor})
        for thread_id in response.get("data", []):
            thread = client.request("thread/read", {
                "threadId": thread_id, "includeTurns": False,
            }).get("thread", {})
            if thread.get("status", {}).get("type") not in ("idle", "notLoaded"):
                return False
        cursor = response.get("nextCursor")
        if not cursor:
            return True


class Runtime:
    def __init__(self, profiles, home=RUNTIME, binary=BINARY):
        self.profiles, self.home, self.binary = profiles, Path(home), binary
        self.socket = self.home / "auto.sock"
        self.process = self.client = None
        self.active = None

    def start(self):
        prepare_home(self.home)
        if self.socket.exists():
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(str(self.socket))
            except (ConnectionRefusedError, FileNotFoundError):
                self.socket.unlink(missing_ok=True)
            else:
                raise UsageUnavailable("An existing automatic runtime is still listening")
            finally:
                probe.close()
        self.process = subprocess.Popen(
            [str(self.binary), "app-server", "--listen", "unix://" + str(self.socket)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, CODEX_HOME=str(self.home)),
        )
        deadline = time.monotonic() + 20
        while not self.socket.exists():
            if self.process.poll() is not None or time.monotonic() >= deadline:
                raise UsageUnavailable("Automatic Codex runtime did not start")
            time.sleep(0.1)
        self.client = Rpc(self.binary, self.home, self.socket, self.refresh)

    def refresh(self, method, params):
        if method != "account/chatgptAuthTokens/refresh":
            raise UsageUnavailable("Unexpected runtime request")
        previous = params.get("previousAccountId")
        for profile in self.profiles.values():
            if profile.account_id == previous:
                return profile.tokens(force=True)
        raise UsageUnavailable("Unknown account requested a token refresh")

    def select(self, name):
        if name == self.active:
            return True
        if not all_idle(self.client):
            return False
        old = self.active
        profile = self.profiles[name]
        try:
            self.client.request("account/login/start", {
                "type": "chatgptAuthTokens", **profile.tokens(),
            })
            verified = self.client.request("account/rateLimits/read")
            if verified.get("accountId") != profile.account_id:
                raise UsageUnavailable("Runtime account verification did not match")
            self.active = name
            return True
        except Exception:
            self.active = None
            if old is not None:
                try:
                    self.client.request("account/login/start", {
                        "type": "chatgptAuthTokens", **self.profiles[old].tokens(),
                    })
                    restored = self.client.request("account/rateLimits/read")
                    if restored.get("accountId") == self.profiles[old].account_id:
                        self.active = old
                except Exception:
                    pass
            raise

    def close(self):
        if self.client:
            self.client.close()
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
