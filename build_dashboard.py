#!/usr/bin/env python3
"""Build the static dashboard from observations.csv. Does not publish anywhere."""
from __future__ import annotations

import argparse
import csv
import fcntl
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.environ.get("EVO_CSV") or os.path.join(HERE, "observations.csv")
DASH = os.path.join(HERE, "dashboard")
CLUB = "EVO Bruno-Marek-Allee"
VIE = ZoneInfo("Europe/Vienna")
STATUSES = ("ok", "unreadable", "stale", "error")


def load(src: str) -> list[dict]:
    with open(src, newline="") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_SH)
        except OSError:
            pass
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        if r.get("club") != CLUB:
            continue
        try:
            t = datetime.fromisoformat(r["observed_utc"]).astimezone(timezone.utc)
        except Exception:
            continue
        ok = r.get("status") == "ok"
        try:
            c = int(r["count"]) if ok else None
        except Exception:
            continue
        if ok and not (0 <= c <= 1000):
            continue
        status = r["status"] if r.get("status") in STATUSES else "error"
        out.append({"t": t.strftime("%Y-%m-%dT%H:%M:%SZ"), "c": c, "s": status,
                    "vienna": t.astimezone(VIE).isoformat()})
    out.sort(key=lambda x: x["t"])
    return out


def build(now: datetime | None = None, src: str = SRC, site: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    site = site or os.path.join(HERE, "site")
    obs = load(src) if os.path.exists(src) else []
    data = {
        "schema": 1,
        "club": CLUB,
        "generated_utc": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "timezone": "Europe/Vienna",
        "cadence": {
            "hourly_from": "2026-11-07T09:00:00Z",
            "quarter_hour_from": "2026-11-07T09:30:00Z",
            "until": None,
            "open_hour": 6,
            "close_hour": 23,
        },
        "source": "Browser readings of the public page visits.evofitness.at (rendered page, not an official EVO feed)",
        "observations": [{"t": o["t"], "c": o["c"], "s": o["s"]} for o in obs],
    }
    os.makedirs(site, exist_ok=True)
    for name in ("index.html", "app.js", "style.css"):
        src_file = os.path.join(DASH, name)
        if os.path.exists(src_file):
            shutil.copyfile(src_file, os.path.join(site, name))
    csv_body = "observed_utc,observed_vienna,count,status\n" + "".join(
        f"{o['t']},{o['vienna']},{'' if o['c'] is None else o['c']},{o['s']}\n" for o in obs
    )
    _atomic(site, "data.json", json.dumps(data, separators=(",", ":")))
    _atomic(site, "observations.csv", csv_body)
    nojekyll = os.path.join(site, ".nojekyll")
    if not os.path.exists(nojekyll):
        with open(nojekyll, "w") as f:
            f.write("")
    return data


def _atomic(site: str, name: str, body: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=site, prefix=".tmp-")
    with os.fdopen(fd, "w") as f:
        f.write(body)
    os.chmod(tmp, 0o644)
    os.replace(tmp, os.path.join(site, name))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=os.path.join(HERE, "site"))
    ap.add_argument("--now", help="override generated time, ISO-8601")
    ap.add_argument("--src", default=SRC)
    args = ap.parse_args(argv)
    now = datetime.fromisoformat(args.now.replace("Z", "+00:00")) if args.now else None
    data = build(now, src=args.src, site=args.out)
    print(f"built {len(data['observations'])} observations -> {args.out}/data.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
