import csv
import io
import json
import unittest
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from forecast.history import DAY, HOUR, History
from forecast.seoul import FIRST, backfill, export_events, midnight


def archive(rows: list[list[str]]) -> str:
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["Date", "Hour", "Rented Bike Count"])
    writer.writerows(rows)
    return stream.getvalue()


class PublicSeriesTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.end = FIRST + timedelta(days=2)
        self.rows = [[(FIRST + timedelta(days=d)).strftime("%d/%m/%Y"), str(h), str(h)]
                     for d in range(2) for h in range(24)]

    def test_partition_backfill_is_order_independent_and_preserves_zero(self) -> None:
        backfill(archive(self.rows), self.root, FIRST, self.end)
        events = export_events(self.root, FIRST, self.end)
        original = events.read_bytes()
        files = sorted((self.root / "days").iterdir())
        before = [f.read_bytes() for f in files]
        stats = backfill(archive(self.rows[::-1] + [self.rows[0]]), self.root, FIRST, FIRST + timedelta(days=1))
        self.assertEqual(stats["duplicate_rows"], 1)
        self.assertGreater(stats["out_of_order_rows"], 0)
        self.assertEqual(before, [f.read_bytes() for f in files])
        self.assertEqual(original, export_events(self.root, FIRST, self.end).read_bytes())
        hist = History.load(events)
        t = midnight(FIRST) + DAY
        self.assertEqual(hist.features(t)[:4], (23, 20.5, 11.5, 0))
        self.assertEqual(hist.label(t, hist.through), 0)
        self.assertEqual(hist._known_units(t-HOUR, t-1), 0)
        self.assertEqual(hist._known_units(t-HOUR, t), 23)

    def test_quarantine_rejects_bad_rows_gaps_conflicts_and_stale_backfill(self) -> None:
        backfill(archive(self.rows), self.root, FIRST, self.end)
        path = self.root / "days" / f"{FIRST}.csv"
        before = path.read_bytes()
        invalid = self.rows[:-1] + [["bad", "1", "3"], ["01/12/2017", "99", "2"],
                                   ["01/12/2017", "2", "-1"], ["01/12/2017", "2", "7"]]
        with self.assertRaisesRegex(ValueError, "quarantine"):
            backfill(archive(invalid), self.root, FIRST, self.end)
        reasons = {json.loads(line)["reason"] for line in (self.root / "quarantine.jsonl").read_text().splitlines()}
        self.assertEqual(reasons, {"invalid local date", "hour outside 0..23 or not an integer",
                                   "count outside uint32 or not an integer", "conflicting duplicate hour",
                                   "missing hours", "stale archive coverage"})
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "source columns"):
            backfill("Date,Hour,Hour\n", self.root, FIRST, self.end)
