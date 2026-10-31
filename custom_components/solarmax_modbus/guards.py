"""Counter guards: keep energy counters clean despite bad Modbus reads.

Home Assistant's Energy dashboard treats any big drop of a total_increasing
sensor as a meter reset and then counts the whole total again when the value
returns. One bad read (a zero, a garbage value) is enough to add thousands of
kWh to a day. These guards sit between the raw register value and the sensor:

* a single implausible reading (drop, zero, or a jump bigger than the inverter
  could physically produce in the elapsed time) is ignored;
* a change that persists (CONFIRM_READINGS readings over CONFIRM_SECONDS) is
  real: a lifetime counter then carries on from where it was ("rebase"), so
  the published total never dips and nothing is counted twice;
* if readings come back to the previous track after a temporary fault, the
  energy produced in between is still counted.

Pure Python (no Home Assistant imports) so every scenario is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import logging

_LOGGER = logging.getLogger(__name__)

CONFIRM_READINGS = 6
CONFIRM_SECONDS = 60
FRESH_READINGS = 3  # consistent readings needed before trusting a brand-new counter


@dataclass
class Track:
    """One continuous run of raw readings: published = raw + offset."""

    offset: float
    raw: float
    ts: float

    def as_list(self) -> list[float]:
        return [self.offset, self.raw, self.ts]

    @classmethod
    def from_list(cls, value) -> Track | None:
        try:
            offset, raw, ts = (float(v) for v in value)
        except (TypeError, ValueError):
            return None
        return cls(offset, raw, ts)


class _Base:
    def __init__(self, name: str, max_rate_per_hour: float) -> None:
        self.name = name
        self.max_rate = max_rate_per_hour
        self.pending: list[tuple[float, float]] = []
        self.rejected = 0
        self.last_event: str | None = None

    @staticmethod
    def _eps(ref: float) -> float:
        return max(0.02, abs(ref) * 2e-6)

    def _plausible(self, value: float, ts: float, ref_value: float, ref_ts: float) -> bool:
        """Not lower than ref and not higher than physically possible since ref."""
        eps = self._eps(ref_value)
        if value < ref_value - eps:
            return False
        hours = max(0.0, ts - ref_ts) / 3600
        return value <= ref_value + self.max_rate * (hours + 0.05) + eps

    def _hold(self, value: float, ts: float) -> bool:
        """Record an anomalous reading. True once it has persisted long enough."""
        self.rejected += 1
        if self.pending and not self._plausible(value, ts, *self.pending[-1]):
            self.pending = []  # readings are not consistent with each other: start over
        self.pending.append((value, ts))
        return len(self.pending) >= CONFIRM_READINGS and ts - self.pending[0][1] >= CONFIRM_SECONDS

    def _event(self, text: str) -> None:
        self.last_event = text
        _LOGGER.warning("%s: %s", self.name, text)


class LifetimeGuard(_Base):
    """For counters that must never go down (total import, PV total, ...)."""

    def __init__(self, name: str, max_rate_per_hour: float) -> None:
        super().__init__(name, max_rate_per_hour)
        self.cur: Track | None = None
        self.prev: Track | None = None
        self.published: float | None = None
        self.rebased = 0
        self._fresh: list[tuple[float, float]] = []

    # --------------------------------------------------------- persistence
    def seed(self, published: float, ts: float) -> None:
        """Continue from a value restored from an older version / YAML sensor."""
        if published > 0:
            self.published = published
            self.cur = Track(0.0, published, ts)

    def to_dict(self) -> dict:
        return {
            "published": self.published,
            "cur": self.cur.as_list() if self.cur else None,
            "prev": self.prev.as_list() if self.prev else None,
            "rejected": self.rejected,
            "rebased": self.rebased,
        }

    def load(self, data: dict) -> bool:
        cur = Track.from_list(data.get("cur"))
        published = data.get("published")
        if cur is None or not isinstance(published, (int, float)):
            return False
        self.cur, self.published = cur, float(published)
        self.prev = Track.from_list(data.get("prev"))
        self.rejected = int(data.get("rejected") or 0)
        self.rebased = int(data.get("rebased") or 0)
        return True

    # ------------------------------------------------------------- update
    def update(self, raw: float | None, ts: float) -> float | None:
        if raw is None:
            return None
        if self.cur is None:
            return self._start(raw, ts)
        if self._plausible(raw, ts, self.cur.raw, self.cur.ts):
            return self._accept(self.cur, raw, ts)
        if self.prev is not None and self._plausible(raw, ts, self.prev.raw, self.prev.ts):
            self.cur, self.prev = self.prev, None
            self._event(f"readings back on the previous track at {raw}; energy in between is counted")
            return self._accept(self.cur, raw, ts)
        if self._hold(raw, ts):
            # The new track starts at the first anomalous reading, so energy
            # counted during the confirmation window is not lost.
            first = self.pending[0][0]
            self.prev = self.cur
            self.cur = Track(self.published - first, first, self.pending[0][1])
            self.rebased += 1
            self._event(
                f"counter changed from {self.prev.raw} to {first} and stayed there; "
                f"continuing from {self.published} without a dip"
            )
            return self._accept(self.cur, raw, ts)
        return self.published

    def _start(self, raw: float, ts: float) -> float | None:
        if raw <= 0:
            return None
        if self._fresh and not self._plausible(raw, ts, *self._fresh[-1]):
            self._fresh = []
        self._fresh.append((raw, ts))
        if len(self._fresh) < FRESH_READINGS:
            return None
        self._fresh = []
        self.cur = Track(0.0, raw, ts)
        self.published = raw
        return raw

    def _accept(self, track: Track, raw: float, ts: float) -> float:
        track.raw, track.ts = raw, ts
        value = round(raw + track.offset, 6)
        self.published = value if self.published is None else max(self.published, value)
        self.pending = []
        return self.published


class DailyGuard(_Base):
    """For counters that reset once a day (daily import, PV today, ...)."""

    def __init__(self, name: str, max_rate_per_hour: float) -> None:
        super().__init__(name, max_rate_per_hour)
        self.value: float | None = None
        self.ts = 0.0

    def to_dict(self) -> dict:
        return {"value": self.value, "ts": self.ts, "rejected": self.rejected}

    def load(self, data: dict) -> bool:
        if not isinstance(data.get("value"), (int, float)):
            return False
        self.value, self.ts = float(data["value"]), float(data.get("ts") or 0)
        self.rejected = int(data.get("rejected") or 0)
        return True

    def update(self, raw: float | None, ts: float, local: datetime) -> float | None:
        if raw is None:
            return None
        if self.value is None:
            return self._accept(raw, ts)
        if self._plausible(raw, ts, self.value, self.ts):
            return self._accept(raw, ts)
        if raw < self.value and self._is_reset(raw, local):
            return self._accept(raw, ts)
        if self._hold(raw, ts):
            self._event(f"value changed from {self.value} to {raw} and stayed there; accepting it")
            return self._accept(raw, ts)
        return self.value

    def _is_reset(self, raw: float, local: datetime) -> bool:
        """A midnight reset: close to midnight and small enough for the time since."""
        minutes = local.hour * 60 + local.minute
        since_midnight_h = minutes / 60 if minutes < 12 * 60 else 0.0
        near_midnight = minutes >= 23 * 60 + 55 or minutes <= 15
        return near_midnight and raw <= self.max_rate * (since_midnight_h + 0.05) + 0.1

    def _accept(self, raw: float, ts: float) -> float:
        self.value, self.ts = raw, ts
        self.pending = []
        return raw
