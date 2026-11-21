#!/usr/bin/env python3
"""Quietest upcoming 90-minute window from the typical curve."""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import hero
import typical

VIE = ZoneInfo("Europe/Vienna")


def slot(label: str, mean: float) -> dict:
    return {"slot": label, "n": 3, "mean": mean, "lo": None, "hi": None}


def flat_day(value: float, start: str = "06:00", count: int = 12) -> list[dict]:
    hour, minute = (int(part) for part in start.split(":"))
    rows = []
    for step in range(count):
        total = hour * 60 + minute + step * 15
        rows.append(slot(f"{total // 60:02d}:{total % 60:02d}", value if step < 6 else value + 10))
    return rows


class Ranking(unittest.TestCase):
    def test_ranks_by_mean_and_keeps_an_earlier_tie(self):
        slots = []
        # 10:00–11:15 is the quiet stretch. Later slots are busier, and the next
        # non-overlapping window starts exactly 90 minutes later.
        for step in range(18):
            total = 10 * 60 + step * 15
            slots.append(slot(f"{total // 60:02d}:{total % 60:02d}", 5 if step < 6 else 15))
        windows = typical.candidate_windows(slots)
        self.assertEqual(windows[0]["start"], "10:00")
        self.assertEqual(windows[0]["end"], "11:30")
        self.assertEqual(windows[0]["shown"], 5)
        best, runner = typical.pick_pair(windows, "10:00")
        self.assertEqual(best["start"], "10:00")
        self.assertEqual(runner["start"], "11:30")
        self.assertEqual(runner["end"], "13:00")
        self.assertFalse(typical.windows_overlap(best, runner))
        self.assertTrue(typical.windows_overlap(best, {"start": "10:15", "end": "11:45"}))

    def test_skips_a_window_with_a_hole(self):
        slots = [slot("10:00", 5), slot("10:15", 5), slot("10:45", 5), slot("11:00", 5), slot("11:15", 5), slot("11:30", 5)]
        starts = [item["start"] for item in typical.candidate_windows(slots)]
        self.assertNotIn("10:00", starts)
        self.assertNotIn("10:15", starts)

    def test_slots_left_through_close(self):
        self.assertEqual(typical.slots_left(datetime(2026, 11, 21, 5, 30, tzinfo=VIE)), 68)
        self.assertEqual(typical.earliest_start(datetime(2026, 11, 21, 5, 30, tzinfo=VIE)), "06:00")
        self.assertEqual(typical.slots_left(datetime(2026, 11, 21, 9, 14, tzinfo=VIE)), 56)
        self.assertEqual(typical.earliest_start(datetime(2026, 11, 21, 9, 14, tzinfo=VIE)), "09:00")
        self.assertEqual(typical.slots_left(datetime(2026, 11, 21, 21, 30, tzinfo=VIE)), 6)
        self.assertEqual(typical.slots_left(datetime(2026, 11, 21, 21, 45, tzinfo=VIE)), 5)
        self.assertIsNone(typical.earliest_start(datetime(2026, 11, 21, 21, 45, tzinfo=VIE)))
        self.assertEqual(typical.slots_left(datetime(2026, 11, 21, 23, 10, tzinfo=VIE)), 0)


