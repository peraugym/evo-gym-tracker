#!/usr/bin/env python3
"""Typical occupancy curve for the dashboard overlay.

Same-weekday history is used once that weekday has at least WEEKDAY_MIN_DAYS
past days. Otherwise the curve uses every past day (today excluded). Each
slot's centre is the mean of that slot's per-day values, and the shaded band
is mean ± BAND_SD standard deviations, clipped at 0, once the slot has
BAND_MIN_DAYS values. Short holes of up to MAX_GAP_SLOTS are interpolated;
longer holes stay broken. Collection and the CSV schema are not involved.
"""
from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import hero

VIE = ZoneInfo("Europe/Vienna")
OPEN = time(6, 0)
CLOSE_SLOT = time(22, 45)
SLOT_MINUTES = 15
# A slot is shaded once this many past days have a value there.
BAND_MIN_DAYS = 3
# Half-width of the shaded band, in standard deviations.
BAND_SD = 2
# One sparse weekday is not enough; wait for this many past days.
WEEKDAY_MIN_DAYS = 3
# Missing quarter-hours that may be bridged. 2 slots = up to 30 minutes.
MAX_GAP_SLOTS = 2
# Quietest stretch: six consecutive slots, 90 minutes.
WINDOW_SLOTS = 6

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


def _day_slot_values(readings: list[hero.Reading], exclude: date, weekday: int | None) -> dict[date, dict[time, list[int]]]:
    """Per-day slot samples. weekday=None keeps every past day."""
    by_date: dict[date, dict[time, list[int]]] = defaultdict(lambda: defaultdict(list))
    for r in readings:
        when = r.when.astimezone(VIE) if r.when.tzinfo else r.when.replace(tzinfo=VIE)
        if when.date() == exclude:
            continue
        if weekday is not None and when.weekday() != weekday:
            continue
        slot = slot_of(when)
        if slot is None:
            continue
        by_date[when.date()][slot].append(int(r.count))
    return by_date


def _slot_band(values: list[float]) -> tuple[float, float | None, float | None]:
    """Mean, and mean ± BAND_SD standard deviations clipped at 0.

    The band needs BAND_MIN_DAYS values. Fewer than that returns the mean only.
    """
    center = float(statistics.mean(values))
    if len(values) < BAND_MIN_DAYS:
        return center, None, None
    spread = float(statistics.stdev(values)) * BAND_SD
    return center, max(0.0, center - spread), max(0.0, center + spread)


def _slot_stats(by_date: dict[date, dict[time, list[int]]]) -> list[dict]:
    samples: dict[time, list[float]] = defaultdict(list)
    for slots in by_date.values():
        for hhmm, counts in slots.items():
            # One value per day, so a slot with two readings does not count twice.
            samples[hhmm].append(float(statistics.median(counts)))
    out = []
    for hhmm in slot_times():
        values = samples.get(hhmm)
        if not values:
            continue
        center, lo, hi = _slot_band(values)
        out.append({
            "slot": slot_label(hhmm),
            "n": len(values),
            "mean": center,
            "lo": lo,
            "hi": hi,
        })
    return out


def label_for(weekday: int, n_days: int) -> str:
    name = WEEKDAY_NAMES[weekday]
    plural = WEEKDAY_PLURAL[weekday] if n_days != 1 else name
    return f"Typical {name} (mean of {n_days} past {plural})"


def all_days_label(n_days: int) -> str:
    unit = "day" if n_days == 1 else "days"
    return f"Typical day (all days, mean of {n_days} {unit})"


def _minutes(hhmm: time) -> int:
    return hhmm.hour * 60 + hhmm.minute


def _parse_slot(label: str) -> time:
    hour, minute = label.split(":")
    return time(int(hour), int(minute))


