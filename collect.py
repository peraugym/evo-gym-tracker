#!/usr/bin/env python3
"""One-shot collector for the public EVO visits page.

Reads the live member sentence via fetch_count.js (headless Chrome on
https://visits.evofitness.at/). Never calls an EVO API, never reads the
forecast bars, and never invents a count. A failed fetch is recorded as a
failure. Runs outside 06:00–22:45 Europe/Vienna are skipped.

  python3 collect.py --dry-run
  python3 collect.py --fetch-only     # write reading.json, do not touch the CSV
  python3 collect.py --apply reading.json
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

HERE = os.path.dirname(os.path.abspath(__file__))
VIE = ZoneInfo("Europe/Vienna")
CLUB = "EVO Bruno-Marek-Allee"
CLUB_MATCH = "Bruno-Marek-Allee"
OPEN_MIN = 6 * 60
LAST_MIN = 22 * 60 + 45
QUIET_THRESHOLD = 10
SOURCE = "headless-chrome:visits.evofitness.at"
FETCH_TIMEOUT_SEC = int(os.environ.get("EVO_FETCH_TIMEOUT_SEC", "180"))
RETRY_WAIT_SEC = int(os.environ.get("EVO_RETRY_WAIT_SEC", "60"))
EVO_PY = os.path.join(HERE, "evo.py")
FETCH_JS = os.path.join(HERE, "fetch_count.js")


def csv_path() -> str:
    return os.environ.get("EVO_CSV") or os.path.join(HERE, "observations.csv")


def alerts_path() -> str:
    return os.environ.get("EVO_ALERTS_LOG") or os.path.join(HERE, "alerts.log")


def reading_path() -> str:
    return os.environ.get("EVO_READING") or os.path.join(HERE, "reading.json")


def status_path() -> str:
    return os.path.join(HERE, ".collect-status.json")


def commit_message_path() -> str:
    return os.path.join(HERE, ".commit-message.txt")


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def in_collect_window(v: datetime) -> bool:
    """True when Vienna local time is within 06:00–22:45 inclusive, any date."""
    v = v.astimezone(VIE)
    minutes = v.hour * 60 + v.minute
    return OPEN_MIN <= minutes <= LAST_MIN


def slot_key(v: datetime) -> str:
    v = v.astimezone(VIE)
    return v.strftime("%Y-%m-%d %H:") + f"{v.minute // 15 * 15:02d}"


def load_rows(path: str | None = None) -> list[dict]:
    path = path or csv_path()
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def slot_rows(observed: datetime, rows: list[dict] | None = None) -> list[dict]:
    key = slot_key(observed)
    out = []
    for r in rows if rows is not None else load_rows():
        if r.get("club") != CLUB:
            continue
        try:
            if slot_key(datetime.fromisoformat(r["observed_vienna"])) == key:
                out.append(r)
        except (KeyError, ValueError):
            continue
    return out


def decide(now: datetime, rows: list[dict] | None = None) -> str:
    """skip (outside window), duplicate (slot already has a success), or fetch."""
    now = now.astimezone(VIE)
    if not in_collect_window(now):
        return "skip"
    if any(r.get("status") == "ok" for r in slot_rows(now, rows)):
        return "duplicate"
    return "fetch"


def last_success_same_day(rows: list[dict], club: str, day, before: datetime | None = None) -> dict | None:
    """Most recent successful same-day reading, strictly before `before` when given.

    Failures are ignored. Other days are ignored, so the first success of a day
    never counts as a crossing.
    """
    best = None
    best_t = None
    before_v = before.astimezone(VIE) if before is not None else None
    for r in rows:
        if r.get("club") != club or r.get("status") != "ok":
            continue
        try:
            t = datetime.fromisoformat(r["observed_vienna"])
            count = int(r["count"])
        except (KeyError, TypeError, ValueError):
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=VIE)
        t = t.astimezone(VIE)
        if t.date() != day:
            continue
        if before_v is not None and t >= before_v:
            continue
        if best_t is None or t > best_t:
            best, best_t = {**r, "count": count, "t": t}, t
    return best


def is_quiet_crossing(previous_count: int | None, new_count: int, threshold: int = QUIET_THRESHOLD) -> bool:
    """True only when the previous same-day success was >= threshold and the new count is below it."""
    if previous_count is None:
        return False
    return previous_count >= threshold and new_count < threshold


def maybe_alert(count: int, observed: datetime, rows: list[dict] | None = None) -> bool:
    """Append one alerts.log line on a same-day >=10 to <10 crossing. Returns True if appended."""
    observed = observed.astimezone(VIE)
    rows = rows if rows is not None else load_rows()
    prev = last_success_same_day(rows, CLUB, observed.date(), before=observed)
    prev_count = None if prev is None else int(prev["count"])
    if not is_quiet_crossing(prev_count, count):
        return False
    hhmm = observed.strftime("%H:%M")
    day = observed.date().isoformat()
    path = alerts_path()
    existing = ""
    if os.path.exists(path):
        with open(path) as f:
            existing = f.read()
    # Don't double-append the same Vienna clock time if a push retry re-applies the reading.
    if f"count={count} time={hhmm}" in existing and day in existing:
        for line in existing.splitlines():
            if line.startswith(day) and f"count={count} time={hhmm}" in line:
                return False
    line = f"{datetime.now(VIE).isoformat()} count={count} time={hhmm} webhook=pending\n"
    with open(path, "a") as f:
        f.write(line)
    print(f"ALERT {line.strip()}", flush=True)
    return True


def write_status(status: dict) -> None:
    with open(status_path(), "w") as f:
        json.dump(status, f, indent=2, ensure_ascii=False)
        f.write("\n")
    gh = os.environ.get("GITHUB_OUTPUT")
    if gh:
        with open(gh, "a") as f:
            f.write(f"deploy={'true' if status.get('deploy') else 'false'}\n")
            f.write(f"action={status.get('action', '')}\n")
    print(json.dumps(status, ensure_ascii=False), flush=True)


def _run_evo(args: list[str]) -> tuple[str, str]:
    p = subprocess.run(
        [sys.executable, EVO_PY, *args],
        cwd=HERE, capture_output=True, text=True, env=os.environ.copy(),
    )
    out = ((p.stdout or "") + (p.stderr or "")).strip()
    if p.returncode == 0:
        return "written", out
    if "duplicate" in out.lower():
        return "duplicate", out
    return "rejected", out or f"exit {p.returncode}"


def commit_message(observed: datetime, count, status: str, alerted: bool) -> str:
    observed = observed.astimezone(VIE)
    if status == "ok":
        msg = f"record {count} at {observed:%Y-%m-%d %H:%M %Z}"
        if alerted:
            msg += ", quiet alert"
        return msg
    return f"record {status} at {observed:%Y-%m-%d %H:%M %Z}"


def apply_payload(payload: dict) -> dict:
    """Append one stored reading. Idempotent per quarter-hour slot. Does not fetch."""
    observed = datetime.fromisoformat(str(payload["observed"]).replace("Z", "+00:00"))
    if observed.tzinfo is None:
        raise SystemExit("reading has no timezone")
    observed_utc = observed.astimezone(timezone.utc)
    observed_vie = observed_utc.astimezone(VIE)
    at = observed_utc.isoformat()
    if payload.get("ok"):
        count = int(payload["count"])
        if not (0 <= count <= 1000):
            return {"outcome": "rejected", "message": f"count out of range: {count}", "alerted": False,
                    "observed_vienna": observed_vie.isoformat(), "slot": slot_key(observed_vie),
                    "count": count, "status": "ok"}
        note = payload.get("note") or ""
        outcome, msg = _run_evo([
            "record", "--count", str(count), "--status", "ok", "--at", at,
            "--source", SOURCE, "--note", note, "--club", CLUB,
        ])
        alerted = False
        if outcome == "written":
            alerted = maybe_alert(count, observed_vie)
        if outcome == "written":
            with open(commit_message_path(), "w") as f:
                f.write(commit_message(observed_vie, count, "ok", alerted) + "\n")
        return {"outcome": outcome, "message": msg, "alerted": alerted,
                "observed_vienna": observed_vie.isoformat(), "slot": slot_key(observed_vie),
                "count": count, "status": "ok"}
    status = payload.get("status") if payload.get("status") in ("unreadable", "stale", "error") else "error"
    note = (payload.get("note") or payload.get("error") or "fetch failed")[:300]
    outcome, msg = _run_evo([
        "record", "--status", status, "--at", at,
        "--source", SOURCE, "--note", note, "--club", CLUB,
    ])
    if outcome == "written":
        with open(commit_message_path(), "w") as f:
            f.write(commit_message(observed_vie, None, status, False) + "\n")
    return {"outcome": outcome, "message": msg, "alerted": False,
            "observed_vienna": observed_vie.isoformat(), "slot": slot_key(observed_vie),
            "count": None, "status": status}


def _node() -> str:
    return os.environ.get("NODE") or os.environ.get("NODE_BIN") or "node"


def fetch_once(timeout: int) -> dict:
    """Run fetch_count.js once (the script itself reloads the page one time)."""
    env = os.environ.copy()
    env.setdefault("TZ", "Europe/Vienna")
    env["DISPLAY"] = ""
    env.pop("CHROME_USER_DATA_DIR", None)
    shot = env.get("EVO_FAIL_SHOT")
    if shot:
        os.makedirs(os.path.dirname(os.path.abspath(shot)), exist_ok=True)
    p = subprocess.Popen(
        [_node(), FETCH_JS],
        cwd=HERE, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except Exception:
            p.kill()
        try:
            stdout, stderr = p.communicate(timeout=5)
        except Exception:
            stdout, stderr = "", ""
        return {"ok": False, "error": f"timeout after {timeout}s", "kind": "error", "stderr": stderr or ""}
    if stderr:
        for line in stderr.strip().splitlines():
            print(f"fetch: {line}", flush=True)
    text = (stdout or "").strip().splitlines()
    if not text:
        return {"ok": False, "error": f"empty fetch stdout (exit {p.returncode})", "kind": "error", "stderr": stderr or ""}
    try:
        data = json.loads(text[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": f"bad fetch json: {text[-1][:200]}", "kind": "error", "stderr": stderr or ""}
    data["stderr"] = stderr or ""
    if not data.get("ok"):
        err = data.get("error") or ""
        data["kind"] = "unreadable" if ("sentence" in err or "live sentence" in err or "club" in err) else "error"
        return data
    try:
        n = int(data["count"])
    except (KeyError, TypeError, ValueError):
        return {"ok": False, "error": "missing or invalid count", "kind": "unreadable"}
    sentence = data.get("sentence") or ""
    if not (0 <= n <= 1000):
        return {"ok": False, "error": f"count out of range: {n}", "kind": "unreadable"}
    if str(n) not in sentence:
        return {"ok": False, "error": f"count {n} not in live sentence {sentence!r}", "kind": "unreadable"}
    club_page = data.get("club") or ""
    if CLUB_MATCH not in club_page:
        return {"ok": False, "error": f"wrong club: {club_page}", "kind": "unreadable"}
    data["count"] = n
    return data


def fetch_with_retry(attempts: int) -> tuple[dict, datetime]:
    """Return (fetch dict, fetch-start UTC). Timestamp is the attempt that produced the result."""
    last = {"ok": False, "error": "no attempt", "kind": "error"}
    started = now_utc()
    for i in range(1, attempts + 1):
        started = now_utc()
        print(f"fetch attempt {i}/{attempts} at {started.astimezone(VIE):%Y-%m-%d %H:%M:%S %Z}", flush=True)
        last = fetch_once(FETCH_TIMEOUT_SEC)
        if last.get("ok"):
            return last, started
        print(f"fetch failed attempt {i}/{attempts}: {last.get('error')}", flush=True)
        if i < attempts:
            time.sleep(RETRY_WAIT_SEC)
    return last, started


def _note_for(data: dict) -> str:
    sentence = data.get("sentence") or f"count {data.get('count')}"
    club = data.get("club") or CLUB
    return (
        f"github-actions; headless chrome; public page {data.get('page') or 'https://visits.evofitness.at/'}; "
        f"club '{club}' "
        f"{'already selected' if data.get('alreadySelected') else 'selected from dropdown'}; "
        f"{'1 reload; ' if data.get('reloaded') else ''}"
        f"live {sentence!r}"
        + (f" ({data['title']})" if data.get("title") else "")
    )


def build_reading(data: dict, started: datetime) -> dict:
    reading = {
        "ok": bool(data.get("ok")),
        "observed": started.astimezone(timezone.utc).isoformat(),
        "sentence": data.get("sentence") or "",
        "club_page": data.get("club") or "",
        "error": data.get("error"),
        "httpStatus": (data.get("detail") or {}).get("httpStatus") if isinstance(data.get("detail"), dict) else None,
    }
    if data.get("ok"):
        reading["count"] = int(data["count"])
        reading["status"] = "ok"
        reading["note"] = _note_for(data)
    else:
        kind = data.get("kind") if data.get("kind") in ("unreadable", "error", "stale") else "error"
        reading["status"] = kind
        detail = data.get("detail")
        extra = ""
        if isinstance(detail, dict):
            page = detail.get("page") or {}
            if isinstance(page, dict) and page.get("text"):
                extra = " | page: " + str(page.get("text"))[:240]
            if detail.get("httpStatus"):
                extra = f" | HTTP {detail.get('httpStatus')}" + extra
        reading["note"] = ((data.get("error") or "fetch failed") + extra)[:300]
    return reading


def _base_status(action: str, deploy: bool, **extra) -> dict:
    status = {
        "action": action,
        "deploy": deploy,
        "club": CLUB,
        "page": "https://visits.evofitness.at/",
        "count": None,
        "sentence": None,
        "observed_utc": None,
        "observed_vienna": None,
        "slot": None,
        "outcome": None,
        "alerted": False,
        "error": None,
    }
    status.update(extra)
    return status


def cmd_fetch(attempts: int, dry_run: bool) -> int:
    now = now_utc()
    decision = decide(now)
    vie = now.astimezone(VIE)
    print(f"Vienna {vie:%Y-%m-%d %H:%M:%S %Z} decision={decision}", flush=True)
    # A previous attempt's reading must not be committed after a skip.
    if os.path.exists(reading_path()) and not dry_run:
        os.remove(reading_path())
    if decision == "skip" and not dry_run:
        write_status(_base_status(
            "skipped", False,
            slot=slot_key(vie),
            error=f"outside 06:00-22:45 Europe/Vienna ({vie:%H:%M %Z})",
        ))
        return 0
    if decision == "duplicate" and not dry_run:
        write_status(_base_status(
            "duplicate", True,
            slot=slot_key(vie),
            outcome="duplicate",
            error="slot already has a success; fetch skipped",
        ))
        return 0
    if not os.path.exists(os.environ.get("CHROME_PATH") or "/usr/bin/google-chrome") and not os.environ.get("CHROME_PATH"):
        # fetch_count.js reports a missing binary itself; still try so the error is the real one.
        pass
    data, started = fetch_with_retry(attempts)
    err = data.get("error") or ""
    if not data.get("ok") and any(s in err for s in ("chrome not found", "Cannot find module")):
        write_status(_base_status("error", False, error=err))
        return 1
    if dry_run:
        out = {k: v for k, v in data.items() if k != "stderr"}
        out["observed"] = started.astimezone(timezone.utc).isoformat()
        out["observed_vienna"] = started.astimezone(VIE).isoformat()
        print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
        return 0 if data.get("ok") else 2
    reading = build_reading(data, started)
    with open(reading_path(), "w") as f:
        json.dump(reading, f, indent=2, ensure_ascii=False)
        f.write("\n")
    vie_obs = started.astimezone(VIE)
    if reading["ok"]:
        write_status(_base_status(
            "pending", True,
            count=reading["count"], sentence=reading.get("sentence"),
            observed_utc=reading["observed"], observed_vienna=vie_obs.isoformat(),
            slot=slot_key(vie_obs),
        ))
        return 0
    detail = data.get("detail")
    err = reading.get("note") or reading.get("error")
    write_status(_base_status(
        "pending", True,
        observed_utc=reading["observed"], observed_vienna=vie_obs.isoformat(),
        slot=slot_key(vie_obs), error=err,
        detail=detail if isinstance(detail, dict) else None,
    ))
    return 0


def cmd_apply(path: str) -> int:
    with open(path) as f:
        payload = json.load(f)
    result = apply_payload(payload)
    action = {
        "written": "recorded" if result["status"] == "ok" else "failed",
        "duplicate": "duplicate",
        "rejected": "rejected",
    }.get(result["outcome"], "rejected")
    deploy = action != "rejected"
    status = _base_status(
        action, deploy,
        count=result.get("count"),
        sentence=payload.get("sentence"),
        observed_utc=payload.get("observed"),
        observed_vienna=result.get("observed_vienna"),
        slot=result.get("slot"),
        outcome=result.get("outcome"),
        alerted=result.get("alerted"),
        error=None if result["outcome"] != "rejected" else result.get("message"),
        message=result.get("message"),
    )
    if action == "failed":
        status["error"] = payload.get("error") or payload.get("note")
    write_status(status)
    if result["outcome"] == "rejected":
        return 1
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true", help="fetch and print; do not record")
    g.add_argument("--fetch-only", action="store_true", help="fetch and write reading.json; do not touch the CSV")
    g.add_argument("--apply", metavar="PATH", help="append a stored reading.json to the CSV and alerts.log")
    ap.add_argument("--attempts", type=int, default=None, help="fetch attempts (default 2, or 1 for --dry-run)")
    args = ap.parse_args(argv)
    if args.apply:
        return cmd_apply(args.apply)
    attempts = args.attempts if args.attempts is not None else (1 if args.dry_run else 2)
    if attempts < 1:
        raise SystemExit("--attempts must be >= 1")
    return cmd_fetch(attempts, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
