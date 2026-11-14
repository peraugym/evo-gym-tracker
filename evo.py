#!/usr/bin/env python3
"""EVO occupancy log: record browser-observed counts (append-only CSV) and analyse quiet slots.
Only real observations; never fabricated. CSV path override: env EVO_CSV."""
import argparse, csv, fcntl, os, sys, statistics as st
from datetime import datetime, timezone, timedelta, date
from zoneinfo import ZoneInfo
VIE = ZoneInfo("Europe/Vienna")
CSV = os.environ.get("EVO_CSV") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "observations.csv")
F = ["observed_utc","observed_vienna","weekday","club","count","status","source","source_timestamp","note"]
OPEN, CLOSE = 6, 23                                   # documented daily 06:00-23:00 (last hourly slot 22)
START = datetime(2026, 11, 7, 10, tzinfo=VIE)         # first genuine sample (hourly cadence)
SWITCH = datetime(2026, 11, 7, 10, 30, tzinfo=VIE)    # cadence changed to every 15 min from here
CADENCE = [(START, 60), (SWITCH, 15)]                 # (from, minutes): explicit schedule metadata
DAYS = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]

def parse_at(s):
    if not s: return datetime.now(timezone.utc)
    t = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None: sys.exit("error: --at needs a timezone (e.g. Z or +01:00)")
    return t.astimezone(timezone.utc)

def slot_key(v): return v.strftime("%Y-%m-%d %H:") + f"{v.minute//15*15:02d}"   # 15-min bucket
def hour_key(v): return v.strftime("%Y-%m-%d %H")

def record(a):
    t = parse_at(a.at); v = t.astimezone(VIE)
    if a.status == "ok":
        if a.count is None or not (0 <= a.count <= 1000): sys.exit("error: status ok needs --count 0-1000")
    elif a.count is not None: sys.exit("error: --count only allowed with status ok")
    with open(CSV, "a+", newline="") as f:
        fcntl.flock(f, fcntl.LOCK_EX)                 # lock covers duplicate check + append
        f.seek(0); rows = list(csv.DictReader(f))
        same = [r for r in rows if r["club"] == a.club and slot_key(datetime.fromisoformat(r["observed_vienna"])) == slot_key(v)]
        if any(r["status"] == "ok" for r in same) or (a.status != "ok" and same):
            sys.exit(f"error: duplicate for {a.club} bucket {slot_key(v)} Vienna")
        w = csv.DictWriter(f, F)
        if not rows and f.tell() == 0: w.writeheader()
        w.writerow(dict(observed_utc=t.isoformat(), observed_vienna=v.isoformat(), weekday=DAYS[v.weekday()],
            club=a.club, count="" if a.count is None else a.count, status=a.status, source=a.source,
            source_timestamp=a.source_timestamp or "", note=a.note or ""))
        f.flush(); os.fsync(f.fileno())
    print(f"recorded {a.club} {a.status} {'' if a.count is None else a.count} at {v:%Y-%m-%d %H:%M %Z} Vienna")

def expected_slots(now):
    """Expected keys: hourly ('YYYY-MM-DD HH') before SWITCH, quarter-hour buckets from SWITCH; 06:00<=t<23:00.
    Collection has no end date; coverage is computed through `now`."""
    end = now.astimezone(VIE); out = []
    d = START.date()
    while d <= end.date():
        for h in range(OPEN, CLOSE):
            for m in (0, 15, 30, 45):
                s = datetime(d.year, d.month, d.day, h, m, tzinfo=VIE)
                if s < START or s > end: continue
                if s < SWITCH:
                    if m == 0: out.append(("h", hour_key(s)))
                else: out.append(("q", slot_key(s)))
        d += timedelta(days=1)
    return out

def keys_for(v):
    return ("h", hour_key(v)) if v < SWITCH else ("q", slot_key(v))

