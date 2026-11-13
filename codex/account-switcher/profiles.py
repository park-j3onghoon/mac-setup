"""Keep each original managed login separate; supply runtime tokens in memory."""

import base64
import json
from pathlib import Path
import threading
import time

from policy import UsageUnavailable
from rpc import Rpc
from state import snapshot


BINARY = Path("/opt/homebrew/bin/codex")
PROFILES = {"company": Path.home() / ".codex-buzzvil",
            "personal": Path.home() / ".codex"}


def credentials(home):
    try:
        data = json.loads((Path(home) / "auth.json").read_text())
        token = data["tokens"]["access_token"]
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
        auth = claims["https://api.openai.com/auth"]
        return {"accessToken": token, "chatgptAccountId": auth["chatgpt_account_id"],
                "chatgptPlanType": auth["chatgpt_plan_type"], "expires": claims["exp"]}
    except (OSError, ValueError, KeyError, IndexError) as error:
        raise UsageUnavailable("Saved ChatGPT login cannot be read") from error


class Profile:
    def __init__(self, name, home, binary=BINARY):
        self.name, self.home, self.binary = name, home, binary
        self.account_id = credentials(home)["chatgptAccountId"]
        self.client = None
        self.lock = threading.Lock()

    def _connect(self):
        if self.client is None:
            self.client = Rpc(self.binary, self.home)
        return self.client

    def tokens(self, force=False):
        with self.lock:
            value = credentials(self.home)
            if force or value["expires"] < time.time() + 300:
                self._connect().request("account/read", {"refreshToken": True}, timeout=8)
                value = credentials(self.home)
            if value["chatgptAccountId"] != self.account_id:
                raise UsageUnavailable(f"The saved {self.name} workspace changed")
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
                if self.client:
                    self.client.close()
                    self.client = None
                raise

    def close(self):
        with self.lock:
            if self.client:
                self.client.close()
                self.client = None
