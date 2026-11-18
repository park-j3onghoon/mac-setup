"""Own an isolated app-server; account changes stay in that server's memory."""

import os
from collections import deque
from pathlib import Path
import resource
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


def raise_file_limit():
    """새 Codex 프로세스의 용량을 보완하며 hard limit은 유지한다."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    target = 4096 if hard == resource.RLIM_INFINITY else min(4096, hard)
    if soft != resource.RLIM_INFINITY and soft < target:
        resource.setrlimit(resource.RLIMIT_NOFILE, (target, hard))


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
    """Yield (thread id, thread without turns) for every thread loaded in the runtime."""
    cursor = None
    while True:
        response = client.request("thread/loaded/list", {"cursor": cursor})
        for thread_id in response.get("data", []):
            yield thread_id, client.request("thread/read", {
                "threadId": thread_id, "includeTurns": False,
            }).get("thread", {})
        cursor = response.get("nextCursor")
        if not cursor:
            return


def quiet(thread):
    return thread.get("status", {}).get("type") in QUIET


def all_idle(client):
    return all(quiet(thread) for _, thread in loaded_threads(client))


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
        self.pid = None
        self.active = None
        self.continued = set()
        self.release_ids = deque()
        self.release_cursor = None

    def start(self, existing_pid=None):
        prepare_home(self.home)
        if self.socket.exists():
            probe = socket.socket(socket.AF_UNIX)
            try:
                probe.connect(str(self.socket))
            except (ConnectionRefusedError, FileNotFoundError):
                self.socket.unlink(missing_ok=True)
            else:
                if not isinstance(existing_pid, int) or existing_pid < 2:
                    raise UsageUnavailable("An existing automatic runtime is still listening")
                os.kill(existing_pid, 0)
                self.pid = existing_pid
                self.observe_account()
                return
            finally:
                probe.close()
        # Every loaded conversation can retain MCP pipes and sockets in this one process.
        # macOS's inherited soft limit of 256 is insufficient for the shared server.
        raise_file_limit()
        # The company config locks logins to the company workspace; the shared server must also
        # accept the personal workspace. A terminal attached to it does not enforce the lock
        # (both measured on 0.168.0, 2026-11-13).
        self.process = subprocess.Popen(
            [str(self.binary), "app-server", "-c", 'forced_chatgpt_workspace_id=""',
             "--listen", "unix://" + str(self.socket)],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env=dict(os.environ, CODEX_HOME=str(self.home)),
        )
        self.pid = self.process.pid
        deadline = time.monotonic() + 20
        while not self.socket.exists():
            if self.process.poll() is not None or time.monotonic() >= deadline:
                raise UsageUnavailable("Automatic Codex runtime did not start")
            time.sleep(0.1)
        self.client = Rpc(self.binary, self.home, self.socket, self.refresh)

    def observe_account(self):
        """Read the server's current identity even when another client changed it.

        Logging in again would restart every loaded thread's MCP servers, and token refresh
        requests reach every connection anyway (app-server/src/outgoing_message.rs in 0.169.0).
        """
        self.active = None
        if self.client is None or self.client.closed:
            if self.client:
                self.client.close()
            self.client = Rpc(self.binary, self.home, self.socket, self.refresh)
        response = self.client.request("account/read", {"refreshToken": False})
        if response.get("account") is None:
            return
        account = (response.get("workspaceRouting") or {}).get("chatgptAccountId")
        self.active = next((name for name, profile in self.profiles.items()
                            if profile.account_id == account), None)
        if self.active is None:
            raise UsageUnavailable("Existing runtime account is outside the saved profiles")

    def running(self):
        if self.process is not None:
            return self.process.poll() is None
        try:
            os.kill(self.pid, 0)
            return True
        except ProcessLookupError:
            return False

    def refresh(self, method, params):
        if method != "account/chatgptAuthTokens/refresh":
            raise UsageUnavailable("Unexpected runtime request")
        previous = params.get("previousAccountId")
        for profile in self.profiles.values():
            if profile.account_id == previous:
                return profile.tokens(force=True)
        raise UsageUnavailable("Unknown account requested a token refresh")

    def release_subscriptions(self):
        """한 대화씩 최대 2초 안에 정리하여 감독 루프에 제어를 돌려준다."""
        if self.client.closed:
            self.release_ids.clear()
            self.release_cursor = None
            return True
        deadline = time.monotonic() + 2

        def request(method, params):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise UsageUnavailable('Subscription cleanup budget exhausted')
            return self.client.request(method, params, timeout=remaining)

        if not self.release_ids:
            page = request('thread/loaded/list', {'cursor': self.release_cursor})
            self.release_ids.extend(page.get('data', []))
            self.release_cursor = page.get('nextCursor')
        if self.release_ids:
            thread_id = self.release_ids[0]
            params = {'threadId': thread_id}
            try:
                thread = request('thread/read', {**params, 'includeTurns': False}).get('thread', {})
                if quiet(thread) and not request('thread/backgroundTerminals/list', params)['data']:
                    request('thread/unsubscribe', params)
            finally:
                self.release_ids.popleft()
        return not self.release_ids and not self.release_cursor

    def select(self, name, *, force=False):
        if self.client.closed:
            self.observe_account()
        if name == self.active:
            return True
        if not force and not all_idle(self.client):
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
        for thread_id, thread in loaded_threads(self.client):
            # A parent drives its sub-agents; the server answers turn/start on one with an error
            # (0.169.0, 2026-11-18), which used to stop this loop every minute.
            if thread.get("parentThreadId") or not quiet(thread):
                continue
            turn = newest_turn(self.client, thread_id)
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