def interpolate_slots(rows: list[dict], max_gap: int = MAX_GAP_SLOTS) -> list[dict]:
    """Fill holes of 1..max_gap quarter-hours. Longer holes stay empty."""
    if not rows:
        return []
    order = [slot_label(t) for t in slot_times()]
    index = {label: i for i, label in enumerate(order)}
    known = {}
    for row in rows:
        item = dict(row)
        item["interpolated"] = False
        known[item["slot"]] = item
    present = sorted(known, key=lambda label: index[label])
    for left_label, right_label in zip(present, present[1:]):
        gap = index[right_label] - index[left_label] - 1
        if gap < 1 or gap > max_gap:
            continue
        left, right = known[left_label], known[right_label]
        for step in range(1, gap + 1):
            weight = step / (gap + 1)
            slot = order[index[left_label] + step]
            filled = {
                "slot": slot,
                "n": 0,
                "mean": left["mean"] * (1 - weight) + right["mean"] * weight,
                "lo": None,
                "hi": None,
                "interpolated": True,
            }
            if left.get("lo") is not None and right.get("lo") is not None:
                filled["lo"] = max(0.0, left["lo"] * (1 - weight) + right["lo"] * weight)
                filled["hi"] = max(0.0, left["hi"] * (1 - weight) + right["hi"] * weight)
            known[slot] = filled
    return [known[label] for label in order if label in known]


def drawable_runs(slots: list[dict]) -> list[list[dict]]:
    """Adjacent 15-minute runs long enough to be a line. Lone slots are omitted."""
    runs: list[list[dict]] = []
    current: list[dict] = []
    for row in slots:
        if current:
            prev = _parse_slot(current[-1]["slot"])
            this = _parse_slot(row["slot"])
            if _minutes(this) - _minutes(prev) != SLOT_MINUTES:
                if len(current) >= 2:
                    runs.append(current)
                current = []
        current.append(row)
    if len(current) >= 2:
        runs.append(current)
    return runs


def curve_for(readings: list[hero.Reading], exclude: date, weekday: int) -> dict | None:
    by_date = _day_slot_values(readings, exclude, weekday)
    n_days = len(by_date)
    if n_days == 0:
        return None
    return {
        "weekday": WEEKDAY_NAMES[weekday],
        "n_days": n_days,
        "label": label_for(weekday, n_days),
        "slots": _slot_stats(by_date),
    }


def all_days_curve(readings: list[hero.Reading], exclude: date) -> dict | None:
    by_date = _day_slot_values(readings, exclude, None)
    n_days = len(by_date)
    if n_days == 0:
        return None
    return {
        "source": "all",
        "n_days": n_days,
        "label": all_days_label(n_days),
        "slots": _slot_stats(by_date),
    }


def curves(readings: list[hero.Reading], exclude: date) -> dict[str, dict]:
    """Raw same-weekday curves, only for weekdays that have past readings."""
    out = {}
    for weekday in range(7):
        curve = curve_for(readings, exclude, weekday)
        if curve is not None:
            out[curve["weekday"]] = curve
    return out


def display_curves(readings: list[hero.Reading], exclude: date) -> dict[str, dict]:
    """Curve to draw for each weekday: same-weekday once it has enough days, else all days."""
    fallback = all_days_curve(readings, exclude)
    out = {}
    for weekday in range(7):
        specific = curve_for(readings, exclude, weekday)
        weekday_days = 0 if specific is None else specific["n_days"]
        if specific is not None and weekday_days >= WEEKDAY_MIN_DAYS:
            chosen = dict(specific)
            chosen["source"] = "weekday"
            chosen["weekday_days"] = weekday_days
        elif fallback is not None:
            chosen = {
                "source": "all",
                "weekday": WEEKDAY_NAMES[weekday],
                "weekday_days": weekday_days,
                "n_days": fallback["n_days"],
                "label": fallback["label"],
                "slots": [dict(row) for row in fallback["slots"]],
            }
        else:
            continue
        chosen["slots"] = interpolate_slots(chosen["slots"])
        out[WEEKDAY_NAMES[weekday]] = chosen
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
    typical = match["mean"]
    shown = hero.round_half_up(typical)
    category = band_category(latest.count, typical, match.get("lo"), match.get("hi"))
    return {
        "count": latest.count,
        "slot": label,
        "typical": shown,
        "typical_mean": typical,
        "lo": match.get("lo"),
        "hi": match.get("hi"),
        "category": category,
        "line": f"Right now: {latest.count} vs typical {shown} ({category})",
    }


