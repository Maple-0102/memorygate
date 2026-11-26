# Mixed memory (raw experience + distilled rules) — plan

Written 2026-11-27, before any mixed-memory call. Exploratory, development data only; the sealed test split
is not used. Not part of the frozen design (`design_freeze.md`).

## Question

At the same retrieval budget (at most 5 items and 1,500 characters per question), does giving up some raw
past-question examples for distilled rules beat raw experience alone?

## Setup

- Fixed memory snapshots from the development runs, one per task order o ∈ {0, 1, 2}, after the 12th
  round (`round_11`): the raw bank from `runs/o{o}_raw` and the rule store from `runs/o{o}_consolidate`.
  Both were built from the same learning stream for a given order. No learning happens in this experiment.
- Model and prompt as in the development runs: `configs/week1.toml` (`gemini-3.5-flash-lite`, temperature 0,
  thinking off), the same prompt template and the same memory label.
- Three conditions, all run in the same batch (the raw and rules baselines are re-run, not reused):
  - **raw**: existing raw retrieval, k = 5, 1,500 characters.
  - **rules**: existing rule retrieval, k = 5, 1,500 characters.
  - **mixed**: up to 3 raw items (raw retrieval with k = 3, 1,500 characters), then up to 2 rules
    (rule retrieval order, same scope), each added only if it fits in the characters left. Raw items are
    listed first. Empty slots are not back-filled: if fewer than 3 raw items or fewer than 2 rules are
    retrieved, the question gets fewer items.
- Questions: the development evaluation set (231) and the validation split (308), 539 in total, all disjoint
  from the learning stream. Validation questions were seen in week 1 and by the gates; neither raw nor
  consolidate memories were chosen with them.
- 3 conditions × 3 orders × 539 questions ≈ 4,850 calls, about $3.

## Analysis (fixed now)

- Unit: question, correctness averaged over the three orders; gradable questions only.
- Primary: mixed vs raw on all 539 questions. Difference in percentage points, 95% interval from the
  per-question differences, two-sided p.
- Also reported: the same for each question set separately (dev eval, val) and each order; mixed vs rules;
  raw vs rules; mean items and characters per question for each condition; fixed/broken counts.
- Reading rule: an effect is observed if the 95% interval excludes 0. If not, the result is read from the
  interval: it rules out gains above the upper bound and nothing more ("not significant" alone does not show
  the gain is below 3 pp).
- Two contrasting examples will be shown: one where an added rule plausibly fixed a question, one where the
  dropped example plausibly cost one.

## Procedure

- Check first, without model calls: for a sample of questions, the items and characters each condition sends.
- Then a 10-question pilot per condition for one order, then the full run.
- Only the remaining Google Cloud trial credit is used; if the credit runs out the runs stop and are reported
  as incomplete.

## Checks before any model call (2026-11-27)

- The raw and rules conditions reproduce the hints recorded in the round-12 development evaluation exactly
  (231 of 231 questions, each of the three orders).
- On 60 sample questions, mixed sends on average 4.35–4.37 items: about 2.95 raw items and 1.40 rules
  (1,383–1,401 characters), because three raw items leave room for fewer than two rules on many questions.
  Raw alone sends 3.75–3.85 items (about 1,410 characters); rules alone 4.8 items (770–910 characters).
  So in practice mixed trades about one raw example for 1.4 rules. This follows the rule fixed above
  (no back-filling) and is not changed.
