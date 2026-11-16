#!/usr/bin/env python3
"""Colour bands, trend arrow, and typical-hour wording for the dashboard hero."""
from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

import hero

VIE = ZoneInfo("Europe/Vienna")


def at(day: int, hour: int, minute: int, count: int, month: int = 11) -> hero.Reading:
    # November 2026: Sunday 1, Monday 2, ... Monday 16.
    return hero.Reading(datetime(2026, month, day, hour, minute, tzinfo=VIE), count)


class Bands(unittest.TestCase):
    def test_colour_thresholds(self):
        self.assertEqual(hero.load_band(0), "green")
        self.assertEqual(hero.load_band(14), "green")
        self.assertEqual(hero.load_band(15), "amber")
        self.assertEqual(hero.load_band(30), "amber")
        self.assertEqual(hero.load_band(31), "red")
        self.assertEqual(hero.load_band(80), "red")


class Trend(unittest.TestCase):
    def test_up_down_flat_and_first_reading(self):
        self.assertEqual(hero.trend(12, 10), "up")
        self.assertEqual(hero.trend(10, 12), "down")
        self.assertEqual(hero.trend(10, 10), "flat")
        self.assertIsNone(hero.trend(10, None))

    def test_summarize_uses_previous_ok_only(self):
        # 20 then 15: down, amber. A gap in time does not matter.
        got = hero.summarize([at(2, 8, 0, 20), at(2, 9, 0, 15)])
        self.assertEqual(got["trend"], "down")
        self.assertEqual(got["count"], 15)
        self.assertEqual(got["band"], "amber")


class Typical(unittest.TestCase):
    def test_weekday_median_once_three_dates_exist(self):
        # Three earlier Mondays at 07:xx, plus a Tuesday that must be ignored.
        # Monday 2 Nov 2026, 9 Nov, and we need a third Monday: 26 Oct.
        readings = [
            at(26, 7, 10, 10, month=10),  # Monday
            at(26, 7, 40, 14, month=10),  # same Monday, two readings
            at(2, 7, 15, 20),             # Monday
            at(3, 7, 15, 40),             # Tuesday, same hour, must not enter the weekday median
            at(9, 7, 5, 30),              # Monday
            at(16, 7, 31, 12),            # latest Monday
        ]
        got = hero.summarize(readings)
        # Weekday values 10, 14, 20, 30 → median 17. Latest 12 is excluded.
        self.assertEqual(got["usual"]["scope"], "weekday")
        self.assertEqual(got["usual"]["scope_label"], "Mondays")
        self.assertEqual(got["usual"]["median"], 17)
        self.assertEqual(got["usual"]["n"], 17)
        self.assertEqual(got["usual"]["category"], "quieter than usual")
        self.assertEqual(got["usual"]["line"], "Usually ~17 at this hour on Mondays · quieter than usual")
        self.assertEqual(got["trend"], "down")  # 30 then 12
        self.assertEqual(got["time_label"], "Mon 16 Nov, 07:31 CET")

    def test_falls_back_to_all_days_below_three_weekday_dates(self):
        readings = [
            at(2, 8, 0, 10),    # Monday
            at(9, 8, 0, 30),    # Monday — only two Monday dates
            at(3, 8, 0, 14),    # Tuesday
            at(4, 8, 0, 18),    # Wednesday
            at(16, 8, 10, 16),  # latest Monday, excluded from the median
        ]
        got = hero.summarize(readings)
        # All-days hour 8: 10, 30, 14, 18 → median 16.
        self.assertEqual(got["usual"]["scope"], "all")
        self.assertEqual(got["usual"]["scope_label"], "all days")
        self.assertEqual(got["usual"]["median"], 16)
        self.assertEqual(got["usual"]["n"], 16)
        self.assertEqual(got["usual"]["category"], "about usual")
        self.assertEqual(got["usual"]["line"], "Usually ~16 at this hour, all days · about usual")

    def test_shows_all_days_from_a_single_past_reading(self):
        got = hero.summarize([at(3, 11, 0, 9), at(4, 11, 15, 21)])
        self.assertEqual(got["usual"]["scope"], "all")
        self.assertEqual(got["usual"]["n"], 9)
        self.assertIn("all days", got["usual"]["line"])
        self.assertTrue(got["usual"]["line"].startswith("Usually ~9 at this hour"))

    def test_hides_line_when_the_hour_has_no_past_readings(self):
        got = hero.summarize([at(2, 6, 0, 4), at(2, 18, 0, 22)])
        self.assertIsNone(got["usual"])
        self.assertEqual(got["count"], 22)
        self.assertEqual(got["band"], "amber")

    def test_latest_reading_is_not_part_of_its_own_typical(self):
        got = hero.summarize([at(2, 9, 0, 10), at(2, 9, 30, 40)])
        self.assertEqual(got["usual"]["n"], 10)
        self.assertNotEqual(got["usual"]["median"], 25)

    def test_other_hours_are_ignored(self):
        got = hero.summarize([
            at(2, 6, 0, 1),
            at(3, 6, 0, 1),
            at(4, 6, 0, 1),
            at(4, 12, 0, 28),
        ])
        self.assertIsNone(got["usual"])


