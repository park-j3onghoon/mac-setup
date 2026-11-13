"""Account priority and quota rules; no credentials or operating system access."""

from dataclasses import dataclass
import math


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

    def available(self, now: float, threshold: float, max_age: float) -> bool:
        if not self.windows or not 0 <= now - self.checked_at <= max_age:
            return False
        return all(
            w.percent is not None and w.percent < threshold
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
    """The primary always wins when freshly verified below every quota line."""
    for email, reason in ((primary, 'primary_available'),
                          (fallback, 'fallback_available')):
        reading = readings.get(email)
        if reading is not None and reading.available(now, threshold, max_age):
            return Decision(email, reason)
    return Decision(None, 'no_verified_capacity')
