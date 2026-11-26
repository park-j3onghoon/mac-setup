"""Usage readings and their quota windows; no rules, credentials or operating system access."""

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
