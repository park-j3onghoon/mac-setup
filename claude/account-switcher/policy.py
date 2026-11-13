"""Account priority and quota rules; no credentials or operating system access."""

from dataclasses import dataclass
import math


# (headroom below the threshold in percentage points, seconds until the next usage lookup).
# The longest stays under the 10 minutes the workspace dashboard trusts runtime.json
# (its usage.py SWITCHER_FRESH_SECONDS); past that it queries usage itself.
POLL_TIERS = ((30, 540), (15, 300), (5, 120))


def poll_seconds(highest_percent: float | None, threshold: float, shortest: float) -> float:
    """Look up usage less often the further the active account is from the threshold."""
    if highest_percent is None:
        return shortest
    headroom = threshold - highest_percent
    return next((seconds for floor, seconds in POLL_TIERS if headroom >= floor), shortest)


@dataclass(frozen=True)
class Window:
    name: str
    percent: float | None
    resets_at: float | None
    blocked: bool = False

    def __post_init__(self):
        if self.percent is not None and (
            isinstance(self.percent, bool)
            or not isinstance(self.percent, (int, float))
            or not math.isfinite(self.percent)
            or self.percent < 0
        ):
            raise ValueError('Invalid quota percentage')
        if self.resets_at is not None and (
            isinstance(self.resets_at, bool)
            or not isinstance(self.resets_at, (int, float))
            or not math.isfinite(self.resets_at)
            or self.resets_at <= 0
        ):
            raise ValueError('Invalid quota reset timestamp')


@dataclass(frozen=True)
class Usage:
    checked_at: float
    windows: tuple[Window, ...]

    def verified(self, now: float, max_age: float) -> bool:
        """A fresh reading that reports every window's percentage."""
        return (bool(self.windows) and 0 <= now - self.checked_at <= max_age
                and all(w.percent is not None for w in self.windows))

    def available(self, now: float, threshold: float, max_age: float) -> bool:
        return self.verified(now, max_age) and all(
            w.percent < threshold
            and not w.blocked
            and (w.resets_at is None or w.resets_at > now)
            for w in self.windows
        )

    def next_reset(self, now: float) -> float | None:
        return min((w.resets_at for w in self.windows
                    if w.resets_at is not None and w.resets_at > now), default=None)


@dataclass(frozen=True)
class Decision:
    target: str | None
    reason: str


def choose_account(active: str, primary: str, fallback: str,
                   readings: dict[str, Usage], now: float,
                   threshold: float, max_age: float) -> Decision:
    """The primary always wins when freshly verified below every quota line.

    Without a verified primary reading the active account stays: the usage endpoint answers
    HTTP 429 to about half the lookups, and reading that as a reached limit switched accounts
    every minute or two (36 switches, 2026-11-13 16:47~17:38).
    """
    reading = readings.get(primary)
    if reading is None or not reading.verified(now, max_age):
        return Decision(active, 'primary_unverified')
    if reading.available(now, threshold, max_age):
        return Decision(primary, 'primary_available')
    reading = readings.get(fallback)
    if reading is not None and reading.available(now, threshold, max_age):
        return Decision(fallback, 'fallback_available')
    return Decision(None, 'no_verified_capacity')
