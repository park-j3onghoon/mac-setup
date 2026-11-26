"""Persist only usage metadata, never credentials or conversation contents."""

import json
import fcntl
import math
import os
from pathlib import Path
import tempfile
import time

from policy import DEFAULT_POLICY, UsageUnavailable, to_usage, utilization
from switchcore.policy import LONGEST_POLL_SECONDS


RUNTIME = Path.home() / ".codex-auto"
STATE_FILE = RUNTIME / "account-switcher.json"
DRAIN_REPORT = RUNTIME / "runtime-draining.json"
_cache = {}


def changed_file(path):
    try:
        info = path.stat()
    except OSError:
        return {}
    identity = (info.st_ino, info.st_mtime_ns, info.st_size)
    if path not in _cache or _cache[path][0] != identity:
        try:
            value = json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
        _cache[path] = (identity, value if isinstance(value, dict) else {})
    return _cache[path][1]


def preference():
    value = changed_file(RUNTIME / "preference.json")
    return value if isinstance(value, dict) and value.get("preferred") in ("company", "personal") else {}


def snapshot(result, observed_at=None):
    observed_at = time.time() if observed_at is None else observed_at
    used = utilization(result)
    limits = (result.get("rateLimitsByLimitId") or {}).get("codex")
    limits = limits or result.get("rateLimits") or {}
    windows = {}
    for name in ("primary", "secondary"):
        window = limits.get(name)
        if not window:
            continue
        resets = window.get("resetsAt")
        if isinstance(resets, bool) or not isinstance(resets, (int, float)) or not math.isfinite(resets):
            resets = None
        windows[name] = {
            "used_percent": window["usedPercent"], "resets_at": resets,
            "window_minutes": window.get("windowDurationMins"),
        }
    return {"observed_at": observed_at, "used_percent": used, "account_id": result.get('accountId'),
            "ordinary_usage_allowed": result.get("ordinaryUsageAllowed"),
            "spend_control_reached": limits.get("spendControlReached"),
            "plan_type": limits.get("planType"), "windows": windows}


def record(previous, current):
    previous = previous or {}
    for field, blocked in (('ordinary_usage_allowed', False), ('spend_control_reached', True)):
        observed = field + '_observed_at'
        before = previous.get(observed, previous.get('observed_at', 0))
        after = current.get(observed, current.get('observed_at', 0))
        if previous.get(field) is not None and current.get(field) is None:
            current[field], current[observed] = previous[field], before
        elif current.get(field) is not None:
            current[observed] = after
        if current.get(field) is blocked:
            current['used_percent'] = 100.0
    history = {**previous.get('window_history', {}), **previous.get('windows', {})}
    for name, window in current["windows"].items():
        old = history.pop(name, {})
        if old.get("last_reset_confirmed_at"):
            window["last_reset_confirmed_at"] = old["last_reset_confirmed_at"]
        if old.get("previous_resets_at"):
            window["previous_resets_at"] = old["previous_resets_at"]
        before, after = old.get("resets_at"), window.get("resets_at")
        if before and after and before <= current["observed_at"] and after > before:
            window["last_reset_confirmed_at"] = current["observed_at"]
            window["previous_resets_at"] = before
    if history:
        current['window_history'] = history
    return current


def known_windows(account):
    return {**account.get('window_history', {}), **account.get('windows', {})}.values()


def usage_history(account_id, supervisor_sample, direct_sample):
    """Join observations only for this registration, retaining the last explicit permission per field."""
    saved = supervisor_sample or {}
    if saved.get('account_id') not in (None, account_id):
        saved = {}
    if direct_sample.get('account_id') != account_id or not direct_sample:
        return saved
    if not saved:
        return direct_sample
    before, after = sorted((saved, direct_sample), key=lambda s: s.get('observed_at', 0))
    after = dict(after, windows={k: dict(v) for k, v in after.get('windows', {}).items()})
    for field, blocked in (('ordinary_usage_allowed', False), ('spend_control_reached', True)):
        key = field + '_observed_at'
        old_time, new_time = before.get(key, before.get('observed_at', 0)), after.get(key, after.get('observed_at', 0))
        if before.get(field) is not None and (old_time > new_time or old_time == new_time and before[field] is blocked):
            after[field] = None
    return record(before, after)


def poll_delay(accounts, active=None, now=None, *, history=None, policy=DEFAULT_POLICY):
    now = time.time() if now is None else now
    future = [window["resets_at"] - now + 1
              for account in (accounts if history is None else history).values()
              for window in known_windows(account)
              if window.get("resets_at") and window["resets_at"] > now]
    account = accounts.get(active)
    usage = to_usage(account["used_percent"], account["observed_at"]) if account else None
    interval = min(policy.poll_seconds(usage), LONGEST_POLL_SECONDS)
    return max(1, min([interval, *future]))


def load(path=STATE_FILE):
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def read_checkpoint(path):
    """A missing first-run checkpoint is empty. An unreadable existing checkpoint is uncertain."""
    try:
        value = json.loads(Path(path).read_text())
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as error:
        raise UsageUnavailable(f"Cannot read checkpoint {Path(path).name}") from error
    if not isinstance(value, dict):
        raise UsageUnavailable(f"Invalid checkpoint {Path(path).name}")
    return value


def save(value, path=STATE_FILE, *, durable=False):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}-{os.getpid()}-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            if durable and hasattr(fcntl, 'F_FULLFSYNC'):
                fcntl.fcntl(stream.fileno(), fcntl.F_FULLFSYNC)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
            if durable and hasattr(fcntl, 'F_FULLFSYNC'):
                fcntl.fcntl(directory, fcntl.F_FULLFSYNC)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
