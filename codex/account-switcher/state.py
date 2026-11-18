"""Persist only usage metadata, never credentials or conversation contents."""

import json
import math
import os
from pathlib import Path
import tempfile
import time

from policy import poll_seconds, utilization


RUNTIME = Path.home() / ".codex-auto"
STATE_FILE = RUNTIME / "account-switcher.json"


def preference():
    value = load(RUNTIME / "preference.json")
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
    return {"observed_at": observed_at, "used_percent": used,
            "plan_type": limits.get("planType"), "windows": windows}


def record(previous, current):
    previous = previous or {}
    for name, window in current["windows"].items():
        old = previous.get("windows", {}).get(name, {})
        if old.get("last_reset_confirmed_at"):
            window["last_reset_confirmed_at"] = old["last_reset_confirmed_at"]
        if old.get("previous_resets_at"):
            window["previous_resets_at"] = old["previous_resets_at"]
        before, after = old.get("resets_at"), window.get("resets_at")
        if before and after and before <= current["observed_at"] and after > before:
            window["last_reset_confirmed_at"] = current["observed_at"]
            window["previous_resets_at"] = before
    return current


def poll_delay(accounts, active=None, now=None):
    now = time.time() if now is None else now
    future = [window["resets_at"] - now + 1
              for account in accounts.values()
              for window in account.get("windows", {}).values()
              if window.get("resets_at") and window["resets_at"] > now]
    interval = poll_seconds((accounts.get(active) or {}).get("used_percent"))
    return max(1, min([interval, *future]))


def load(path=STATE_FILE):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}


def save(value, path=STATE_FILE):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".usage-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
