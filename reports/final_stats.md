# Final comparison: intervals, per-order results, Holm (supplementary)

Orders: o0, o1, o2. Last evaluated round. Unit = test question, correctness averaged over orders. Δ in percentage points with 95% interval from per-question differences. p = two-sided, raw; Holm over the 7 pre-registered pairs is supplementary. Primary verdicts: reports/final.md.

| B vs A | n | acc A | acc B | Δ pt | 95% interval | z | p | p (Holm) | same sign in every order |
|---|---|---|---|---|---|---|---|---|---|
| raw vs no_memory | 459 | 0.443 | 0.572 | +12.9 | [+9.4, +16.5] | +7.11 | 0.0000 | 0.0000 | yes |
| consolidate vs no_memory | 459 | 0.443 | 0.510 | +6.7 | [+3.8, +9.5] | +4.62 | 0.0000 | 0.0000 | yes |
| gate_accept vs no_memory | 459 | 0.443 | 0.495 | +5.2 | [+2.4, +7.9] | +3.63 | 0.0003 | 0.0011 | yes |
| gate_reject vs no_memory | 459 | 0.443 | 0.480 | +3.7 | [+1.2, +6.2] | +2.86 | 0.0042 | 0.0127 | yes |
| raw vs consolidate | 459 | 0.510 | 0.572 | +6.2 | [+3.4, +9.1] | +4.36 | 0.0000 | 0.0001 | yes |
| gate_accept vs consolidate | 459 | 0.510 | 0.495 | -1.5 | [-3.3, +0.2] | -1.70 | 0.0889 | 0.0889 | yes |
| gate_reject vs consolidate | 459 | 0.510 | 0.480 | -3.0 | [-5.0, -0.9] | -2.84 | 0.0045 | 0.0127 | yes |

## Per task order

| B vs A | o0: A → B (Δ pt) | o1: A → B (Δ pt) | o2: A → B (Δ pt) |
|---|---|---|---|
| raw vs no_memory | 0.449 → 0.575 (+12.6) | 0.438 → 0.571 (+13.3) | 0.442 → 0.571 (+12.9) |
| consolidate vs no_memory | 0.449 → 0.499 (+5.0) | 0.438 → 0.510 (+7.2) | 0.442 → 0.521 (+7.8) |
| gate_accept vs no_memory | 0.449 → 0.486 (+3.7) | 0.438 → 0.488 (+5.0) | 0.442 → 0.510 (+6.8) |
| gate_reject vs no_memory | 0.449 → 0.497 (+4.8) | 0.438 → 0.464 (+2.6) | 0.442 → 0.479 (+3.7) |
| raw vs consolidate | 0.499 → 0.575 (+7.6) | 0.510 → 0.571 (+6.1) | 0.521 → 0.571 (+5.0) |
| gate_accept vs consolidate | 0.499 → 0.486 (-1.3) | 0.510 → 0.488 (-2.2) | 0.521 → 0.510 (-1.1) |
| gate_reject vs consolidate | 0.499 → 0.497 (-0.2) | 0.510 → 0.464 (-4.6) | 0.521 → 0.479 (-4.1) |
