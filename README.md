# MemoryGate

**Do memory updates help an LLM agent, and can a regression gate catch the ones that hurt?**

MemoryGate is a controlled experiment on long-term memory for a text-to-SQL agent. The agent answers
questions from the [BIRD](https://bird-bench.github.io/) benchmark over 12 learning rounds. After
each round it updates its memory. Five memory strategies are compared, including two that put every
memory update through a statistical regression gate before it takes effect.

**Answer.** Retrieving past questions with their correct SQL raised held-out execution accuracy from 44.3% to
57.2%. The default-accept gate showed no measurable accuracy gain over ungated consolidation and cost 6.3× as much
in strategy API spend. In a separate development-stage stress test, it blocked 9 of 17 harmful updates.

The design was frozen (commit [`1ec8ccd`](https://github.com/Maple-0102/memorygate/commit/1ec8ccd),
tag `design-freeze`) before the held-out test split was opened. The final runs were done once and evaluated on the
test split after rounds 4, 8 and 12, with round 12 specified in advance as the primary comparison.

Full report (Chinese, 6 pages): [`reports/MemoryGate_report_zh.pdf`](reports/MemoryGate_report_zh.pdf)

## Results on the held-out test split

There are 459 gradable questions from the same 11 BIRD dev databases the agent learned from; one of the
460 sealed questions was excluded because its reference SQL fails. Accuracy is execution accuracy
after 12 learning rounds, averaged over three task orders.

| Memory strategy | Accuracy | vs. no memory |
|---|---|---|
| No memory | 44.3% | — |
| Raw experience: retrieve past questions with their correct SQL | **57.2%** | **+12.9 pp** |
| Consolidated rules: LLM distils lessons from failed attempts each round | 51.0% | +6.7 pp |
| Rules + gate, default accept (reject only on evidence of harm) | 49.5% | +5.2 pp |
| Rules + gate, default reject (accept only on evidence of benefit) | 48.0% | +3.7 pp |

The seven comparisons below were fixed in advance. Each is a paired test per question, after
averaging over the three orders. Δ is in percentage points.

| Comparison | Δ | 95% CI | Holm-adjusted p | Δ in each task order |
|---|---|---|---|---|
| Raw vs. no memory | +12.9 | +9.4 to +16.5 | <0.001 | +12.6 / +13.3 / +12.9 |
| Rules vs. no memory | +6.7 | +3.8 to +9.5 | <0.001 | +5.0 / +7.2 / +7.8 |
| Gate (accept) vs. no memory | +5.2 | +2.4 to +7.9 | 0.001 | +3.7 / +5.0 / +6.8 |
| Gate (reject) vs. no memory | +3.7 | +1.2 to +6.2 | 0.013 | +4.8 / +2.6 / +3.7 |
| Raw vs. rules | +6.2 | +3.4 to +9.1 | <0.001 | +7.6 / +6.1 / +5.0 |
| Gate (accept) vs. rules | −1.5 | −3.3 to +0.2 | 0.089 | −1.3 / −2.2 / −1.1 |
| Gate (reject) vs. rules | −3.0 | −5.0 to −0.9 | 0.013 | −0.2 / −4.6 / −4.1 |

The 95% intervals reflect variation across questions for these completed runs. The per-order column shows how
the observed differences varied across the three task orders.

What this shows:

- **Memory helps.** Every memory strategy beats no memory.
- **Raw experience beats distilled rules by 6.2 pp** at the same retrieval budget (at most 5 items and 1,500 characters per question). The two groups also see different inputs: the raw bank keeps every past question with its correct SQL, while rules are distilled only from failed attempts. So this compares two complete strategies, not the compression step alone.
- **The default-accept gate showed no measurable gain.** It rejected 1 of 36 updates. In the two task orders where it rejected nothing, it still trailed ungated rules by 1.1 and 1.3 pp. That gap can only come from run-to-run variation: the model is not fully deterministic at temperature 0, and two runs diverge from round 0. So this design cannot separate the effect of gate decisions from run-to-run variation.
- **The default-reject gate accepted only 6 of 36 updates** and ended 3.0 pp below ungated rules.
- **Cost.** In the final runs, the default-accept gate's strategy API spend (learning, consolidation and gate checks; evaluation excluded) was 6.3× that of ungated rules: $4.65 vs. $0.74 per 12-round run.

## Development-stage findings

These used development data only. The test split stayed sealed throughout.

- **Week 1: past experience transfers.** On the validation split, retrieving relevant past questions with their correct SQL raised accuracy from 42.7% to 57.0%. Random past questions from the same database added only 3.9 pp. Run-to-run noise: 2.9% of questions switched between correct and incorrect across two identical-prompt runs.
- **No natural update was measurably harmful.** Under the pre-set test, 108 natural updates were labelled on a separate evaluation set and none was significantly harmful. The default-reject gate also blocked 6 of the 8 updates that were labelled beneficial.
- **Injected-error stress test.** 72 corrupted versions were built by rewriting 25% or 50% of each natural update's rules into plausible but wrong ones (wrong column, inverted condition, wrong unit or code). 17 of them were labelled harmful. The default-accept gate blocked 9 and let 8 through. The default-reject gate blocked all 17, at the cost of blocking almost all normal updates too.

## Follow-up experiments (exploratory, development data)

Run on 2026-11-27 after the final evaluation, with plans written before the runs; the sealed test split was not
used. Details: [`reports/followups.md`](reports/followups.md).

- **Second model.** On `gemini-3.8-flash` (thinking "low"), retrieving 3 relevant past questions with their
  correct SQL raised validation accuracy from 47.4% to 54.2% (+6.8 pp, 95% CI +2.4 to +11.2). Relevant
  questions beat the same number of random same-database questions by 9.4 pp (+5.2 to +13.7), close to the
  10.4 pp seen on `gemini-3.5-flash-lite`; random same-database questions alone gave no gain.
- **Mixed memory.** Replacing about one raw example with about 1.4 distilled rules, at the same budget, did not
  help: −0.8 pp vs raw experience alone (−2.3 to +0.7) on 539 development questions, averaged over three orders.

## How it works

- **Data.** BIRD dev has 1,534 questions over 11 SQLite databases. It is split per database with a fixed seed into learn (766), validation (308) and test (460). The test ids are stored separately with a recorded hash and cannot be loaded without an explicit `unseal=True`.
- **Agent.** `gemini-3.5-flash-lite` on Google Cloud Vertex AI, temperature 0, thinking off. It is graded on execution results with BIRD's set-equality rule.
- **Memory.** SQLite FTS5 (BM25) retrieval, scoped to the question's database, with the same budget for every group. Rules carry provenance (source tasks, creation round, use, win and loss counts). They are retired or quarantined, never deleted.
- **Gate.** The candidate memory and the current memory both answer the validation set, and the gate runs a paired z-test on fixed vs. broken questions (one-sided, 1.645). A rejected candidate is rolled back as a whole, and its new rules are kept as quarantined.
- **Audit trail.** Every round stores trajectories, the memory before and after the update, the candidate, the gate decision, cost, and a readable `report.md`. Interrupted runs resume from the last finished round. In total the experiments made about 225,000 model calls.

## Integrity of the final evaluation

- [`reports/design_freeze.md`](reports/design_freeze.md): written before the test split was opened. It lists what runs, the pre-registered analysis, the expectations from development data, and SHA-256 hashes of the 19 frozen source and config files.
- [`reports/analysis_addendum.md`](reports/analysis_addendum.md): supplementary statistics (intervals, per-order results, Holm) and reading rules added after the freeze. They were written before any test score was seen, and the frozen files were not changed.
- Generated results: [`final.md`](reports/final.md) (primary analysis), [`final_stats.md`](reports/final_stats.md), [`final_rounds.md`](reports/final_rounds.md); development results: [`rounds.md`](reports/rounds.md), [`injection.md`](reports/injection.md), [`week1.md`](reports/week1.md).

Commit history note: on 2026-11-25 the history was rewritten once to normalise the author and remove co-author trailers. File contents and dates are unchanged. Old IDs map to new ones as follows: `f53388c` → `1ec8ccd` (design freeze), `32e7744` → `64f3291`, `e0d6d78` → `cf9364f`, `5f739a0` → `f46fa39`, `4dec0c7` → `25f587f`.

## Limitations

- One model, one data split seed, and three task orders.
- The test questions come from the same databases the agent learned from. Results say nothing about transfer to new databases.
- The agent is assumed to receive the correct SQL after each learning question.
- Validation (308) and evaluation sets are small. Most single updates move accuracy by less than about 3 pp, and paired tests mostly label them unclear.
- Each group runs independently, so between-group differences include run-to-run variation (see above).

## Running it

```bash
uv sync
uv run pytest -q          # 47 offline tests (fake model)
```

**Data.** Download BIRD dev from https://bird-bench.github.io/ and place it as
`data/raw/bird_dev/dev.json` and `data/raw/bird_dev/dev_databases/<db_id>/<db_id>.sqlite`.
`data/raw/` and `data/sealed/` are git-ignored. `uv run memorygate split` writes the split from the
seed in the config; the sealed test ids are checked against the hash in `data/splits/` whenever they are loaded.

**Model access.** In `configs/week1.toml`, `provider = "vertex"` needs
`gcloud auth application-default login` and `GOOGLE_CLOUD_PROJECT`. `provider = "aistudio"` needs
`GEMINI_API_KEY`. `provider = "fake"` runs offline. Every call is logged with its cost, and
`[budget]` caps each invocation.

| Script | What it runs | Approx. cost |
|---|---|---|
| `scripts/run_week1.sh` | week-1 checks | $2 |
| `scripts/run_rounds.sh` | development rounds: 5 groups × 3 orders | $41 |
| `scripts/run_labels.sh` | post-hoc labels for every update | $8 |
| `scripts/run_inject.sh` | injected-error stress test | $21 |
| `scripts/run_final.sh` | final runs on the sealed test split | $41 |
| `scripts/run_model2.sh` | second-model replication of the week-1 check | $9 |
| `python -m memorygate.mixed run` | mixed-memory comparison | $3 |

Reports can be regenerated from saved runs without model calls:
`memorygate rounds-report`, `final-report`, `inject-report`, and `python -m memorygate.final_stats`.

Code layout (`src/memorygate/`):

| Module | Role |
|---|---|
| `rounds.py` | round loop |
| `memstore.py` | rule store |
| `memory.py` | raw-experience bank |
| `consolidate.py` | distil, merge, prune |
| `gate.py` | paired test and policies |
| `posthoc.py` | independent labels, primary report |
| `harm.py` | injection |
| `final_stats.py` | supplementary statistics |
| `model2_stats.py`, `mixed.py` | follow-up experiments |
| `splits.py` | sealed split |
| `grader.py`, `sqlexec.py` | execution grading |
| `llm.py` | model adapter and cost meter |
