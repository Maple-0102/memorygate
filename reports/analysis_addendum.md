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
3 orders is descriptive only (with 3 orders, all signs agree by chance 1 time in 4).
Accuracy on test is not compared with development numbers as a check of "the same result": the final runs learn from
766 questions instead of 535 and are scored on different questions, so only differences between groups within the final runs
are interpreted.
