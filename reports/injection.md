# Harm injection: corrupted candidates vs the gate

Each row replays a real update with a fraction of the candidate's entries rewritten into wrong versions.
label = independent paired test on the evaluation set; gate = paired test on val.

| strength | updates | label worse | unclear | improved | mean Δ eval | default_accept lets through (all / worse) | default_reject lets through (all / worse) |
|---|---|---|---|---|---|---|---|
| 0.25 | 36 | 6 | 27 | 3 | -0.002 | 27 / 4 | 2 / 0 |
| 0.50 | 36 | 11 | 23 | 2 | -0.021 | 15 / 4 | 0 / 0 |