def band_category(count: float, mean: float, lo: float | None, hi: float | None) -> str:
    """Place a count against the shaded band, or against the mean when there is no band.

    Above the band is way busier; below it is way quieter; inside it is about usual.
    """
    if lo is not None and hi is not None:
        if count > hi:
            return "way busier than usual"
        if count < lo:
            return "way quieter than usual"
        return "about usual"
    return hero.category(int(count), mean)


def payload(readings: list[hero.Reading], today: date) -> dict:
    weekdays = display_curves(readings, today)
    latest = max(readings, key=lambda r: r.when) if readings else None
    today_name = WEEKDAY_NAMES[today.weekday()]
    now = compare_now(weekdays.get(today_name), latest, today) if latest else None
    return {
        "exclude_date": today.isoformat(),
        "weekdays": weekdays,
        "now": now,
    }


def _hhmm_minutes(label: str) -> int:
    hour, minute = label.split(":")
    return int(hour) * 60 + int(minute)


def _end_label(start: time) -> str:
    total = start.hour * 60 + start.minute + WINDOW_SLOTS * SLOT_MINUTES
    return f"{total // 60:02d}:{total % 60:02d}"


def basis_phrase(curve: dict) -> str:
    """Lower-case 'based on …' clause naming the curve and how many days it uses."""
    n = int(curve.get("n_days") or 0)
    unit = "day" if n == 1 else "days"
    if curve.get("source") == "weekday":
        who = WEEKDAY_PLURAL[WEEKDAY_NAMES.index(curve["weekday"])]
    else:
        who = "all days"
    return f"based on {who}, {n} {unit}"


def candidate_windows(slots: list[dict]) -> list[dict]:
    """Every 90-minute run of 6 present slots, quietest mean first."""
    by_label = {row["slot"]: row["mean"] for row in slots}
    times = slot_times()
    found = []
    for i in range(len(times) - WINDOW_SLOTS + 1):
        chunk = times[i:i + WINDOW_SLOTS]
        means = []
        missing = False
        for moment in chunk:
            key = slot_label(moment)
            if key not in by_label:
                missing = True
                break
            means.append(by_label[key])
        if missing:
            continue
        mean = float(statistics.mean(means))
        found.append({
            "start": slot_label(chunk[0]),
            "end": _end_label(chunk[0]),
            "mean": mean,
            "shown": hero.round_half_up(mean),
        })
    found.sort(key=lambda item: (item["mean"], item["start"]))
    return found


def windows_overlap(left: dict, right: dict) -> bool:
    return abs(_hhmm_minutes(left["start"]) - _hhmm_minutes(right["start"])) < WINDOW_SLOTS * SLOT_MINUTES


def slots_left(local: datetime) -> int:
    """Collected slots still starting at or after the current Vienna quarter-hour."""
    local = local.astimezone(VIE) if local.tzinfo else local.replace(tzinfo=VIE)
    minutes = local.hour * 60 + local.minute
    open_m = OPEN.hour * 60 + OPEN.minute
    close_m = CLOSE_SLOT.hour * 60 + CLOSE_SLOT.minute
    start = open_m if minutes < open_m else minutes - (minutes % SLOT_MINUTES)
    if start > close_m:
        return 0
    return (close_m - start) // SLOT_MINUTES + 1