class Recommendation(unittest.TestCase):
    def _catalog(self):
        saturday = {
            "source": "all",
            "weekday": "Saturday",
            "n_days": 13,
            "slots": flat_day(12, "06:00", 68)[:6] + [
                slot(f"{(6 * 60 + step * 15) // 60:02d}:{(6 * 60 + step * 15) % 60:02d}", 30 if step < 30 else 12)
                for step in range(6, 68)
            ],
        }
        # Rebuild Saturday as a simple quiet morning and a busier midday, then a quiet afternoon.
        slots = []
        for step in range(68):
            total = 6 * 60 + step * 15
            mean = 12 if step < 12 else (28 if step < 24 else 9)
            slots.append(slot(f"{total // 60:02d}:{total % 60:02d}", mean))
        saturday["slots"] = slots
        sunday = {
            "source": "weekday",
            "weekday": "Sunday",
            "n_days": 3,
            "slots": [slot(f"{(6 * 60 + step * 15) // 60:02d}:{(6 * 60 + step * 15) % 60:02d}", 7) for step in range(68)],
        }
        return typical.best_time_catalog({"Saturday": saturday, "Sunday": sunday})

    def test_today_line_uses_all_days_and_a_non_overlapping_runner(self):
        catalog = self._catalog()
        got = typical.recommend(catalog, datetime(2026, 11, 21, 9, 14, tzinfo=VIE))
        self.assertEqual(got["status"], "today")
        self.assertEqual(got["start"], "12:00")
        self.assertEqual(got["end"], "13:30")
        self.assertEqual(got["shown"], 9)
        self.assertEqual(
            got["line"],
            "Quietest window left today: 12:00–13:30, typically ~9 people (based on all days, 13 days)",
        )
        self.assertEqual(got["confidence"], "Based on all days, 13 days")
        self.assertGreaterEqual(got["runner_up"]["start"], "09:00")
        self.assertNotEqual(got["runner_up"]["start"], "12:00")
        self.assertFalse(typical.windows_overlap(got, got["runner_up"]))
        self.assertIn("Runner-up:", got["runner_up"]["line"])

    def test_evening_offers_tomorrow(self):
        catalog = self._catalog()
        got = typical.recommend(catalog, datetime(2026, 11, 21, 22, 0, tzinfo=VIE))
        self.assertEqual(got["status"], "evening")
        self.assertEqual(got["message"], "Not enough time left today")
        self.assertEqual(
            got["tomorrow"]["line"],
            "Tomorrow's quietest window: 06:00–07:30, typically ~7 people (based on Sundays, 3 days)",
        )

    def test_no_data(self):
        got = typical.recommend({}, datetime(2026, 11, 21, 10, 0, tzinfo=VIE))
        self.assertEqual(got["status"], "none")
        self.assertEqual(got["message"], "No typical data yet")

    def test_weekday_curve_once_three_days_exist(self):
        # Three past Saturdays: a busy morning block and a quiet afternoon block.
        # A loud Monday must not change the Saturday afternoon mean.
        readings = []
        for day in (7, 14, 21):
            for step in range(6):
                morning = 8 * 60 + step * 15
                afternoon = 15 * 60 + step * 15
                readings.append(hero.Reading(datetime(2026, 11, day, morning // 60, morning % 60, tzinfo=VIE), 40))
                readings.append(hero.Reading(datetime(2026, 11, day, afternoon // 60, afternoon % 60, tzinfo=VIE), 4))
        readings.append(hero.Reading(datetime(2026, 11, 16, 15, 0, tzinfo=VIE), 80))
        today = datetime(2026, 11, 28, 9, 0, tzinfo=VIE)  # Saturday
        curves = typical.display_curves(readings, today.date())
        self.assertEqual(curves["Saturday"]["source"], "weekday")
        got = typical.best_time(curves, today)["at_build"]
        self.assertEqual(got["source"], "weekday")
        self.assertEqual(got["start"], "15:00")
        self.assertEqual(got["end"], "16:30")
        self.assertIn("based on Saturdays, 3 days", got["line"])


class Build(unittest.TestCase):
    def test_dashboard_embeds_best_time(self):
        import tempfile
        from datetime import timezone
        import build_dashboard
        with tempfile.TemporaryDirectory() as site:
            data = build_dashboard.build(datetime(2026, 11, 21, 8, 5, tzinfo=timezone.utc), site=site)
        box = data["best_time"]
        self.assertEqual(box["window_slots"], 6)
        self.assertIn("Saturday", box["by_weekday"])
        self.assertIn(box["at_build"]["status"], ("today", "evening", "none"))
        if box["at_build"]["status"] == "today":
            self.assertIn("Quietest window left today", box["at_build"]["line"])
            self.assertIn("based on ", box["at_build"]["line"])
        self.assertEqual(set(data["observations"][0]), {"t", "c", "s"})


if __name__ == "__main__":
    unittest.main()
