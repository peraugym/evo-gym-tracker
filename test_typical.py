#!/usr/bin/env python3
"""Typical curve: binning, all-days fallback, mean ± 2 SD band, and gaps."""
from __future__ import annotations

import statistics
import tempfile
import unittest
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import build_dashboard
import hero
import typical

VIE = ZoneInfo("Europe/Vienna")


def at(day: int, hour: int, minute: int, count: int, month: int = 11) -> hero.Reading:
    # November 2026: Sunday 1, Monday 2, Friday 6, Friday 13, Friday 20.
    return hero.Reading(datetime(2026, month, day, hour, minute, tzinfo=VIE), count)


class SlotBinning(unittest.TestCase):
    def test_slots_cover_open_hours_only(self):
        slots = typical.slot_times()
        self.assertEqual(slots[0], time(6, 0))
        self.assertEqual(slots[-1], time(22, 45))
        self.assertEqual(len(slots), 68)
        self.assertTrue(all(slots[i + 1] > slots[i] for i in range(len(slots) - 1)))

    def test_floors_to_quarter_hour_and_drops_outside_window(self):
        self.assertEqual(typical.slot_of(at(20, 18, 1, 24).when), time(18, 0))
        self.assertEqual(typical.slot_of(at(20, 6, 0, 1).when), time(6, 0))
        self.assertEqual(typical.slot_of(at(20, 22, 44, 1).when), time(22, 30))
        self.assertEqual(typical.slot_of(at(20, 22, 45, 1).when), time(22, 45))
        self.assertIsNone(typical.slot_of(at(20, 5, 59, 1).when))
        self.assertIsNone(typical.slot_of(at(20, 23, 0, 1).when))


class Band(unittest.TestCase):
    def test_mean_and_two_sd_clipped_at_zero(self):
        center, lo, hi = typical._slot_band([10, 20, 30])
        self.assertEqual(center, 20)
        self.assertEqual(lo, 0)   # 20 - 2*10
        self.assertEqual(hi, 40)  # 20 + 2*10
        wide = [1, 2, 30]
        center, lo, hi = typical._slot_band(wide)
        self.assertLess(center - typical.BAND_SD * statistics.stdev(wide), 0)
        self.assertEqual(lo, 0)
        self.assertGreater(hi, center)

    def test_band_needs_three_day_values(self):
        center, lo, hi = typical._slot_band([10, 30])
        self.assertEqual(center, 20)
        self.assertIsNone(lo)
        self.assertIsNone(hi)


