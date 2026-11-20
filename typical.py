#!/usr/bin/env python3
"""Typical weekday occupancy curve for the dashboard overlay.

Built from past same-weekday ok readings, excluding today, binned to
15-minute slots from 06:00 to 22:45 Europe/Vienna. Collection and the
CSV schema are not involved.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import hero

VIE = ZoneInfo("Europe/Vienna")
OPEN = time(6, 0)
CLOSE_SLOT = time(22, 45)
SLOT_MINUTES = 15
BAND_MIN_DAYS = 3

WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
WEEKDAY_PLURAL = hero.WEEKDAY_PLURAL


def slot_times() -> list[time]:
    """Every 15-minute slot from 06:00 to 22:45 inclusive."""
    start = OPEN.hour * 60 + OPEN.minute
    end = CLOSE_SLOT.hour * 60 + CLOSE_SLOT.minute
    return [time(m // 60, m % 60) for m in range(start, end + 1, SLOT_MINUTES)]


def slot_label(hhmm: time) -> str:
    return f"{hhmm.hour:02d}:{hhmm.minute:02d}"


def slot_of(when: datetime) -> time | None:
    """Floor a Vienna timestamp to its 15-minute slot, or None if outside hours."""
    local = when.astimezone(VIE) if when.tzinfo else when.replace(tzinfo=VIE)
    minutes = local.hour * 60 + local.minute
    floored = minutes - (minutes % SLOT_MINUTES)
    hhmm = time(floored // 60, floored % 60)
    if hhmm < OPEN or hhmm > CLOSE_SLOT:
        return None
    return hhmm


def percentile(values: list[float], p: float) -> float:
    """Linear-interpolation percentile; p is in 0..1. Matches median at p=0.5."""
    if not values:
        raise ValueError("percentile of empty sample")
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    k = (len(ordered) - 1) * p
    lo = math.floor(k)
    hi = math.ceil(k)
    if lo == hi:
        return float(ordered[int(k)])
    return ordered[lo] * (hi - k) + ordered[hi] * (k - lo)


def _day_slot_values(readings: list[hero.Reading], exclude: date, weekday: int) -> dict[date, dict[time, list[int]]]:
    by_date: dict[date, dict[time, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in readings:
        when = r.when.astimezone(VIE) if r.when.tzinfo else r.when.replace(tzinfo=VIE)
        if when.date() == exclude or when.weekday() != weekday:
            continue
        slot = slot_of(when)
        if slot is None:
            continue
        by_date[when.date()][slot].append(int(r.count))
    return by_date


def _slot_stats(by_date: dict[date, dict[time, list[int]]], n_days: int) -> list[dict]:
    samples: dict[time, list[float]] = defaultdict(list)
    for slots in by_date.values():
        for hhmm, counts in slots.items():
            samples[hhmm].append(statistics.median(counts))
    out = []
    show_band = n_days >= BAND_MIN_DAYS
    for hhmm in slot_times():
        values = samples.get(hhmm)
        if not values:
            continue
        row = {
            "slot": slot_label(hhmm),
            "n": len(values),
            "median": statistics.median(values),
            "p25": None,
            "p75": None,
        }
        if show_band and len(values) >= BAND_MIN_DAYS:
            row["p25"] = percentile(values, 0.25)
            row["p75"] = percentile(values, 0.75)
        out.append(row)
    return out


def label_for(weekday: int, n_days: int) -> str:
    name = WEEKDAY_NAMES[weekday]
    plural = WEEKDAY_PLURAL[weekday] if n_days != 1 else name
    return f"Typical {name} (median of {n_days} past {plural})"


def curve_for(readings: list[hero.Reading], exclude: date, weekday: int) -> dict | None:
    by_date = _day_slot_values(readings, exclude, weekday)
    n_days = len(by_date)
    if n_days == 0:
        return None
    return {
        "weekday": WEEKDAY_NAMES[weekday],
        "n_days": n_days,
        "label": label_for(weekday, n_days),
        "slots": _slot_stats(by_date, n_days),
    }


def curves(readings: list[hero.Reading], exclude: date) -> dict[str, dict]:
    out = {}
    for weekday in range(7):
        curve = curve_for(readings, exclude, weekday)
        if curve is not None:
            out[curve["weekday"]] = curve
    return out


def compare_now(curve: dict | None, latest: hero.Reading, today: date) -> dict | None:
    """Compare today's latest reading with the typical value in the same slot."""
    if curve is None:
        return None
    when = latest.when.astimezone(VIE) if latest.when.tzinfo else latest.when.replace(tzinfo=VIE)
    if when.date() != today:
        return None
    slot = slot_of(when)
    if slot is None:
        return None
    label = slot_label(slot)
    match = next((s for s in curve["slots"] if s["slot"] == label), None)
    if match is None:
        return None
    typical = match["median"]
    shown = hero.round_half_up(typical)
    category = hero.category(latest.count, typical)
    return {
        "count": latest.count,
        "slot": label,
        "typical": shown,
        "typical_median": typical,
        "category": category,
        "line": f"Right now: {latest.count} vs typical {shown} ({category})",
    }


def payload(readings: list[hero.Reading], today: date) -> dict:
    weekdays = curves(readings, today)
    latest = max(readings, key=lambda r: r.when) if readings else None
    today_name = WEEKDAY_NAMES[today.weekday()]
    now = compare_now(weekdays.get(today_name), latest, today) if latest else None
    return {
        "exclude_date": today.isoformat(),
        "weekdays": weekdays,
        "now": now,
    }
