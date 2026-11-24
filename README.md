# MemoryGate

Evaluating memory updates for SQL agents: memories distilled from past tasks only take effect after
passing a regression gate. This repo is at **week 1 (feasibility)**: model adapter, execution grader,
frozen data split with a sealed test set, and runs for the no-memory and official-hint groups.

## Setup

```bash
uv sync
uv run pytest -q
```

### Data (BIRD dev)

Download the BIRD dev set from the official site (https://bird-bench.github.io/), unzip, and place it so that:

```
data/raw/bird_dev/dev.json
data/raw/bird_dev/dev_databases/<db_id>/<db_id>.sqlite
```

`data/raw/` and `data/sealed/` are git-ignored.

### Model access

Set `[model]` in `configs/week1.toml`, and verify the model ID and `[pricing]` before any real run.

- Vertex AI (`provider = "vertex"`): `gcloud auth application-default login`, then `export GOOGLE_CLOUD_PROJECT=<project-id>`.
- AI Studio (`provider = "aistudio"`): `export GEMINI_API_KEY=...`.
- Offline (`provider = "fake"`): no network, for dry runs.

`[budget]` caps calls and USD per invocation; every call is logged to `runs/<name>/usage.jsonl`.

## Week-1 commands

```bash
# 1. freeze the split once (learn 50% / val 20% / test 30%, per database; test is sealed)
uv run memorygate split

# 2. smoke test on 20 dev items
uv run memorygate run --condition no_memory --limit 20 --name smoke

# 3. the two reference groups on dev items (learn+val), twice each to measure run-to-run noise
uv run memorygate run --condition no_memory --limit 200 --name nomem_r1
uv run memorygate run --condition no_memory --limit 200 --name nomem_r2
uv run memorygate run --condition evidence  --limit 200 --name evid_r1

# 4. compare
uv run memorygate compare nomem_r1 nomem_r2   # flip rate = noise floor
uv run memorygate compare nomem_r1 evid_r1    # headroom memory could fill
```

Runs are resumable: re-running the same `--name` skips finished items.

## Rules this code enforces

- The test split cannot be loaded without `unseal=True`; its ids live in `data/sealed/` and are hash-checked.
- A split, once written, cannot be overwritten.
- Gold queries that fail are excluded from accuracy (`gold_error`), not counted as wrong.
- Accuracy follows the BIRD rule (row sets equal); a stricter multiset match is also recorded.
