# Week-1 feasibility results

| comparison (A → B) | n | acc A | acc B | Δ | fixed | broken | McNemar p | note |
|---|---|---|---|---|---|---|---|---|
| no-memory run 1 → run 2 | 1074 | 0.457 | 0.458 | +0.001 | 24 | 23 | 1 | noise floor (same prompt, temp 0) |
| no-memory → official hints | 1074 | 0.457 | 0.626 | +0.169 | 214 | 33 | 1.17e-33 | headroom: is there something to learn? |
| no-memory → raw retrieval (val) | 307 | 0.427 | 0.570 | +0.143 | 53 | 9 | 1.05e-08 | does past experience help new tasks? |
| no-memory → official hints (val) | 308 | 0.429 | 0.581 | +0.153 | 54 | 7 | 4.32e-10 | headroom on the same items |
| no-memory r1 → r2 (val) | 308 | 0.429 | 0.419 | -0.010 | 3 | 6 | 0.508 | noise on the same items |
| no-memory → shuffled same-db (val) | 308 | 0.429 | 0.468 | +0.039 | 19 | 7 | 0.029 | placebo |
| shuffled → raw retrieval (val) | 307 | 0.466 | 0.570 | +0.104 | 42 | 10 | 9.06e-06 | relevance beyond placebo |
| no-memory → raw_k3_halfA (val) | 308 | 0.429 | 0.523 | +0.094 | 36 | 7 | 8.96e-06 | half of the bank |
| no-memory → raw_k3_halfB (val) | 307 | 0.427 | 0.515 | +0.088 | 35 | 8 | 4.19e-05 | half of the bank |

Reproducibility: half A fixed 36, half B fixed 35, both fixed 23.


## Attribution proxy (raw retrieval vs no-memory, val)

35 of 53 fixed items used an identifier or constant that the gold query needs, the baseline missed, and a retrieved experience contained. Check by hand with `memorygate inspect nomem_r1 raw_k3`.

| qid | db | supplied by memory | memories |
|---|---|---|---|
| T0018 | california_schools | `'directly funded', county` | T0009, T0066, T0022 |
| T0023 | california_schools | `school` | T0001, T0034, T0051 |
| T0216 | toxicology | `'#'` | T0276, T0253, T0305 |
| T0248 | toxicology | `'#'` | T0276, T0306, T0272 |
| T0255 | toxicology | `'-', 100, bond_id` | T0226, T0262, T0232 |
| T0260 | toxicology | `'#'` | T0306, T0284, T0197 |
| T0266 | toxicology | `'+'` | T0204, T0229, T0321 |
| T0273 | toxicology | `'+', 100` | T0263, T0304, T0270 |
| T0326 | toxicology | `'='` | T0335, T0201, T0275 |
| T0327 | toxicology | `'-', atom_id` | T0325, T0329, T0211 |
| T0328 | toxicology | `'='` | T0335, T0201, T0275 |
| T0330 | toxicology | `'#', '+'` | T0272, T0200, T0276 |
| T0333 | toxicology | `atom_id` | T0226, T0297, T0272 |
| T0336 | toxicology | `'#', '-'` | T0200, T0272, T0262 |
| T0371 | card_games | `id` | T0516, T0416, T0498 |
| T0378 | card_games | `cardkingdomfoilid, cardkingdomid, id` | T0340, T0423, T0393 |
| T0434 | card_games | `mtgocode` | T0469, T0506, T0529 |
| T0450 | card_games | `cardkingdomfoilid, cardkingdomid` | T0340, T0393, T0454 |
| T0497 | card_games | `code, set_translations, setcode` | T0492, T0417, T0503 |
| T0507 | card_games | `code, id, sets` | T0506, T0433, T0401 |
| T0606 | codebase_community | `'2010-07-19 19:39:08.0'` | T0611, T0620, T0618 |
| T0684 | codebase_community | `18, id` | T0615, T0690, T0688 |
| T1206 | thrombosis_prediction | `60` | T1280, T1281, T1209 |
| T1230 | thrombosis_prediction | `'-', 250, admission, patient` | T1192, T1302, T1190 |
| T1233 | thrombosis_prediction | `180` | T1192, T1303, T1304 |

## Headroom by database (learn+val)

| db | n | no-memory | official hints | Δ |
|---|---|---|---|---|
| debit_card_specializing | 45 | 0.222 | 0.600 | +0.378 |
| toxicology | 101 | 0.208 | 0.574 | +0.366 |
| thrombosis_prediction | 115 | 0.148 | 0.452 | +0.304 |
| student_club | 111 | 0.577 | 0.766 | +0.189 |
| card_games | 134 | 0.373 | 0.537 | +0.164 |
| california_schools | 62 | 0.435 | 0.565 | +0.129 |
| financial | 74 | 0.473 | 0.595 | +0.122 |
| codebase_community | 130 | 0.615 | 0.715 | +0.100 |
| european_football_2 | 90 | 0.622 | 0.700 | +0.078 |
| formula_1 | 122 | 0.484 | 0.549 | +0.066 |
| superhero | 90 | 0.800 | 0.844 | +0.044 |

## Cost

- Week-1 total: 4474 calls, $2.29; per call $0.00051, 1132 input / 69 output / 0 thinking tokens; median latency 0.85s.
- Projection for the full plan (≈70,000 solve calls: 12 rounds × 4 groups × 3 orders, gate runs old+new memory on val each round, test every other round): about $46 (×1.3 for longer memory prompts and consolidation calls).
