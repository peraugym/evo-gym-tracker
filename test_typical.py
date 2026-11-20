#!/usr/bin/env python3
"""Typical weekday curve: binning, exclusions, median, and percentile band."""
from __future__ import annotations

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


class Percentile(unittest.TestCase):
    def test_matches_median_and_interpolates(self):
        self.assertEqual(typical.percentile([10, 20, 30], 0.5), 20)
        self.assertEqual(typical.percentile([10, 20, 30], 0.25), 15)
        self.assertEqual(typical.percentile([10, 20, 30], 0.75), 25)
        self.assertEqual(typical.percentile([10, 20, 30, 40], 0.5), 25)
        self.assertEqual(typical.percentile([7], 0.25), 7)


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
        self.assertEqual(got["label"], "Typical Friday (median of 2 past Fridays)")
        slot = next(s for s in got["slots"] if s["slot"] == "18:00")
        self.assertEqual(slot["median"], 30)
        self.assertIsNone(slot["p25"])
        self.assertIsNone(slot["p75"])

    def test_one_value_per_day_is_that_days_median(self):
        # Two readings in the same slot on one Friday must not outweigh another Friday.
        readings = [
            at(6, 10, 1, 10),
            at(6, 10, 14, 30),   # same 10:00 slot, day median 20
            at(13, 10, 0, 40),
        ]
        got = typical.curve_for(readings, datetime(2026, 11, 20, tzinfo=VIE).date(), 4)
        slot = next(s for s in got["slots"] if s["slot"] == "10:00")
        self.assertEqual(slot["median"], 30)  # median of 20 and 40
        self.assertEqual(slot["n"], 2)

    def test_band_appears_only_with_three_past_days(self):
        readings = [
            at(23, 7, 0, 10, month=10),  # Friday
            at(30, 7, 0, 20, month=10),
            at(6, 7, 0, 30),
        ]
        got = typical.curve_for(readings, datetime(2026, 11, 13, tzinfo=VIE).date(), 4)
        slot = next(s for s in got["slots"] if s["slot"] == "07:00")
        self.assertEqual(got["n_days"], 3)
        self.assertEqual(slot["median"], 20)
        self.assertEqual(slot["p25"], 15)
        self.assertEqual(slot["p75"], 25)

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
        self.assertIsNone(noon["p25"])
        self.assertIsNone(noon["p75"])

    def test_no_curve_when_weekday_has_no_past_days(self):
        readings = [at(20, 9, 0, 16)]  # Friday today only
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        self.assertIsNone(typical.curve_for(readings, today, 4))
        self.assertEqual(typical.curves(readings, today), {})

    def test_singular_label_for_one_past_day(self):
        readings = [at(13, 8, 0, 22)]
        got = typical.curve_for(readings, datetime(2026, 11, 20, tzinfo=VIE).date(), 4)
        self.assertEqual(got["label"], "Typical Friday (median of 1 past Friday)")


class CompareNow(unittest.TestCase):
    def test_line_uses_same_slot_and_hero_categories(self):
        readings = [at(6, 18, 0, 10), at(13, 18, 0, 30)]
        today = datetime(2026, 11, 20, tzinfo=VIE).date()
        curve = typical.curve_for(readings, today, 4)
        got = typical.compare_now(curve, at(20, 18, 1, 16), today)
        self.assertEqual(got["slot"], "18:00")
        self.assertEqual(got["typical"], 20)
        self.assertEqual(got["count"], 16)
        self.assertEqual(got["category"], "quieter than usual")
        self.assertEqual(got["line"], "Right now: 16 vs typical 20 (quieter than usual)")

    def test_hidden_when_latest_is_not_today_or_slot_is_new(self):
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
        self.assertIn("Friday", got["weekdays"])
        self.assertIn("Thursday", got["weekdays"])
        self.assertNotIn("Monday", got["weekdays"])
        self.assertEqual(got["now"]["line"], "Right now: 16 vs typical 20 (quieter than usual)")

    def test_dashboard_build_embeds_typical_without_changing_rows(self):
        with tempfile.TemporaryDirectory() as site:
            data = build_dashboard.build(
                datetime(2026, 11, 20, 17, 5, tzinfo=timezone.utc), site=site
            )
        self.assertEqual(data["typical"]["exclude_date"], "2026-11-20")
        friday = data["typical"]["weekdays"]["Friday"]
        self.assertGreaterEqual(friday["n_days"], 1)
        self.assertTrue(friday["label"].startswith("Typical Friday"))
        self.assertTrue(any(s["slot"] == "18:00" for s in friday["slots"]))
        self.assertNotIn("note", data["observations"][0])
        self.assertEqual(set(data["observations"][0]), {"t", "c", "s"})
        if data["typical"]["now"] is not None:
            self.assertIn("vs typical", data["typical"]["now"]["line"])


if __name__ == "__main__":
    unittest.main()
