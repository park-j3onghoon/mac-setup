"""Own an isolated app-server; account changes stay in that server's memory."""

import os
from pathlib import Path
import socket
import subprocess
import time

from policy import UsageUnavailable
from profiles import BINARY, PROFILES
from rpc import Rpc
from state import RUNTIME


SOCKET = RUNTIME / "auto.sock"
CONTINUE_PROMPT = "이어서 해줘"
# A thread in systemError runs nothing; leaving it out of the wait keeps one failed thread
# from blocking every later switch.
QUIET = ("idle", "notLoaded", "systemError")


def prepare_home(home=RUNTIME, shared=Path.home() / ".codex",
                 config=PROFILES["company"] / "config.toml"):
    home = Path(home)
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    home.chmod(0o700)
    # Company comes first, so the shared server opens with the company setup (MCP servers,
    # model); earlier versions linked the personal config here.
    target = home / "config.toml"
    if target.is_symlink() and target.readlink() != config:
        target.unlink()
    if not target.exists() and not target.is_symlink():
        target.symlink_to(config)
    for name in ("AGENTS.md", "skills", "agents", "rules",
                 "plugins", "packages", "hooks.json", ".hook-trust"):
        target = home / name
        if not target.exists() and not target.is_symlink() and (shared / name).exists():
            target.symlink_to(shared / name, target_is_directory=(shared / name).is_dir())


def loaded_threads(client):
    """Yield (thread id, status type) for every thread loaded in the runtime."""
    cursor = None
    while True:
        response = client.request("thread/loaded/list", {"cursor": cursor})
        for thread_id in response.get("data", []):
            thread = client.request("thread/read", {
                "threadId": thread_id, "includeTurns": False,
            }).get("thread", {})
            yield thread_id, thread.get("status", {}).get("type")
        cursor = response.get("nextCursor")
        if not cursor:
            return


def all_idle(client):
    return all(status in QUIET for _, status in loaded_threads(client))


def newest_turn(client, thread_id):
    try:
        turns = client.request("thread/turns/list", {
            "threadId": thread_id, "limit": 1, "sortDirection": "desc", "itemsView": "notLoaded",
        }).get("data", [])
    except UsageUnavailable:
        # A thread whose first turn has not been written yet has no rollout to list.
        return None
    return turns[0] if turns else None


class Runtime:
    def __init__(self, profiles, home=RUNTIME, binary=BINARY):
        self.profiles, self.home, self.binary = profiles, Path(home), binary
        self.socket = self.home / "auto.sock"
        self.process = self.client = None
        self.active = None
        self.continued = set()

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
        # The company config locks logins to the company workspace; the shared server must also
        # accept the personal workspace. A terminal attached to it does not enforce the lock
        # (both measured on 0.168.0, 2026-11-13).
        self.process = subprocess.Popen(
            [str(self.binary), "app-server", "-c", 'forced_chatgpt_workspace_id=""',
             "--listen", "unix://" + str(self.socket)],
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

    def continue_limited(self):
        """Start CONTINUE_PROMPT once on each quiet thread whose newest turn hit the usage limit.

        A turn started from this connection still sends its approval requests to the terminal
        that opened the thread (measured on 0.168.0, 2026-11-13).
        """
        for thread_id, status in loaded_threads(self.client):
            turn = newest_turn(self.client, thread_id) if status in QUIET else None
            if (not turn or turn["id"] in self.continued or turn["status"] != "failed"
                    or (turn.get("error") or {}).get("codexErrorInfo") != "usageLimitExceeded"):
                continue
            self.client.request("turn/start", {
                "threadId": thread_id, "input": [{"type": "text", "text": CONTINUE_PROMPT}],
            })
            self.continued.add(turn["id"])

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
