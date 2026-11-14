#!/usr/bin/env python3
"""Unit tests for the window, dedupe, alert, and dashboard build. No network."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import build_dashboard
import collect

VIE = ZoneInfo("Europe/Vienna")
HERE = os.path.dirname(os.path.abspath(__file__))
HEADER = "observed_utc,observed_vienna,weekday,club,count,status,source,source_timestamp,note\n"


def _sha(path: str) -> str:
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


class PreserveHistory(unittest.TestCase):
    def test_original_rows_stay_in_place(self):
        with open(os.path.join(HERE, "observations.csv"), newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertGreaterEqual(len(rows), 378)
        self.assertEqual(rows[0]["observed_utc"], "2026-11-07T09:00:00+00:00")
        self.assertEqual(rows[0]["count"], "22")
        self.assertEqual(rows[0]["club"], "EVO Bruno-Marek-Allee")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[377]["observed_utc"], "2026-11-14T08:46:01.116856+00:00")
        self.assertEqual(rows[377]["observed_vienna"], "2026-11-14T09:46:01.116856+01:00")
        self.assertEqual(rows[377]["count"], "13")
        self.assertEqual(list(rows[0]), [
            "observed_utc", "observed_vienna", "weekday", "club", "count",
            "status", "source", "source_timestamp", "note",
        ])

    def test_existing_alert_lines(self):
        lines = open(os.path.join(HERE, "alerts.log")).read().splitlines()
        self.assertGreaterEqual(len(lines), 2)
        self.assertEqual(lines[0], "2026-11-13T08:10:30.950916+01:00 count=9 time=08:10 webhook=pending")
        self.assertEqual(lines[1], "2026-11-13T09:13:47.502694+01:00 count=9 time=09:13 webhook=pending")


class Window(unittest.TestCase):
    def test_bounds_cover_cet_and_cest(self):
        cron_hours = set(range(4, 22))  # 4-21
        cron_minutes = {0, 15, 30, 45}
        cases = [
            (datetime(2026, 1, 15, 6, 0, tzinfo=VIE), True, 5, 0),
            (datetime(2026, 1, 15, 22, 45, tzinfo=VIE), True, 21, 45),
            (datetime(2026, 1, 15, 5, 59, tzinfo=VIE), False, 4, 59),
            (datetime(2026, 1, 15, 5, 0, tzinfo=VIE), False, 4, 0),
            (datetime(2026, 1, 15, 22, 46, tzinfo=VIE), False, 21, 46),
            (datetime(2026, 7, 15, 6, 0, tzinfo=VIE), True, 4, 0),
            (datetime(2026, 7, 15, 22, 45, tzinfo=VIE), True, 20, 45),
            (datetime(2026, 7, 15, 5, 59, tzinfo=VIE), False, 3, 59),
            (datetime(2026, 7, 15, 22, 46, tzinfo=VIE), False, 20, 46),
        ]
        for local, inside, uh, um in cases:
            utc = local.astimezone(timezone.utc)
            self.assertEqual((utc.hour, utc.minute), (uh, um), local)
            self.assertEqual(collect.in_collect_window(local), inside, local)
            if inside:
                self.assertIn(utc.hour, cron_hours, local)
                self.assertIn(utc.minute, cron_minutes, local)
        # 05:00 CET is outside the club window but inside the UTC cron, so the script must skip it.
        early = datetime(2026, 1, 15, 5, 0, tzinfo=VIE).astimezone(timezone.utc)
        self.assertIn(early.hour, cron_hours)
        self.assertEqual(collect.decide(datetime(2026, 1, 15, 5, 0, tzinfo=VIE)), "skip")
        # 2027 is still inside the clock window: collection does not stop on a calendar date.
        self.assertTrue(collect.in_collect_window(datetime(2027, 3, 1, 12, 0, tzinfo=VIE)))


class DedupeAndAlert(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.csv = os.path.join(self.tmp.name, "observations.csv")
        self.alerts = os.path.join(self.tmp.name, "alerts.log")
        with open(self.csv, "w", newline="") as f:
            f.write(HEADER.replace("\n", "\r\n"))
        with open(self.alerts, "w") as f:
            f.write("2026-11-13T08:10:30.950916+01:00 count=9 time=08:10 webhook=pending\n")
            f.write("2026-11-13T09:13:47.502694+01:00 count=9 time=09:13 webhook=pending\n")
        self._env = os.environ.copy()
        os.environ["EVO_CSV"] = self.csv
        os.environ["EVO_ALERTS_LOG"] = self.alerts

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self.tmp.cleanup()

    def _rows(self):
        with open(self.csv, newline="") as f:
            return list(csv.DictReader(f))

    def _apply(self, when, count=None, ok=True, status="error", note="x"):
        payload = {"ok": ok, "observed": when.astimezone(timezone.utc).isoformat(), "note": note}
        if ok:
            payload["count"] = count
            payload["status"] = "ok"
            payload["sentence"] = f"Momentan sind {count} Mitglieder im Club"
        else:
            payload["status"] = status
            payload["error"] = note
        return collect.apply_payload(payload)

    def test_success_then_same_slot_is_duplicate(self):
        a = datetime(2026, 11, 14, 10, 5, tzinfo=VIE)
        b = datetime(2026, 11, 14, 10, 7, tzinfo=VIE)
        self.assertEqual(self._apply(a, 15)["outcome"], "written")
        self.assertEqual(self._apply(b, 12)["outcome"], "duplicate")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["count"], "15")
        self.assertEqual(rows[0]["status"], "ok")
        self.assertTrue(rows[0]["observed_utc"].endswith("+00:00"))
        self.assertIn("Bruno-Marek-Allee", rows[0]["club"])

    def test_failure_then_success_same_slot(self):
        t1 = datetime(2026, 11, 14, 11, 2, tzinfo=VIE)
        t2 = datetime(2026, 11, 14, 11, 8, tzinfo=VIE)
        self.assertEqual(self._apply(t1, ok=False, status="unreadable", note="live sentence not found")["outcome"], "written")
        second = self._apply(t2, 9)
        self.assertEqual(second["outcome"], "written")
        rows = self._rows()
        self.assertEqual([r["status"] for r in rows], ["unreadable", "ok"])
        self.assertEqual(rows[1]["count"], "9")
        # First success of the day: a failure does not count, so this must not alert.
        self.assertFalse(second["alerted"])

    def test_second_failure_rejected(self):
        t1 = datetime(2026, 11, 14, 12, 1, tzinfo=VIE)
        t2 = datetime(2026, 11, 14, 12, 3, tzinfo=VIE)
        self.assertEqual(self._apply(t1, ok=False, note="timeout")["outcome"], "written")
        self.assertEqual(self._apply(t2, ok=False, note="timeout again")["outcome"], "duplicate")
        self.assertEqual(len(self._rows()), 1)

    def test_quiet_crossing_and_not_first_of_day(self):
        self.assertFalse(collect.is_quiet_crossing(None, 4))
        self.assertFalse(collect.is_quiet_crossing(9, 4))
        self.assertFalse(collect.is_quiet_crossing(10, 10))
        self.assertTrue(collect.is_quiet_crossing(10, 9))
        self.assertTrue(collect.is_quiet_crossing(15, 0))
        day = datetime(2026, 11, 14, 10, 0, tzinfo=VIE)
        later = datetime(2026, 11, 14, 10, 20, tzinfo=VIE)
        self.assertEqual(self._apply(day, 15)["outcome"], "written")
        self.assertFalse(self._apply(day, 15)["alerted"])
        crossed = self._apply(later, 8)
        self.assertEqual(crossed["outcome"], "written")
        self.assertTrue(crossed["alerted"])
        lines = open(self.alerts).read().splitlines()
        self.assertEqual(lines[0], "2026-11-13T08:10:30.950916+01:00 count=9 time=08:10 webhook=pending")
        self.assertEqual(lines[1], "2026-11-13T09:13:47.502694+01:00 count=9 time=09:13 webhook=pending")
        self.assertEqual(len(lines), 3)
        self.assertIn("count=8 time=10:20 webhook=pending", lines[2])
        self.assertTrue(lines[2].startswith("2026-"))
        # Re-applying the same reading must not add another alert line.
        self.assertEqual(self._apply(later, 8)["outcome"], "duplicate")
        self.assertEqual(len(open(self.alerts).read().splitlines()), 3)

    def test_failure_does_not_reset_baseline(self):
        self._apply(datetime(2026, 11, 14, 16, 0, tzinfo=VIE), 12)
        self._apply(datetime(2026, 11, 14, 16, 15, tzinfo=VIE), ok=False, note="blip")
        result = self._apply(datetime(2026, 11, 14, 16, 30, tzinfo=VIE), 7)
        self.assertTrue(result["alerted"])
        self.assertIn("count=7 time=16:30 webhook=pending", open(self.alerts).read())

    def test_already_below_does_not_alert(self):
        self._apply(datetime(2026, 11, 14, 20, 0, tzinfo=VIE), 9)
        result = self._apply(datetime(2026, 11, 14, 20, 15, tzinfo=VIE), 4)
        self.assertFalse(result["alerted"])
        self.assertEqual(len(open(self.alerts).read().splitlines()), 2)

    def test_duplicate_slot_skips_fetch_decision(self):
        when = datetime(2026, 11, 14, 18, 5, tzinfo=VIE)
        self._apply(when, 21)
        self.assertEqual(collect.decide(datetime(2026, 11, 14, 18, 10, tzinfo=VIE)), "duplicate")
        self.assertEqual(collect.decide(datetime(2026, 11, 14, 18, 15, tzinfo=VIE)), "fetch")


class Dashboard(unittest.TestCase):
    def test_build_real_history_and_a_failure(self):
        with tempfile.TemporaryDirectory() as site:
            data = build_dashboard.build(datetime(2026, 11, 14, 12, tzinfo=timezone.utc), site=site)
            self.assertTrue(os.path.exists(os.path.join(site, "index.html")))
            self.assertTrue(os.path.exists(os.path.join(site, "data.json")))
            self.assertTrue(os.path.exists(os.path.join(site, ".nojekyll")))
        self.assertGreaterEqual(len(data["observations"]), 378)
        self.assertEqual(data["observations"][0], {"t": "2026-11-07T09:00:00Z", "c": 22, "s": "ok"})
        self.assertEqual(data["observations"][377]["t"], "2026-11-14T08:46:01Z")
        self.assertEqual(data["observations"][377]["c"], 13)
        self.assertIsNone(data["cadence"]["until"])
        self.assertNotIn("note", json.dumps(data))

    def test_failure_row_has_null_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "o.csv")
            site = os.path.join(tmp, "site")
            with open(src, "w", newline="") as f:
                w = csv.DictWriter(f, ["observed_utc", "observed_vienna", "weekday", "club", "count", "status", "source", "source_timestamp", "note"])
                w.writeheader()
                w.writerow({
                    "observed_utc": "2026-11-14T10:00:00+00:00",
                    "observed_vienna": "2026-11-14T11:00:00+01:00",
                    "weekday": "Sat", "club": "EVO Bruno-Marek-Allee", "count": "",
                    "status": "error", "source": "x", "source_timestamp": "", "note": "blocked",
                })
            data = build_dashboard.build(src=src, site=site)
            self.assertEqual(data["observations"], [{"t": "2026-11-14T10:00:00Z", "c": None, "s": "error"}])


def setUpModule():
    global _CSV_SHA, _ALERTS
    _CSV_SHA = _sha(os.path.join(HERE, "observations.csv"))
    _ALERTS = open(os.path.join(HERE, "alerts.log"), "rb").read()


def tearDownModule():
    if _sha(os.path.join(HERE, "observations.csv")) != _CSV_SHA:
        raise AssertionError("observations.csv was modified by the tests")
    if open(os.path.join(HERE, "alerts.log"), "rb").read() != _ALERTS:
        raise AssertionError("alerts.log was modified by the tests")


if __name__ == "__main__":
    unittest.main()
