#!/usr/bin/env bash
# Post-hoc labels for every consolidation run (gated and ungated), one lane per order, then the summary.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p runs/logs

label_one() {
  local name=$1
  for attempt in $(seq 1 30); do
    until curl -s -m 10 -o /dev/null https://oauth2.googleapis.com/; do sleep 30; done
    if uv run memorygate label --run "$name" --workers 4 >> "runs/logs/label_$name.log" 2>&1; then
      echo "$(date +%T) label $name finished (attempt $attempt)"; return 0
    fi
    echo "$(date +%T) label $name crashed (attempt $attempt), retrying in 60s"; sleep 60
  done
  echo "$(date +%T) label $name GAVE UP"
}

lane() { for g in gate_accept gate_reject consolidate; do label_one "o$1_$g"; done; }

for o in ${@:-0 1 2}; do lane "$o" & done
wait
uv run memorygate rounds-report
echo "== labels done: $(date) =="
