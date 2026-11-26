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
    """A rule a switcher asks; a local setting picks one of switchcore/choices.py by name."""

    def choose(self, order: Sequence[str], active: str | None, readings: Mapping[str, Usage],
               now: float) -> Decision:
        """The account to use now. order lists the account names with the preferred one first;
        readings holds the accounts read in this cycle."""

    def available(self, usage: Usage, now: float) -> bool:
        """Whether an account with this reading may be switched to; asked again right before."""

    def poll_seconds(self, usage: Usage | None) -> float:
        """Seconds until the next usage lookup, from the active account's last reading."""


class PriorityPolicy:
    """The first account a fresh reading shows below the threshold on every window.

    Without a verified reading of the first account the active account stays: the Claude usage
    endpoint answers HTTP 429 to about half the lookups, and reading that as a reached limit
    switched accounts every minute or two (36 switches, 2026-11-13 16:47~17:38).
    """

    def __init__(self, threshold, shortest_poll, max_age=90):
        self.threshold, self.shortest_poll, self.max_age = threshold, shortest_poll, max_age

    def choose(self, order, active, readings, now):
        primary, *fallbacks = order
        reading = readings.get(primary)
        known_block = (reading is not None and 0 <= now - reading.checked_at <= self.max_age and
                       any((w.blocked or (w.percent is not None and w.percent >= self.threshold))
                           and (w.resets_at is None or w.resets_at > now) for w in reading.windows))
        if reading is None or (not reading.verified(now, self.max_age) and not known_block):
            return Decision(active, 'primary_unverified')
        if self.available(reading, now):
            return Decision(primary, 'primary_available')
        for fallback in fallbacks:
            reading = readings.get(fallback)
            if reading is not None and self.available(reading, now):
                return Decision(fallback, 'fallback_available')
        return Decision(None, 'no_verified_capacity')

    def available(self, usage, now):
        return usage.available(now, self.threshold, self.max_age)

    def poll_seconds(self, usage):
        return _tiered_poll_seconds(_highest_percent(usage), self.threshold, self.shortest_poll)


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
        return _tiered_poll_seconds(_highest_percent(usage), self.threshold, self.shortest_poll)


def _highest_percent(usage):
    if usage is None:
        return None
    return max((w.percent for w in usage.windows if w.percent is not None), default=None)


def _tiered_poll_seconds(highest, threshold, shortest):
    """Look up usage less often the further the active account is from the threshold."""
    if highest is None:
        return shortest
    headroom = threshold - highest
    return next((max(seconds, shortest) for floor, seconds in POLL_TIERS if headroom >= floor), shortest)
