"""Which account a switcher uses and when it looks at usage again; no credentials or I/O."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .quota import Usage


# Readers trust a switcher's status file for 10 minutes (the workspace dashboard's usage.py
# SWITCHER_FRESH_SECONDS; past that it queries usage itself) and a restart helper waits 900 seconds
# for a switch (refresh.py SWITCH_TIMEOUT_SECONDS), so no lookup interval may be longer.
LONGEST_POLL_SECONDS = 540
# (headroom below the threshold in percentage points, seconds until the next usage lookup).
POLL_TIERS = ((30, LONGEST_POLL_SECONDS), (15, 300), (5, 120))


@dataclass(frozen=True)
class Decision:
    target: str | None
    reason: str


class SwitchPolicy(Protocol):
    """A rule a switcher asks. A local setting picks one by name from POLICIES below, and the
    switcher builds it as cls(threshold, shortest_poll)."""

    def choose(self, order: Sequence[str], active: str | None, readings: Mapping[str, Usage],
               now: float) -> Decision:
        """The account to use now. order lists the account names with the preferred one first;
        readings holds the accounts read in this cycle."""

    def available(self, usage: Usage, now: float) -> bool:
        """Whether an account with this reading may be switched to; asked again right before."""

    def poll_seconds(self, usage: Usage | None) -> float:
        """Seconds until the next usage lookup, from the active account's last reading."""


def poll_interval(policy: SwitchPolicy, usage: Usage | None) -> float:
    """Seconds until the next usage lookup under any rule, never past LONGEST_POLL_SECONDS."""
    return min(policy.poll_seconds(usage), LONGEST_POLL_SECONDS)


class PriorityPolicy:
    """The first account a fresh reading shows below the threshold on every window.

    Without a verified reading of the first account the active account stays: the Claude usage
    endpoint answers HTTP 429 to about half the lookups, and reading that as a reached limit
    switched accounts every minute or two (36 switches, 2026-11-13 16:47~17:38).
    """

    max_age = 90  # seconds a reading stays verified

    def __init__(self, threshold, shortest_poll):
        self.threshold, self.shortest_poll = threshold, shortest_poll

    def choose(self, order, active, readings, now):
        primary, *fallbacks = order
        reading = readings.get(primary)
        known_block = (reading is not None and 0 <= now - reading.checked_at <= self.max_age and
                       any((w.blocked or (w.percent is not None and w.percent >= self.threshold))
                           and (w.resets_at is None or w.resets_at > now) for w in reading.windows))
        if reading is None or (not self.verified(reading, now) and not known_block):
            return Decision(active, 'primary_unverified')
        if self.available(reading, now):
            return Decision(primary, 'primary_available')
        for fallback in fallbacks:
            reading = readings.get(fallback)
            if reading is not None and self.available(reading, now):
                return Decision(fallback, 'fallback_available')
        return Decision(None, 'no_verified_capacity')

    def available(self, usage, now):
        return self.verified(usage, now) and all(
            w.percent < self.threshold and not w.blocked and (w.resets_at is None or w.resets_at > now)
            for w in usage.windows)

    def poll_seconds(self, usage):
        return _tiered_poll_seconds(usage, self.threshold, self.shortest_poll)

    def verified(self, usage, now):
        """A reading from the last max_age seconds that reports every window's percentage."""
        return (bool(usage.windows) and 0 <= now - usage.checked_at <= self.max_age
                and all(w.percent is not None for w in usage.windows))


class StrictPriorityPolicy:
    """The first account in order below the threshold, read in the same cycle.

    A failed lookup of an earlier account decides nothing, so the current login stays; with every
    account at the threshold the preferred one stays the target (the Codex switcher's rule, codex
    README 「전환과 초기화」).
    """

    def __init__(self, threshold, shortest_poll):
        self.threshold, self.shortest_poll = threshold, shortest_poll

    def choose(self, order, active, readings, now):
        for name in order:
            reading = readings.get(name)
            if reading is None:
                return Decision(None, 'unverified')
            if self.available(reading, now):
                return Decision(name, 'available')
        return Decision(order[0], 'all_at_threshold')

    def available(self, usage, now):
        return bool(usage.windows) and all(
            w.percent is not None and w.percent < self.threshold and not w.blocked for w in usage.windows)

    def poll_seconds(self, usage):
        return _tiered_poll_seconds(usage, self.threshold, self.shortest_poll)


def _tiered_poll_seconds(usage, threshold, shortest):
    """Look up usage less often the further the highest window is from the threshold."""
    percents = [w.percent for w in usage.windows if w.percent is not None] if usage is not None else []
    if not percents:
        return shortest
    headroom = threshold - max(percents)
    return next((max(seconds, shortest) for floor, seconds in POLL_TIERS if headroom >= floor), shortest)


POLICIES = {'priority': PriorityPolicy, 'strict-priority': StrictPriorityPolicy}