def earliest_start(local: datetime) -> str | None:
    """First slot that is not already past. None when fewer than 6 slots remain."""
    if slots_left(local) < WINDOW_SLOTS:
        return None
    local = local.astimezone(VIE) if local.tzinfo else local.replace(tzinfo=VIE)
    minutes = local.hour * 60 + local.minute
    open_m = OPEN.hour * 60 + OPEN.minute
    start = open_m if minutes < open_m else minutes - (minutes % SLOT_MINUTES)
    return f"{start // 60:02d}:{start % 60:02d}"


def window_sentence(prefix: str, window: dict, basis: str | None = None) -> str:
    detail = f"typically ~{window['shown']} people"
    if basis:
        detail += f" ({basis})"
    return f"{prefix}: {window['start']}–{window['end']}, {detail}"


def pick_pair(windows: list[dict], earliest: str) -> tuple[dict | None, dict | None]:
    eligible = [item for item in windows if item["start"] >= earliest]
    if not eligible:
        return None, None
    best = eligible[0]
    runner = next((item for item in eligible[1:] if not windows_overlap(best, item)), None)
    return best, runner


def best_time_catalog(curves: dict[str, dict]) -> dict[str, dict]:
    catalog = {}
    for name, curve in curves.items():
        catalog[name] = {
            "source": curve.get("source"),
            "n_days": curve.get("n_days"),
            "basis": basis_phrase(curve),
            "windows": candidate_windows(curve.get("slots") or []),
        }
    return catalog


def _tomorrow_pick(catalog: dict, tomorrow: date) -> dict | None:
    info = catalog.get(WEEKDAY_NAMES[tomorrow.weekday()])
    if not info or not info["windows"]:
        return None
    best = info["windows"][0]
    return {
        "start": best["start"],
        "end": best["end"],
        "shown": best["shown"],
        "line": window_sentence("Tomorrow's quietest window", best, info["basis"]),
        "confidence": info["basis"][:1].upper() + info["basis"][1:],
    }


def recommend(catalog: dict, now: datetime) -> dict:
    """Quietest 90-minute window still ahead, using pre-ranked curves."""
    local = now.astimezone(VIE) if now.tzinfo else now.replace(tzinfo=VIE)
    today = local.date()
    tomorrow = today + timedelta(days=1)
    if not catalog:
        return {"status": "none", "message": "No typical data yet"}
    earliest = earliest_start(local)
    today_info = catalog.get(WEEKDAY_NAMES[today.weekday()])
    if earliest is None:
        result = {"status": "evening", "message": "Not enough time left today"}
        nxt = _tomorrow_pick(catalog, tomorrow)
        if nxt:
            result["tomorrow"] = nxt
        return result
    if not today_info or not today_info["windows"]:
        return {"status": "none", "message": "No typical data yet"}
    best, runner = pick_pair(today_info["windows"], earliest)
    if best is None:
        result = {"status": "none", "message": "No typical data for the rest of today"}
        nxt = _tomorrow_pick(catalog, tomorrow)
        if nxt:
            result["tomorrow"] = nxt
        return result
    result = {
        "status": "today",
        "start": best["start"],
        "end": best["end"],
        "shown": best["shown"],
        "mean": best["mean"],
        "line": window_sentence("Quietest window left today", best, today_info["basis"]),
        "confidence": today_info["basis"][:1].upper() + today_info["basis"][1:],
        "source": today_info["source"],
        "n_days": today_info["n_days"],
    }
    if runner:
        result["runner_up"] = {
            "start": runner["start"],
            "end": runner["end"],
            "shown": runner["shown"],
            "line": window_sentence("Runner-up", runner, None),
        }
    return result


def best_time(curves: dict[str, dict], now: datetime) -> dict:
    catalog = best_time_catalog(curves)
    local = now.astimezone(VIE) if now.tzinfo else now.replace(tzinfo=VIE)
    return {
        "window_slots": WINDOW_SLOTS,
        "by_weekday": catalog,
        "at_build": recommend(catalog, local),
    }