class Categories(unittest.TestCase):
    def test_about_way_and_plain_bands(self):
        # typical 20 → about below 4 (max(3, 4)), way at 10 (max(8, 10))
        self.assertEqual(hero.category(20, 20), "about usual")
        self.assertEqual(hero.category(17, 20), "about usual")  # |d|=3 < 4
        self.assertEqual(hero.category(16, 20), "quieter than usual")  # |d|=4, not yet 10
        self.assertEqual(hero.category(24, 20), "busier than usual")
        self.assertEqual(hero.category(10, 20), "way quieter than usual")
        self.assertEqual(hero.category(30, 20), "way busier than usual")

    def test_small_typical_uses_absolute_floors(self):
        # typical 10 → about below max(3, 2)=3, way at max(8, 5)=8
        self.assertEqual(hero.category(10, 10), "about usual")
        self.assertEqual(hero.category(8, 10), "about usual")  # |d|=2 < 3
        self.assertEqual(hero.category(7, 10), "quieter than usual")
        self.assertEqual(hero.category(13, 10), "busier than usual")
        self.assertEqual(hero.category(2, 10), "way quieter than usual")
        self.assertEqual(hero.category(18, 10), "way busier than usual")

    def test_boundary_is_strict_for_about_and_inclusive_for_way(self):
        self.assertEqual(hero.category(16, 20), "quieter than usual")  # |d| == about threshold, not inside it
        self.assertEqual(hero.category(10, 20), "way quieter than usual")  # |d| == way threshold


class BuildWire(unittest.TestCase):
    def test_fixed_offset_is_labelled_in_vienna(self):
        import build_dashboard
        got = build_dashboard.hero_payload([{
            "s": "ok", "c": 19,
            "vienna": "2026-11-16T07:31:05+01:00",
            "t": "2026-11-16T06:31:05Z",
        }])
        self.assertEqual(got["time_label"], "Mon 16 Nov, 07:31 CET")
        self.assertEqual(got["band"], "amber")
        self.assertIsNone(got["usual"])


    def test_dashboard_build_embeds_hero_without_changing_rows(self):
        import tempfile
        from datetime import timezone
        import build_dashboard

        with tempfile.TemporaryDirectory() as site:
            data = build_dashboard.build(datetime(2026, 11, 16, 7, tzinfo=timezone.utc), site=site)
        oks = [o for o in data["observations"] if o["s"] == "ok"]
        self.assertEqual(data["hero"]["count"], oks[-1]["c"])
        self.assertIn(data["hero"]["band"], ("green", "amber", "red"))
        self.assertIn(data["hero"]["trend"], ("up", "down", "flat", None))
        self.assertNotIn("note", data["observations"][0])
        # Static page: the script does not poll.
        script = open("dashboard/app.js").read()
        self.assertNotIn("setInterval", script)
        page = open("dashboard/index.html").read()
        self.assertLess(page.index('id="hero"'), page.index("<header"))


if __name__ == "__main__":
    unittest.main()
