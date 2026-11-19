"""Keep each original managed login separate; supply runtime tokens in memory."""

import base64
from contextlib import contextmanager
import json
from pathlib import Path
import threading
import time

from policy import UsageUnavailable
from rpc import Rpc
from state import snapshot


BINARY = Path("/opt/homebrew/bin/codex")
PROFILES = {"company": Path.home() / ".codex-work",
            "personal": Path.home() / ".codex"}


def credentials(home):
    try:
        data = json.loads((Path(home) / "auth.json").read_text())
        token = data["tokens"]["access_token"]
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
        auth = claims["https://api.openai.com/auth"]
        return {"accessToken": token, "chatgptAccountId": auth["chatgpt_account_id"],
                "chatgptPlanType": auth["chatgpt_plan_type"], "expires": claims["exp"]}
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise UsageUnavailable("Saved ChatGPT login cannot be read") from error


class Profile:
    def __init__(self, name, home, binary=BINARY):
        self.name, self.home, self.binary = name, home, binary
        try:
            self.account_id = credentials(home)["chatgptAccountId"]
        except UsageUnavailable:
            self.account_id = None
        self.client = None
        self.lock = threading.Lock()
        self.refresh_generation = 0
        self.failed_refresh = None

    def _connect(self, cancel=None):
        if self.client is not None and self.client.closed:
            self._disconnect()
        if self.client is None:
            self.client = Rpc(self.binary, self.home, cancel=cancel) if cancel is not None else Rpc(self.binary, self.home)
        return self.client

    def register(self, expected):
        with self.lock:
            current = credentials(self.home)['chatgptAccountId']
            if current != expected:
                raise UsageUnavailable('Saved workspace changed after registration was requested')
            self._disconnect()
            self.account_id = current
            self.failed_refresh = None

    @contextmanager
    def token_lock(self, cancel):
        if cancel is None:
            with self.lock:
                yield
            return
        while not cancel.is_set():
            if self.lock.acquire(timeout=.1):
                try:
                    if cancel.is_set():
                        raise UsageUnavailable('Refresh cancelled')
                    yield
                finally:
                    self.lock.release()
                return
        raise UsageUnavailable('Refresh cancelled')

    def tokens(self, force=False, *, cancel=None):
        generation = self.refresh_generation
        with self.token_lock(cancel):
            value = credentials(self.home)
            if self.account_id is None:
                self.account_id = value['chatgptAccountId']
            if value["chatgptAccountId"] != self.account_id:
                raise UsageUnavailable(f"The saved {self.name} workspace changed")
            if (self.failed_refresh and self.failed_refresh[0] == value['expires']
                    and value['expires'] <= time.time() and time.monotonic() < self.failed_refresh[1]):
                raise UsageUnavailable(f"The saved {self.name} login has expired")
            refresh = (force and generation == self.refresh_generation) or value['expires'] < time.time() + 300
            if refresh:
                try:
                    client = self._connect(cancel)
                    if cancel is None:
                        client.request("account/read", {"refreshToken": True}, timeout=8)
                    else:
                        client.request("account/read", {"refreshToken": True}, timeout=8, cancel=cancel)
                except UsageUnavailable:
                    if cancel is None or not cancel.is_set():
                        self._disconnect()
                    raise
                value = credentials(self.home)
                if value['expires'] <= time.time():
                    self.failed_refresh = (value['expires'], time.monotonic() + 60)
                    raise UsageUnavailable(f"The saved {self.name} login is still expired after refresh")
                self.failed_refresh = None
            if value["chatgptAccountId"] != self.account_id:
                raise UsageUnavailable(f"The saved {self.name} workspace changed")
            if refresh:
                self.refresh_generation += 1
            value.pop("expires")
            return value

    def usage(self):
        self.tokens()
        with self.lock:
            try:
                result = self._connect().request("account/rateLimits/read", timeout=20)
                if result.get("accountId") != self.account_id:
                    raise UsageUnavailable(f"The {self.name} usage belongs to another workspace")
                return snapshot(result)
            except Exception:
                self._disconnect()
                raise

    def close(self):
        with self.lock:
            self._disconnect()

    def _disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
