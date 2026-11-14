#!/usr/bin/env bash
# Apply reading.json onto the latest main and push.
# Resets to origin/main before each attempt so a rejected push cannot
# duplicate a quarter-hour that another run already wrote.
set -euo pipefail

READING="${1:-reading.json}"
cd "$(dirname "$0")/.."

if [[ ! -f "$READING" ]]; then
  echo "no reading file ($READING); nothing to commit"
  exit 0
fi

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

commit_if_needed() {
  git fetch origin main
  git checkout main
  git reset --hard origin/main
  python3 collect.py --apply "$READING"
  if git diff --quiet -- observations.csv alerts.log; then
    echo "nothing to commit"
    return 2
  fi
  git add -- observations.csv alerts.log
  local extra
  extra="$(git diff --cached --name-only | grep -v -E '^(observations\.csv|alerts\.log)$' || true)"
  if [[ -n "$extra" ]]; then
    echo "refusing to commit unexpected files:"
    echo "$extra"
    return 1
  fi
  if [[ ! -s .commit-message.txt ]]; then
    echo "missing commit message"
    return 1
  fi
  git commit -m "$(cat .commit-message.txt)"
  echo "committed $(git rev-parse --short HEAD): $(cat .commit-message.txt)"
  return 0
}

for i in 1 2 3 4 5 6; do
  set +e
  commit_if_needed
  rc=$?
  set -e
  if [[ "$rc" -eq 2 ]]; then
    exit 0
  fi
  if [[ "$rc" -ne 0 ]]; then
    echo "apply/commit failed (rc=$rc)"
    exit "$rc"
  fi
  if git push origin HEAD:main; then
    echo "pushed $(git rev-parse --short HEAD) to main"
    exit 0
  fi
  echo "push rejected, retry $i"
  sleep $((i * 2))
done

echo "push failed after retries"
exit 1
