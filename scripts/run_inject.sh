#!/usr/bin/env bash
# Harm injection over the gated runs' real updates: one lane per order, two corruption strengths.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p runs/logs
inject_one() {  # run frac
  for attempt in $(seq 1 30); do
    until curl -s -m 10 -o /dev/null https://oauth2.googleapis.com/; do sleep 30; done
    if uv run memorygate inject --run "$1" --frac "$2" --workers 4 >> "runs/logs/inject_$1_$2.log" 2>&1; then
      echo "$(date +%T) inject $1 $2 finished (attempt $attempt)"; return 0
    fi
    echo "$(date +%T) inject $1 $2 crashed (attempt $attempt), retrying in 60s"; sleep 60
  done
  echo "$(date +%T) inject $1 $2 GAVE UP"
}
lane() { for f in 0.25 0.5; do inject_one "o$1_gate_accept" "$f"; done; }
for o in ${@:-0 1 2}; do lane "$o" & done
wait
uv run memorygate inject-report
echo "== injection done: $(date) =="
