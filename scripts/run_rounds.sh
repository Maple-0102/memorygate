#!/usr/bin/env bash
# Main round-based runs: 5 groups x 3 task orders.
# One lane per order runs its groups one after another (gated groups first); the 3 lanes run in parallel.
# Each group run is retried until it finishes (rate-limit crashes resume from the last finished round).
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p runs/logs

run_one() {  # order group
  local o=$1 g=$2 name="o$1_$2"
  for attempt in $(seq 1 30); do
    # offline (sleep / Wi-Fi drop): wait for the network without spending an attempt
    until curl -s -m 10 -o /dev/null https://oauth2.googleapis.com/; do sleep 30; done
    if uv run memorygate rounds --group "$g" --order-seed "$o" --name "$name" --workers 4 >> "runs/logs/$name.log" 2>&1; then
      echo "$(date +%T) $name finished (attempt $attempt)"; return 0
    fi
    echo "$(date +%T) $name crashed (attempt $attempt), retrying in 60s"; sleep 60
  done
  echo "$(date +%T) $name GAVE UP"
}

lane() {
  for g in gate_accept gate_reject consolidate raw no_memory; do run_one "$1" "$g"; done
}

for o in ${@:-0 1 2}; do lane "$o" & done
wait
echo "== all done: $(date) =="
