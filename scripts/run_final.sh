#!/usr/bin/env bash
# Final runs on the sealed test split (see reports/design_freeze.md). One lane per order, then the report.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p runs/final runs/logs

run_one() {  # order group
  local o=$1 g=$2 name="final/o$1_$2"
  for attempt in $(seq 1 30); do
    until curl -s -m 10 -o /dev/null https://oauth2.googleapis.com/; do sleep 30; done
    if uv run memorygate rounds --final --eval-every 4 --group "$g" --order-seed "$o" --name "$name" --workers 4 \
        >> "runs/logs/final_o$1_$2.log" 2>&1; then
      echo "$(date +%T) $name finished (attempt $attempt)"; return 0
    fi
    echo "$(date +%T) $name crashed (attempt $attempt), retrying in 60s"; sleep 60
  done
  echo "$(date +%T) $name GAVE UP"
}

lane() { for g in no_memory raw consolidate gate_accept gate_reject; do run_one "$1" "$g"; done; }

for o in ${@:-0 1 2}; do lane "$o" & done
wait
uv run memorygate rounds-report --runs runs/final --out reports/final_rounds.md
uv run memorygate final-report
echo "== final done: $(date) =="
