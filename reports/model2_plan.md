# Second-model replication of the week-1 retrieval check — plan

Written 2026-11-27, before any call to the second model. Exploratory, development data only;
the sealed test split is not used. This is not part of the frozen design (`design_freeze.md`).

## Question

On a second model, does retrieving same-database past questions with their correct SQL still beat
no memory, and does relevance-based retrieval beat random same-database past questions?

## Setup

Identical to the week-1 check (`scripts/run_week1.sh`, `reports/week1.md`) except the model:

- Model: `gemini-3.8-flash` on Vertex AI (global), temperature 0, `thinking_level = "low"`
  (the model rejects "minimal" with a 400 error, found on the first pilot call; "low" is the lowest it accepts; week 1 ran with thinking off). Config: `configs/model2.toml`.
- Same data split (seed 20261123), prompts, grader and BIRD set-equality rule.
- Runs:
  1. `m2_nomem`: no memory on learn + val. Its learn attempts become the agent's own attempts in the bank,
     as in week 1.
  2. `m2_raw_k3`: relevant retrieval on val, k = 3, bank = learn + attempts from `m2_nomem`.
  3. `m2_shuf_k3`: k = 3 random same-database past questions, same bank, same seed as week 1.
- Gradable questions: those whose reference SQL runs (307 of 308 in week 1); the count is reported.

## Analysis (fixed now)

- Primary: `m2_raw_k3` vs `m2_nomem` on val. Paired per-question difference in accuracy, with a
  normal-approximation 95% CI, and fixed/broken counts.
- Secondary: `m2_raw_k3` vs `m2_shuf_k3`, same statistics.
- Reading rule: an effect is "observed" if the 95% CI excludes 0. A non-significant result is read
  from the interval: it rules out effects larger than the upper bound, nothing more.
- Reported next to the week-1 numbers on gemini-3.5-flash-lite (42.7% → 57.0%, random same-db +3.9 pp).

## Procedure and stop rules

- Pilot first: 10 val questions per condition, to confirm the model ID returned, thinking tokens,
  success rate, tokens and latency, and to re-estimate the full cost. Pilot runs were not analysed.
  (Correction, 2026-11-27: the pilot folders `runs/m2_pilot_*` were deleted after the full runs, before the
  backup; they held 30 calls, about $0.13, not included in the reported cost.)
- Only the remaining Google Cloud trial credit is used. If the console asks to upgrade to a paid account,
  or the credit runs out, the runs stop and whatever finished is reported as incomplete.
- Each run has a hard cap of $8 (estimated at the standard rate).

## Notes added during the runs (before any full-run result was seen)

- Model record. The run logs store the requested model name from the config; the server's returned
  model version is not saved per call. A separate one-off call on 2026-11-27 with the same settings
  returned `model_version = gemini-3.8-flash`. Results are reported as "requested `gemini-3.8-flash`,
  thinking level low".
- Cross-model reading. All three new runs use the same configuration, so the comparisons within the
  new model are fair. Week 1 ran a different model with thinking off, so a difference between the two
  models' gains is reported only as "different gains under two configurations", not as a tested
  difference between models; one being significant and the other not would not show the gains differ.
- The comparison of most interest is relevant vs. random same-database past questions: it separates
  "any same-db examples help" from "choosing relevant ones adds more".
