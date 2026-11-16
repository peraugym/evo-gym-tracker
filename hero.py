#!/usr/bin/env python3
"""Latest-reading hero for the static dashboard.

Edit the constants below to change the colour bands and the
"compared with usual" wording. Collection and the CSV are not involved.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

# green if count < LOAD_GREEN_BELOW
# amber if LOAD_GREEN_BELOW <= count <= LOAD_AMBER_UP_TO
# red if count > LOAD_AMBER_UP_TO
LOAD_GREEN_BELOW = 15
LOAD_AMBER_UP_TO = 30

# d = count - typical
# "about usual" when abs(d) < max(USUAL_ABOUT_ABS, USUAL_ABOUT_FRAC * typical)
# "way quieter/busier" when abs(d) >= max(USUAL_WAY_ABS, USUAL_WAY_FRAC * typical)
# otherwise "quieter than usual" / "busier than usual"
USUAL_ABOUT_ABS = 3
USUAL_ABOUT_FRAC = 0.20
USUAL_WAY_ABS = 8
USUAL_WAY_FRAC = 0.50

# Same weekday + hour once this many distinct past dates exist; otherwise all days.
WEEKDAY_MIN_DATES = 3

WEEKDAY_PLURAL = (
    "Mondays",
    "Tuesdays",
    "Wednesdays",
    "Thursdays",
    "Fridays",
    "Saturdays",
    "Sundays",
)


@dataclass(frozen=True)
class Reading:
    when: datetime  # Europe/Vienna
    count: int


def load_band(count: int) -> str:
    if count < LOAD_GREEN_BELOW:
        return "green"
    if count <= LOAD_AMBER_UP_TO:
        return "amber"
    return "red"


def trend(current: int, previous: int | None) -> str | None:
    """Up, down, or flat versus the previous ok reading. None if there is no previous."""
    if previous is None:
        return None
    if current > previous:
        return "up"
    if current < previous:
        return "down"
    return "flat"


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2


def round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def category(count: int, typical: float) -> str:
    delta = count - typical
    distance = abs(delta)
    about = max(USUAL_ABOUT_ABS, USUAL_ABOUT_FRAC * typical)
    way = max(USUAL_WAY_ABS, USUAL_WAY_FRAC * typical)
    if distance < about:
        return "about usual"
    strong = distance >= way
    if delta < 0:
        return "way quieter than usual" if strong else "quieter than usual"
    return "way busier than usual" if strong else "busier than usual"


def _pack(values: list[int], count: int, scope: str, scope_label: str) -> dict:
    typical = _median([float(v) for v in values])
    shown = round_half_up(typical)
    label = category(count, typical)
    if scope == "weekday":
        line = f"Usually ~{shown} at this hour on {scope_label} · {label}"
    else:
        line = f"Usually ~{shown} at this hour, all days · {label}"
    return {
        "n": shown,
        "median": typical,
        "scope": scope,
        "scope_label": scope_label,
        "category": label,
        "line": line,
    }


def typical_for(past: list[Reading], latest: Reading) -> dict | None:
    """Median of earlier ok readings in the latest reading's Vienna clock hour.

    Uses that weekday once WEEKDAY_MIN_DATES distinct past dates exist.
    Otherwise uses every past reading in the hour. None when the hour has no past readings.
    """
    hour = latest.when.hour
    earlier = [r for r in past if r.when < latest.when and r.when.hour == hour]
    if not earlier:
        return None
    same_day = [r for r in earlier if r.when.weekday() == latest.when.weekday()]
    dates = {r.when.date() for r in same_day}
    if len(dates) >= WEEKDAY_MIN_DATES:
        return _pack(
            [r.count for r in same_day],
            latest.count,
            "weekday",
            WEEKDAY_PLURAL[latest.when.weekday()],
        )
    return _pack([r.count for r in earlier], latest.count, "all", "all days")


def summarize(readings: list[Reading]) -> dict | None:
    """Hero payload for a time-ordered list of ok readings. The last one is latest."""
    if not readings:
        return None
    ordered = sorted(readings, key=lambda r: r.when)
    latest = ordered[-1]
    previous = ordered[-2] if len(ordered) > 1 else None
    usual = typical_for(ordered[:-1], latest)
    return {
        "count": latest.count,
        "band": load_band(latest.count),
        "trend": trend(latest.count, None if previous is None else previous.count),
        "time_vienna": latest.when.isoformat(),
        "time_label": f"{latest.when.strftime('%a')} {latest.when.day} {latest.when.strftime('%b')}, {latest.when:%H:%M %Z}",
        "usual": usual,
    }