class Curve(unittest.TestCase):
    def test_excludes_today_and_other_weekdays(self):
        readings = [
            at(6, 18, 0, 40),    # Friday, past
            at(13, 18, 0, 20),   # Friday, past
            at(12, 18, 0, 99),   # Thursday, ignored
            at(20, 18, 0, 10),   # Friday today, excluded
        ]
        got = typical.curve_for(readings, datetime(2026, 11, 20, tzinfo=VIE).date(), 4)
        self.assertEqual(got["n_days"], 2)
        self.assertEqual(got["label"], "Typical Friday (mean of 2 past Fridays)")
        slot = next(s for s in got["slots"] if s["slot"] == "18:00")
        self.assertEqual(slot["mean"], 30)
        self.assertIsNone(slot["lo"])
        self.assertIsNone(slot["hi"])

    def test_one_value_per_day_then_mean_across_days(self):
        # Two readings in the same slot on one Friday must not outweigh another Friday.
        readings = [
            at(6, 10, 1, 10),
            at(6, 10, 14, 30),   # same 10:00 slot, day value 20
            at(13, 10, 0, 40),
        ]
        got = typical.curve_for(readings, datetime(2026, 11, 20, tzinfo=VIE).date(), 4)
        slot = next(s for s in got["slots"] if s["slot"] == "10:00")
        self.assertEqual(slot["mean"], 30)  # mean of the day values 20 and 40
        self.assertEqual(slot["n"], 2)

    def test_band_appears_for_a_slot_with_three_days(self):
        readings = [
            at(23, 7, 0, 10, month=10),  # Friday
            at(30, 7, 0, 20, month=10),
            at(6, 7, 0, 30),
        ]
        got = typical.curve_for(readings, datetime(2026, 11, 13, tzinfo=VIE).date(), 4)
        slot = next(s for s in got["slots"] if s["slot"] == "07:00")
        self.assertEqual(got["n_days"], 3)
        self.assertEqual(slot["mean"], 20)
        self.assertEqual(slot["lo"], 0)
        self.assertEqual(slot["hi"], 40)

    def test_band_omitted_for_a_slot_with_fewer_than_three_days(self):
        readings = [
            at(23, 7, 0, 10, month=10),
            at(30, 7, 0, 20, month=10),
            at(6, 7, 0, 30),
            at(23, 12, 0, 8, month=10),
            at(30, 12, 0, 12, month=10),
        ]
        got = typical.curve_for(readings, datetime(2026, 11, 13, tzinfo=VIE).date(), 4)
        noon = next(s for s in got["slots"] if s["slot"] == "12:00")
        self.assertEqual(got["n_days"], 3)
        self.assertEqual(noon["n"], 2)
        self.assertEqual(noon["mean"], 10)
        self.assertIsNone(noon["lo"])
        self.assertIsNone(noon["hi"])

    def test_no_curve_when_weekday_has_no_past_days(self):
        readings = [at(20, 9, 0, 16)]  # Friday today only
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        self.assertIsNone(typical.curve_for(readings, today, 4))
        self.assertEqual(typical.curves(readings, today), {})
        self.assertEqual(typical.display_curves(readings, today), {})

    def test_singular_label_for_one_past_day(self):
        readings = [at(13, 8, 0, 22)]
        got = typical.curve_for(readings, datetime(2026, 11, 20, tzinfo=VIE).date(), 4)
        self.assertEqual(got["label"], "Typical Friday (mean of 1 past Friday)")

    def test_falls_back_until_three_weekday_days(self):
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        sparse = [at(13, 18, 0, 10), at(19, 18, 0, 40)]  # one Friday, one Thursday
        shown = typical.display_curves(sparse, today)["Friday"]
        self.assertEqual(shown["source"], "all")
        self.assertEqual(shown["weekday_days"], 1)
        self.assertEqual(shown["label"], "Typical day (all days, mean of 2 days)")
        # Three Fridays switch back, and a Thursday no longer moves the Friday mean.
        fridays = [
            at(23, 18, 0, 10, month=10),
            at(30, 18, 0, 20, month=10),
            at(6, 18, 0, 30),
            at(12, 18, 0, 100),  # Thursday
        ]
        chosen = typical.display_curves(fridays, today)["Friday"]
        self.assertEqual(chosen["source"], "weekday")
        self.assertEqual(chosen["weekday_days"], 3)
        slot = next(s for s in chosen["slots"] if s["slot"] == "18:00")
        self.assertEqual(slot["mean"], 20)
        self.assertEqual(chosen["label"], "Typical Friday (mean of 3 past Fridays)")


class Gaps(unittest.TestCase):
    def test_interpolates_up_to_two_slots_and_breaks_longer_gaps(self):
        short = typical.interpolate_slots([
            {"slot": "10:00", "n": 3, "mean": 10, "lo": 4, "hi": 16},
            {"slot": "10:45", "n": 3, "mean": 40, "lo": 30, "hi": 50},
        ])
        labels = [s["slot"] for s in short]
        self.assertEqual(labels, ["10:00", "10:15", "10:30", "10:45"])
        filled = next(s for s in short if s["slot"] == "10:15")
        self.assertTrue(filled["interpolated"])
        self.assertEqual(filled["mean"], 20)
        self.assertEqual(len(typical.drawable_runs(short)), 1)
        long = typical.interpolate_slots([
            {"slot": "10:00", "n": 1, "mean": 10, "lo": None, "hi": None},
            {"slot": "11:00", "n": 1, "mean": 40, "lo": None, "hi": None},
        ])
        self.assertEqual([s["slot"] for s in long], ["10:00", "11:00"])
        self.assertEqual(typical.drawable_runs(long), [])

    def test_status_uses_a_nearby_interpolated_slot(self):
        readings = [at(13, 18, 0, 10), at(13, 18, 45, 40), at(20, 18, 15, 16)]
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        got = typical.payload(readings, today)
        self.assertEqual(got["now"]["slot"], "18:15")
        self.assertEqual(got["now"]["typical"], 20)
        self.assertIn("vs typical", got["now"]["line"])


