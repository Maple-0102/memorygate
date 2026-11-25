# Final comparison on the test split (pre-registered)

Orders: o0, o1, o2. Last evaluated round. Unit = test question, correctness averaged over orders.

| B vs A | acc A | acc B | Δ (B − A) | z | verdict (|z| > 1.96) |
|---|---|---|---|---|---|
| raw vs no_memory | 0.443 | 0.572 | +0.129 | +7.11 | B better |
| consolidate vs no_memory | 0.443 | 0.510 | +0.067 | +4.62 | B better |
| gate_accept vs no_memory | 0.443 | 0.495 | +0.052 | +3.63 | B better |
| gate_reject vs no_memory | 0.443 | 0.480 | +0.037 | +2.86 | B better |
| raw vs consolidate | 0.510 | 0.572 | +0.062 | +4.36 | B better |
| gate_accept vs consolidate | 0.510 | 0.495 | -0.015 | -1.70 | no clear difference |
| gate_reject vs consolidate | 0.510 | 0.480 | -0.030 | -2.84 | B worse |
