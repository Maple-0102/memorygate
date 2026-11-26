#!/usr/bin/env bash
# Second-model replication of the week-1 retrieval check (see reports/model2_plan.md).
# Development data only. Resumable: re-running skips finished items.
set -euo pipefail
cd "$(dirname "$0")/.."
C=configs/model2.toml
uv run memorygate -c $C run --condition no_memory --split learn,val --name m2_nomem
uv run memorygate -c $C run --condition raw_retrieval --split val --bank-run m2_nomem --k 3 --name m2_raw_k3
uv run memorygate -c $C run --condition shuffled --split val --bank-run m2_nomem --k 3 --name m2_shuf_k3
echo "== done =="