class CompareNow(unittest.TestCase):
    def test_inside_band_is_about_usual_and_outside_is_way(self):
        # 18, 20, 22 → mean 20, sd 2, band 16–24.
        readings = [
            at(23, 18, 0, 18, month=10),
            at(30, 18, 0, 20, month=10),
            at(6, 18, 0, 22),
        ]
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        curve = typical.curve_for(readings, today, 4)
        inside = typical.compare_now(curve, at(20, 18, 1, 21), today)
        above = typical.compare_now(curve, at(20, 18, 1, 25), today)
        below = typical.compare_now(curve, at(20, 18, 1, 15), today)
        self.assertEqual(inside["typical"], 20)
        self.assertEqual(inside["category"], "about usual")
        self.assertEqual(inside["line"], "Right now: 21 vs typical 20 (about usual)")
        self.assertEqual(above["category"], "way busier than usual")
        self.assertEqual(below["category"], "way quieter than usual")

    def test_without_a_band_compares_with_the_mean(self):
        readings = [at(6, 18, 0, 10), at(13, 18, 0, 30)]
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        curve = typical.curve_for(readings, today, 4)
        got = typical.compare_now(curve, at(20, 18, 1, 16), today)
        self.assertEqual(got["slot"], "18:00")
        self.assertEqual(got["typical"], 20)
        self.assertEqual(got["category"], "quieter than usual")
        self.assertEqual(got["line"], "Right now: 16 vs typical 20 (quieter than usual)")

    def test_hidden_when_latest_is_not_today_or_the_gap_is_long(self):
        readings = [at(13, 18, 0, 20)]
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        curve = typical.curve_for(readings, today, 4)
        self.assertIsNone(typical.compare_now(curve, at(13, 18, 0, 20), today))
        self.assertIsNone(typical.compare_now(curve, at(20, 7, 0, 5), today))
        self.assertIsNone(typical.compare_now(None, at(20, 18, 0, 16), today))


class PayloadAndBuild(unittest.TestCase):
    def test_payload_nests_weekdays_and_now(self):
        readings = [
            at(6, 18, 0, 10),
            at(13, 18, 0, 30),
            at(20, 18, 1, 16),
            at(5, 9, 0, 12),   # Thursday
        ]
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        got = typical.payload(readings, today)
        self.assertEqual(got["exclude_date"], "2026-11-20")
        self.assertEqual(got["weekdays"]["Friday"]["source"], "all")
        self.assertEqual(got["weekdays"]["Monday"]["label"], got["weekdays"]["Friday"]["label"])
        self.assertEqual(got["now"]["line"], "Right now: 16 vs typical 20 (quieter than usual)")

    def test_dashboard_build_embeds_typical_without_changing_rows(self):
        with tempfile.TemporaryDirectory() as site:
            data = build_dashboard.build(
                datetime(2026, 11, 20, 17, 5, tzinfo=timezone.utc), site=site
            )
        self.assertEqual(data["typical"]["exclude_date"], "2026-11-20")
        friday = data["typical"]["weekdays"]["Friday"]
        self.assertIn(friday["source"], ("weekday", "all"))
        self.assertIn("mean", friday["label"])
        if friday["source"] == "weekday":
            self.assertGreaterEqual(friday["weekday_days"], 3)
            self.assertTrue(friday["label"].startswith("Typical Friday"))
        else:
            self.assertLess(friday["weekday_days"], 3)
            self.assertTrue(friday["label"].startswith("Typical day (all days, mean of "))
        self.assertTrue(friday["slots"])
        self.assertNotIn("note", data["observations"][0])
        self.assertEqual(set(data["observations"][0]), {"t", "c", "s"})
        if data["typical"]["now"] is not None:
            self.assertIn("vs typical", data["typical"]["now"]["line"])
        script = open("dashboard/app.js").read()
        page = open("dashboard/index.html").read()
        self.assertNotIn("esc(typ.label)", script)
        self.assertNotIn("s.p75", script)
        self.assertIn("s.mean", script)
        self.assertIn('id="typicalLegend"', page)


if __name__ == "__main__":
    unittest.main()
