"""Choose a saved Codex profile from freshly reported plan limits."""

import math


THRESHOLD = 90


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


def choose(usages, threshold=THRESHOLD):
    for name in ("company", "personal"):
        if name not in usages:
            raise UsageUnavailable(f"Cannot verify {name} plan usage")
        value = usages[name]
        if value < threshold:
            return name
    return "company"
