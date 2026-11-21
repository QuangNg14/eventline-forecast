import unittest

from forecast.history import DAY, HOUR, History
from forecast.model import ridge


class TimeContractTests(unittest.TestCase):
    def test_known_lag_and_rolling_at_receipt_boundary(self) -> None:
        t = DAY
        history = History(0, 2 * DAY, 2 * HOUR, 2 * DAY, {
            0: [(1, 11)], t - 2 * HOUR: [(t - 1, 7)],
            t - HOUR: [(t, 5), (t + 1, 13)], t: [(t, 17)],
        })
        self.assertEqual(history.features(t)[:4], (5, 12 / 6, 23 / 24, 11))
        self.assertEqual(history.features(t + HOUR)[:2], (17, (17 + 5 + 13 + 7) / 6))
        for invalid in (t - HOUR, t + 1, history.end + HOUR):
            with self.assertRaises(ValueError):
                history.features(invalid)

    def test_target_requires_coverage_and_maturity_even_if_empty(self) -> None:
        t = DAY
        h = History(0, 2 * DAY, 2 * HOUR, 2 * DAY, {
            t: [(t, 4), (t + 3 * HOUR - 1, 9)], t + HOUR: [(t + HOUR, 11)],
        })
        self.assertEqual(h.label(t, t + 3 * HOUR), 13)
        self.assertEqual(h.label(t + 2 * HOUR, h.through), 0)
        self.assertEqual(h.mature_origins(t, t + 3 * HOUR)[:], range(t, t + 1, HOUR))
        for origin, as_of in [(t, t + 3 * HOUR - 1), (h.end - HOUR, h.through),
                              (h.end, h.through), (t, h.through + 1)]:
            with self.assertRaises(ValueError):
                h.label(origin, as_of)
        # Even waiting past the occurrence window cannot turn a future hour into a zero label.
        drained = History(h.start, h.end, h.lateness, h.end + DAY, {})
        self.assertEqual(drained.mature_origins(t, drained.through)[-1], h.end - HOUR)
        with self.assertRaises(ValueError):
            drained.label(h.end, drained.through)

    def test_ridge_matches_hand_solved_fit(self) -> None:
        intercept, (slope,) = ridge([(0,), (1,), (2,)], [1, 3, 5])
        self.assertAlmostEqual(slope, 4 / 3)
        self.assertAlmostEqual(intercept, 5 / 3)