def table(rows, slot, min_days, title):
    s = {}
    for r in rows:
        v = datetime.fromisoformat(r["observed_vienna"])
        m = (v.hour*60 + v.minute)//slot*slot
        s.setdefault((v.weekday(), m), {}).setdefault(v.date(), []).append(int(r["count"]))
    out = []
    for (d, m), byday in sorted(s.items()):
        daily = [st.median(c) for c in byday.values()]           # one value per date: reads within a day are correlated
        q = st.quantiles(daily, n=4, method="inclusive") if len(daily) > 1 else [daily[0]]*3
        out.append((d, m, st.median(daily), q[0], q[2], sum(map(len, byday.values())), len(daily)))
    print(f"\n== {title} ({slot}-min slots) ==  median/IQR are across distinct dates (per-date median first);")
    print(f"   reads = all samples (quarter-hour reads on one day are correlated, not independent); eligible = >= {min_days} dates")
    print("day  slot   median  IQR(dates)   reads dates eligible")
    for d, m, med, lo, hi, n, days in out:
        print(f"{DAYS[d]}  {m//60:02d}:{m%60:02d}  {med:6.1f}  {lo:5.1f}-{hi:5.1f}  {n:5d} {days:5d}  {'yes' if days>=min_days else 'no'}")
    good = sorted([o for o in out if o[6] >= min_days], key=lambda o: (o[2], o[4]))[:10]
    print("Quietest eligible slots (observed history, not a prediction):" if good else "No slot has sufficient dates for comparison yet.")
    for d, m, med, lo, hi, n, days in good:
        print(f"  {DAYS[d]} {m//60:02d}:{m%60:02d} median {med} (IQR {lo}-{hi}, {days} dates, {n} reads)")

def analyse(a):
    rows = [r for r in csv.DictReader(open(CSV))] if os.path.exists(CSV) else []
    rows = [r for r in rows if r["club"] == a.club]
    now = parse_at(a.now)
    exp = expected_slots(now); e = set(exp); ok_s, fail_s = set(), set()
    for r in rows:
        k = keys_for(datetime.fromisoformat(r["observed_vienna"]))
        (ok_s if r["status"] == "ok" else fail_s).add(k)
    succ = len(ok_s & e); err = len((fail_s - ok_s) & e)
    print(f"Coverage {START:%Y-%m-%d %H:%M} to {now.astimezone(VIE):%Y-%m-%d %H:%M} Vienna "
          f"(hourly before {SWITCH:%H:%M} on {SWITCH:%Y-%m-%d}, then every 15 min; 06:00-23:00, no end date): "
          f"expected {len(exp)}, successes {succ}, failures {err}, missing {len(exp)-succ-err}, "
          f"coverage {100*succ/len(exp) if exp else 0:.1f}%, distinct dates with data "
          f"{len({r['observed_vienna'][:10] for r in rows if r['status']=='ok'})}")
    ok = [r for r in rows if r["status"] == "ok" and OPEN <= datetime.fromisoformat(r["observed_vienna"]).hour < CLOSE]
    if not ok: print("No valid samples yet; nothing to analyse."); return
    table(ok, a.slot, a.min_days, "Detail")
    if a.slot != 60: table(ok, 60, a.min_days, "Hourly summary")

p = argparse.ArgumentParser(); sp = p.add_subparsers(dest="cmd", required=True)
r = sp.add_parser("record"); r.add_argument("--count", type=int); r.add_argument("--status", default="ok", choices=["ok","unreadable","stale","error"])
r.add_argument("--club", default="EVO Bruno-Marek-Allee"); r.add_argument("--at", help="ISO time with zone; default now")
r.add_argument("--source", default="browser:visits.evofitness.at"); r.add_argument("--source-timestamp"); r.add_argument("--note")
z = sp.add_parser("analyse"); z.add_argument("--club", default="EVO Bruno-Marek-Allee"); z.add_argument("--slot", type=int, default=15, choices=[15,30,60])
z.add_argument("--min-days", type=int, default=3); z.add_argument("--now", help="override current time (testing)")
a = p.parse_args(); record(a) if a.cmd == "record" else analyse(a)
