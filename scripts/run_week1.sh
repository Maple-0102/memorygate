#!/usr/bin/env bash
# Week-1 feasibility runs. Resumable: re-running skips finished items.
# Needs GOOGLE_CLOUD_PROJECT and Application Default Credentials.
set -euo pipefail
cd "$(dirname "$0")/.."
run() { uv run memorygate run "$@" | grep -E '"(accuracy|n|usd|stopped)"' || true; }

echo "== no-memory, twice (noise floor) =="
run --condition no_memory --split learn,val --name nomem_r1
run --condition no_memory --split learn,val --name nomem_r2

echo "== official hints (reference group: is there anything to learn?) =="
run --condition evidence --split learn,val --name evid_r1

echo "== raw experience retrieval on val, bank = learn (+ agent's own attempts from nomem_r1) =="
run --condition raw_retrieval --split val --bank-run nomem_r1 --name raw_k3
echo "== placebo: k random same-db experiences =="
run --condition shuffled --split val --bank-run nomem_r1 --name shuf_k3
echo "== reproducibility: two different random halves of the bank =="
run --condition raw_retrieval --split val --bank-run nomem_r1 --bank-frac 0.5 --bank-seed 1 --name raw_k3_halfA
run --condition raw_retrieval --split val --bank-run nomem_r1 --bank-frac 0.5 --bank-seed 2 --name raw_k3_halfB

echo "== done =="
