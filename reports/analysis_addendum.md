# Analysis addendum — 2026-11-24 16:54 +08

Supplement to reports/design_freeze.md (frozen at commit f53388c). Written while the final runs were in progress.

## Test scores seen so far: none
Since the final runs started (2026-11-24 16:42), the only things read from runs/final/ were the directory listing,
o0_no_memory/config.json (to confirm 766 learn / 460 test / 308 val) and the last lines of one run log, which were empty.
No accuracy, done.json, evaluation trajectory or report from the test split, including the round 4 and round 8 evaluations,
has been opened. The dry runs of the reporting code below used development runs only (runs/o*_*).

## What is added
`python -m memorygate.final_stats` (new file src/memorygate/final_stats.py; no frozen file is changed, so the running
experiment and the primary analysis in `memorygate final-report` are untouched). For the same 7 pre-registered pairs and
the same unit (test question, correctness averaged over the 3 orders):
- difference in percentage points with a 95% interval, mean ± 1.96 × SE of the per-question differences;
- the raw two-sided p value, and the Holm-adjusted p value over all 7 pairs, labelled supplementary;
- each order's own accuracies and difference, and whether all three orders agree in sign.

## How this is read
The primary verdicts stay those of design_freeze.md (paired z, |z| > 1.96). Holm is reported alongside and can only
make a claim harder to keep. Results are read by the size of the difference and its interval first; sign agreement over
3 orders is descriptive only.
Accuracy on test is not compared with development numbers as a check of "the same result": the final runs learn from
766 questions instead of 535 and are scored on different questions, so only differences between groups within the final runs
are interpreted.

## Correction — 2026-11-24, still before any test score was seen
An earlier version of the paragraph above said that with 3 orders all signs agree by chance 1 time in 4. That figure
assumes independent orders with equal odds of either sign and no ties; the three orders share the same test questions, so
it has no basis and is removed. The per-order table only shows how much the difference moves with the task order.
The launch script scripts/run_final.sh is not in the hashed list of design_freeze.md; it is archived unchanged in commit f53388c.

## Reading note on gate_accept vs consolidate — 2026-11-24, still before any test score was seen
Checked on development runs only. gate_accept accepted 12, 11 and 12 of 12 updates, so in orders 0 and 2 it ran the same
strategy as consolidate. Even so the two runs diverge from the first round: with empty memory, 4 of 45 round-0 learning
answers already differ (orders 0 and 2; the model is not fully deterministic at temperature 0), no memory text is shared
after round 0, and at round 12 at most 1 of ~150 texts is shared. In order 2 (all accepted) the dev gap was −4.8 pt.
So the per-question 95% interval covers which questions were sampled, but not run-to-run variation of the whole pipeline,
which is of the same size as the observed gap. Consequences for the final report:
- gate_accept vs consolidate is read together with the number of rejections in each order; in an order with no rejection
  the difference is an estimate of run-to-run noise, not an effect of the gate;
- the per-order table is the only view of run-to-run variation and is shown next to the interval;
- a difference whose interval excludes 0 is still reported as measured, but not attributed to the gate unless
  rejections occurred and the per-order differences are larger than the spread seen between identical strategies.
