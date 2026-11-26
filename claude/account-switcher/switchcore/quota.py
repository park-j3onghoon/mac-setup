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
