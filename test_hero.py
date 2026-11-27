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
    def _usual(self, readings):
        import typical
        latest = max(readings, key=lambda reading: reading.when)
        curves = typical.display_curves(readings, latest.when.date())
        name = typical.WEEKDAY_NAMES[latest.when.weekday()]
        got = hero.summarize(readings)
        got["usual"] = typical.usual_for(latest, curves.get(name))
        return got

    def test_four_weekdays_use_the_slot_median_and_shared_label(self):
        readings = [
            at(5, 7, 31, 10, month=10),
            at(12, 7, 40, 20, month=10),
            at(19, 7, 35, 30, month=10),
            at(26, 7, 32, 40, month=10),
            at(2, 7, 31, 12),  # latest Monday, excluded from the 07:30 slot
        ]
        got = self._usual(readings)
        self.assertEqual(got["usual"]["scope"], "weekday")
        self.assertEqual(got["usual"]["scope_label"], "on Mondays")
        self.assertEqual(got["usual"]["slot"], "07:30")
        self.assertEqual(got["usual"]["n"], 25)  # median of 10, 20, 30, 40
        self.assertEqual(got["usual"]["category"], "quieter than usual")
        self.assertEqual(got["usual"]["line"], "Usually ~25 at this hour · on Mondays · quieter than usual")
        self.assertEqual(got["trend"], "down")
        self.assertEqual(got["time_label"], "Mon 2 Nov, 07:31 CET")

    def test_three_weekdays_fall_back_to_all_days(self):
        readings = [
            at(2, 8, 0, 10),
            at(9, 8, 0, 30),
            at(16, 8, 0, 14),
            at(3, 8, 10, 18),  # Tuesday
            at(23, 8, 10, 16),  # latest Monday
        ]
        got = self._usual(readings)
        self.assertEqual(got["usual"]["scope"], "all")
        self.assertEqual(got["usual"]["scope_label"], "all days")
        self.assertIn("all days", got["usual"]["line"])
        self.assertNotIn("way ", got["usual"]["line"])

    def test_median_without_a_band_omits_the_category(self):
        got = self._usual([at(3, 11, 5, 9), at(4, 11, 10, 21)])
        self.assertIsNone(got["usual"]["category"])
        self.assertEqual(got["usual"]["line"], "Usually ~9 at this hour · all days")

    def test_hides_line_when_the_slot_has_no_history(self):
        got = self._usual([at(2, 6, 0, 4), at(2, 18, 0, 22)])
        self.assertIsNone(got["usual"])
        self.assertEqual(got["count"], 22)
        self.assertEqual(got["band"], "amber")

    def test_today_is_not_part_of_its_own_typical(self):
        got = self._usual([at(2, 9, 1, 10), at(3, 9, 5, 40)])
        self.assertEqual(got["usual"]["n"], 10)
        self.assertNotEqual(got["usual"]["median"], 25)


class Categories(unittest.TestCase):
    def test_band_edges_are_about_usual(self):
        self.assertEqual(hero.usual_label(15, 15, 25), "about usual")
        self.assertEqual(hero.usual_label(25, 15, 25), "about usual")
        self.assertEqual(hero.usual_label(14, 15, 25), "quieter than usual")
        self.assertEqual(hero.usual_label(26, 15, 25), "busier than usual")
        self.assertIsNone(hero.usual_label(20, None, None))
        self.assertEqual(hero.usual_line(21, "on Fridays", "about usual"), "Usually ~21 at this hour · on Fridays · about usual")
        self.assertEqual(hero.usual_line(9, "all days", None), "Usually ~9 at this hour · all days")


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
        # Observations are not polled. The best-time box only rechecks the clock.
        script = open("dashboard/app.js").read()
        self.assertNotIn("setInterval(load", script)
        self.assertIn("bestTimeBox()", script)
        page = open("dashboard/index.html").read()
        self.assertLess(page.index('id="hero"'), page.index("<header"))


if __name__ == "__main__":
    unittest.main()
