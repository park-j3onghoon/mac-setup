"""Keep each original managed login separate; supply runtime tokens in memory."""

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import json
import math
import os
from pathlib import Path
import stat
import threading
import time

from policy import DEFAULT_POLICY, DEFAULT_POLICY_NAME, DEFAULT_THRESHOLD, SHORTEST_POLL, UsageUnavailable
from rpc import Rpc
from state import RUNTIME, load, read_checkpoint, save, snapshot
from switchcore.choices import pick
from switchcore.policy import POLICIES, SwitchPolicy


BINARY = Path("/opt/homebrew/bin/codex")
DEFAULT_HOMES = {"company": Path.home() / ".codex-work",
                 "personal": Path.home() / ".codex"}
# A computer's own values live outside git; the launcher runs through a ~/.local/bin link.
SETTINGS_FILE = Path(__file__).resolve().parents[2] / "private/codex/account-switcher/config.json"
SETTING_KEYS = ("homes", "threshold", "policy")


@dataclass(frozen=True)
class Settings:
    homes: dict[str, Path]
    threshold: float
    policy: SwitchPolicy

    @property
    def server_config(self):
        """The automatic server opens with the company setup (MCP servers, model)."""
        return self.homes["company"] / "config.toml"


DEFAULT_SETTINGS = Settings(DEFAULT_HOMES, DEFAULT_THRESHOLD, DEFAULT_POLICY)


def load_settings(path=None):
    """This computer's SETTINGS_FILE, or the built-in settings without one. UsageUnavailable tells
    which value to fix; the file picks the homes whose tokens the switcher reads."""
    path = SETTINGS_FILE if path is None else Path(path)
    if not path.exists() and not path.is_symlink():
        return DEFAULT_SETTINGS
    for item in (path.parent, path):
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or info.st_uid != os.getuid():
            raise UsageUnavailable(f"Switcher settings must be your own file, not a link: {item}")
    path.parent.chmod(0o700)
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise UsageUnavailable(f"Cannot read switcher settings: {path}") from error
    if not isinstance(value, dict) or set(value) - set(SETTING_KEYS):
        raise UsageUnavailable(f"Invalid switcher settings: {path} (keys: {', '.join(SETTING_KEYS)})")
    homes = dict(DEFAULT_HOMES)
    folders = value.get("homes", {})
    if not isinstance(folders, dict) or set(folders) - set(homes):
        raise UsageUnavailable("Invalid switcher setting: homes (keys: company, personal)")
    for name, folder in folders.items():
        if not isinstance(folder, str) or "/" in folder or folder in ("", ".", "..", RUNTIME.name):
            raise UsageUnavailable(f"Invalid switcher setting: homes.{name}={folder} "
                                   "(one folder name directly under your home)")
        homes[name] = Path.home() / folder
    if homes["company"] == homes["personal"]:
        raise UsageUnavailable("Invalid switcher setting: homes (company and personal must differ)")
    threshold = value.get("threshold", DEFAULT_THRESHOLD)
    if (isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not math.isfinite(threshold) or not 1 <= threshold <= 100):
        raise UsageUnavailable("Invalid switcher setting: threshold (a number from 1 to 100)")
    try:
        policy = pick("policy", value.get("policy", DEFAULT_POLICY_NAME), POLICIES)(threshold, SHORTEST_POLL)
    except ValueError as error:
        raise UsageUnavailable(str(error)) from error
    return Settings(homes, threshold, policy)


def credentials(home):
    try:
        data = json.loads((Path(home) / "auth.json").read_text())
        token = data["tokens"]["access_token"]
        claims = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "==="))
        auth = claims["https://api.openai.com/auth"]
        account, expires = auth["chatgpt_account_id"], claims["exp"]
        if (not isinstance(account, str) or not account.strip() or isinstance(expires, bool)
                or not isinstance(expires, (float, int)) or not math.isfinite(expires)):
            raise ValueError('Invalid saved workspace or token lifetime')
        return {"accessToken": token, "chatgptAccountId": account,
                "chatgptPlanType": auth["chatgpt_plan_type"], "expires": expires}
    except (OSError, ValueError, KeyError, IndexError, TypeError, AttributeError) as error:
        raise UsageUnavailable("Saved ChatGPT login cannot be read") from error


class RegistrationMismatch(UsageUnavailable):
    pass


def registered_accounts(homes, runtime_dir, previous_state=None, *, registration=None):
    directory = Path(runtime_dir)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / 'profile-bindings.json'
    with (directory / 'profile-bindings.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        bindings = read_checkpoint(path)
        if not all(isinstance(value, str) and value for value in bindings.values()):
            raise UsageUnavailable('Invalid saved workspace registration')
        original = dict(bindings)
        if registration is not None:
            name, expected = registration
            if credentials(homes[name])['chatgptAccountId'] != expected:
                raise RegistrationMismatch('Saved workspace changed after registration was requested')
            bindings[name] = expected
        for name, home in homes.items():
            if name in bindings:
                continue
            if previous_state is None:
                previous_state = load(directory / 'account-switcher.json')
            previous = load(directory / f'profile-registration-{name}.json')
            if not previous:
                previous = load(directory / 'profile-registration.json')
            registered = previous_state.get('registration_requests', {}).get(name)
            if registered is None and not previous_state.get('registration_error'):
                registered = previous_state.get('registration_at')
            if (previous.get('profile') == name and previous.get('account_id')
                    and previous.get('requested_at') is not None
                    and previous.get('requested_at') == registered
                    and name not in previous_state.get('registration_errors', {})):
                bindings[name] = previous['account_id']
            else:
                try:
                    bindings[name] = credentials(home)['chatgptAccountId']
                except UsageUnavailable:
                    continue
        if bindings != original:
            save(bindings, path, durable=True)
        return bindings


class Profile:
    def __init__(self, name, home, binary=BINARY, *, bindings_dir=None, account_id=None):
        self.name, self.home, self.binary = name, home, binary
        self.bindings_dir = bindings_dir
        self.account_id = account_id
        if bindings_dir is None:
            try:
                self.account_id = credentials(home)["chatgptAccountId"]
            except UsageUnavailable:
                pass
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
                raise RegistrationMismatch('Saved workspace changed after registration was requested')
            if self.bindings_dir is not None:
                registered_accounts({self.name: self.home}, self.bindings_dir,
                                    registration=(self.name, current))
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
                self.account_id = (value['chatgptAccountId'] if self.bindings_dir is None else
                                   registered_accounts({self.name: self.home}, self.bindings_dir).get(self.name))
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
            client, account_id = self._connect(), self.account_id
        try:
            result = client.request("account/rateLimits/read", timeout=20)
            with self.lock:
                if self.client is not client or self.account_id != account_id or result.get("accountId") != account_id:
                    raise UsageUnavailable(f"The {self.name} usage belongs to another workspace")
            return snapshot(result)
        except Exception:
            with self.lock:
                if self.client is client:
                    self._disconnect()
            raise

    def close(self):
        with self.lock:
            self._disconnect()

    def _disconnect(self):
        if self.client:
            self.client.close()
            self.client = None
