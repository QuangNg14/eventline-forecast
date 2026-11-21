"""Read a Rust replay and query occurrence-hour totals by first receipt time."""

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

HOUR = 3600
DAY = 24 * HOUR
EVENT_SCHEMA = "eventline-v1"
FEATURE_SCHEMA = "hourly-asof-v1"
FEATURES = ("lag_1h", "mean_6h", "mean_24h", "lag_24h", "utc_hour", "hours_after_noon", "weekend")


@dataclass(frozen=True)
class History:
    start: int
    end: int
    lateness: int
    through: int
    buckets: dict[int, list[tuple[int, int]]]

    @classmethod
    def load(cls, path: Path) -> "History":
        with path.open(encoding="ascii") as f:
            version, start, end, lateness, through = f.readline().rstrip().split(",")
            if version != EVENT_SCHEMA or f.readline().rstrip() != "event_id,occurred_at,available_at,units":
                raise ValueError("expected an eventline-v1 canonical replay")
            s, e, delay, watermark = map(int, (start, end, lateness, through))
            if not (0 <= s < e and s % HOUR == e % HOUR == 0 and delay >= 0 and watermark >= s):
                raise ValueError("invalid observation window")
            buckets: dict[int, list[tuple[int, int]]] = defaultdict(list)
            seen: set[str] = set()
            previous = (-1, -1, "")
            for line_number, line in enumerate(f, 3):
                event_id, *fields = line.rstrip().split(",")
                occurred, available, units = map(int, fields)
                key = (available, occurred, event_id)
                if (key <= previous or event_id in seen or not s <= occurred < e
                        or not occurred <= available <= min(occurred + delay, watermark)
                        or not 1 <= units < 2**32):
                    raise ValueError(f"line {line_number}: inconsistent replay; run Rust replay first")
                seen.add(event_id)
                previous = key
                buckets[occurred // HOUR * HOUR].append((available, units))
        return cls(s, e, delay, watermark, dict(buckets))

    def _known_units(self, hour: int, as_of: int) -> int:
        return sum(units for received, units in self.buckets.get(hour, ()) if received <= as_of)

    def features(self, origin: int) -> tuple[float, ...]:
        if origin % HOUR or not self.start + DAY <= origin <= min(self.end, self.through):
            raise ValueError("origin needs a whole UTC hour and 24 hours of observed history")
        lags = [self._known_units(origin - k * HOUR, origin) for k in range(1, 25)]
        hour = origin // HOUR % 24
        weekday = (origin // DAY + 3) % 7  # Unix epoch was a Thursday.
        return (lags[0], sum(lags[:6]) / 6, sum(lags) / 24, lags[23],
                hour, max(0, hour - 12), int(weekday >= 5))

    def label(self, origin: int, as_of: int) -> int:
        end = origin + HOUR
        if (origin % HOUR or origin < self.start or end > self.end
                or not end + self.lateness <= as_of <= self.through):
            raise ValueError("target hour is outside coverage or not final as of this time")
        return self._known_units(origin, as_of)

    def mature_origins(self, first: int, as_of: int) -> range:
        if first % HOUR or not self.start <= as_of <= self.through:
            raise ValueError("invalid origin range or snapshot cutoff")
        last = min(self.end, as_of - self.lateness) - HOUR
        return range(max(first, self.start + DAY), last + 1, HOUR)
