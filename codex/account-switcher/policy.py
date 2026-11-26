"""Read Codex plan limits as switchcore usage and select a saved profile from them."""

import math
import time

from switchcore.policy import StrictPriorityPolicy
from switchcore.quota import Usage, Window


DEFAULT_THRESHOLD = 90
SHORTEST_POLL = 60
DEFAULT_POLICY = StrictPriorityPolicy(DEFAULT_THRESHOLD, SHORTEST_POLL)


class UsageUnavailable(ValueError):
    pass


def utilization(result):
    if result.get("ordinaryUsageAllowed") is False:
        return 100.0
    by_id = result.get("rateLimitsByLimitId") or {}
    if not isinstance(by_id, dict):
        raise UsageUnavailable("The usage response has an invalid limit map")
    limits = by_id.get("codex")
    limits = limits or result.get("rateLimits") or {}
    if not isinstance(limits, dict):
        raise UsageUnavailable("The usage response has invalid limits")
    if limits.get('limitId') not in (None, 'codex'):
        raise UsageUnavailable("No Codex plan limits were reported")
    if limits.get("spendControlReached") or limits.get("rateLimitReachedType"):
        return 100.0
    values = []
    for key in ("primary", "secondary"):
        window = limits.get(key)
        if window is None:
            continue
        if not isinstance(window, dict):
            raise UsageUnavailable("The usage window is invalid")
        value = window.get("usedPercent")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise UsageUnavailable("Usage percentage is missing or invalid")
        if not math.isfinite(value) or not 0 <= value <= 100:
            raise UsageUnavailable("Usage percentage is outside 0–100")
        values.append(float(value))
    if not values:
        raise UsageUnavailable("No included plan usage window was reported")
    return max(values)


def to_usage(used_percent, checked_at):
    """One window holding a profile's used percentage, which state.record keeps at 100 while the
    workspace blocks ordinary usage or reached spend control."""
    return Usage(checked_at, (Window("codex", used_percent, None),))


def is_available(account, policy, now):
    """Whether a profile with this state.snapshot may be switched to under the rule."""
    return policy.available(to_usage(account["used_percent"], account["observed_at"]), now)


def choose(usages, preferred="company", policy=DEFAULT_POLICY, now=None):
    """The profile to use from fresh used percentages; UsageUnavailable when the rule decides none."""
    if preferred not in ("company", "personal"):
        raise UsageUnavailable("Unknown preferred account")
    order = ("personal", "company") if preferred == "personal" else ("company", "personal")
    now = time.time() if now is None else now
    readings = {name: to_usage(used, now) for name, used in usages.items()}
    target = policy.choose(order, None, readings, now).target
    if target is None:
        missing = next((name for name in order if name not in usages), None)
        raise UsageUnavailable(f"Cannot verify {missing} plan usage" if missing else
                               "No profile has plan capacity")
    return target
