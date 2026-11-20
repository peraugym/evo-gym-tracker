# EVO gym occupancy tracker

Public log of how many members are in **EVO Bruno-Marek-Allee** (Vienna). Each reading comes from the rendered public page [visits.evofitness.at](https://visits.evofitness.at/) — the live sentence “Momentan sind N Mitglieder im Club” (or the English “N people in the club right now”). This is not an official EVO feed. The page’s forecast bars are ignored. A missed slot stays empty; counts are never guessed or backfilled.

Dashboard: [https://peraugym.github.io/evo-gym-tracker/](https://peraugym.github.io/evo-gym-tracker/)

Pages is built from this workflow. Source is **GitHub Actions** (`build_type: workflow`).

## How a run works

[`.github/workflows/collect.yml`](.github/workflows/collect.yml) runs on GitHub-hosted runners.

- **Schedule:** `0,15,30,45 4-21 * * *` (UTC). That span covers 06:00–22:45 Europe/Vienna in both CET (UTC+1) and CEST (UTC+2). The script checks the actual Vienna time and skips anything outside 06:00–22:45, so the extra UTC runs at the edges do not record a row.
- **Manual:** Actions → Collect occupancy → Run workflow.
- Changing `.github/workflows/collect.yml` on `main` also starts one run. Commits the workflow pushes with `GITHUB_TOKEN` do not.
- Headless Chrome opens the public page, selects Bruno-Marek-Allee in the `location-select` dropdown, and reads `location-now`. The CSV stores the fetch time, not the time the cron was supposed to fire (scheduled runs are often a few minutes late).
- One row per club per Vienna quarter-hour. A success sticks. A failure can be replaced by one later success in the same slot. A second failure is not written.
- The row is committed to `observations.csv` on `main`. If the push loses a race, the job rebases onto `main` and applies the same reading again (it will not duplicate a slot). Runs do not overlap (`concurrency` group `evo-occupancy`).
- When today’s count crosses from 10 or more to under 10, one line is appended to `alerts.log`. The first successful reading of a day never alerts. Failures do not alert and do not reset the baseline. Something outside this repo can read `alerts.log` from `main`.
- The dashboard is rebuilt from `observations.csv` and deployed to GitHub Pages from this workflow. The day chart shades the usual range (mean ± 2 standard deviations of past days in each 15-minute slot). Same-weekday history is used once that weekday has 3 past days; until then the shade uses every past day. This page updates when it is reloaded.

Collection has no end date.

## Files

| File | Role |
| --- | --- |
| `observations.csv` | Append-only history. Columns: `observed_utc`, `observed_vienna`, `weekday`, `club`, `count`, `status`, `source`, `source_timestamp`, `note`. |
| `alerts.log` | Append-only quiet-gym alerts: `<iso> count=N time=HH:MM webhook=pending`. |
| `fetch_count.js` | The page reader (puppeteer-core + system Chrome). |
| `evo.py` | CSV append, quarter-hour dedupe, and a text coverage summary. |
| `collect.py` | Window check, fetch, record, alert. |
| `dashboard/` | Static page (`index.html`, `app.js`, `style.css`). `data.json` is generated at deploy time, including the typical weekday curve. |
| `typical.py` | Mean ± 2 standard deviations for each 15-minute slot, used by the day-view overlay. |

A failed fetch is a row with status `unreadable` or `error` and an empty count.

## Local check

```bash
npm ci
python3 -m unittest test_collect.py test_hero.py test_typical.py -v
CHROME_PATH=/usr/bin/google-chrome python3 collect.py --dry-run
```

`--dry-run` prints the live count and does not write the CSV.
