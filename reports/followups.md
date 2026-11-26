# Follow-up experiments (2026-11-27, exploratory)

Both use development data only (learning split, development evaluation set, validation split); the sealed
test split was not touched. They are not part of the frozen design. Plans were written before any full run:
[`model2_plan.md`](model2_plan.md), [`mixed_plan.md`](mixed_plan.md). Generated tables:
[`model2.md`](model2.md), [`mixed.md`](mixed.md).

## 1. Second model: does retrieval still help on `gemini-3.8-flash`?

The week-1 check (validation split, k = 3 same-database past questions with their correct SQL) re-run with
a second model, requested as `gemini-3.8-flash` at thinking level "low" (it rejects "minimal"; a one-off
call returned `model_version = gemini-3.8-flash`). Week 1 used `gemini-3.5-flash-lite` with thinking off.

| | 3.5 Flash-Lite (week 1) | 3.8 Flash |
|---|---|---|
| No memory | 42.7% | 47.4% |
| Random same-db past questions | 46.6% | 44.8% |
| Relevant past questions | 57.0% | 54.2% |
| Relevant vs. no memory | +14.3 (95% CI +9.6 to +19.1) | **+6.8 (+2.4 to +11.2)** |
| Relevant vs. random | +10.4 (+6.0 to +14.9) | **+9.4 (+5.2 to +13.7)** |
| Random vs. no memory | +3.9 (+0.7 to +7.1) | −2.6 (−5.7 to +0.5) |

Each model's numbers use the questions gradable in all three of its runs: 308 for 3.8 Flash, 307 for week 1
(one reference query timed out in one week-1 run).

- Retrieval still helps on the second model: +6.8 pp over no memory, interval excludes 0.
- Choosing relevant past questions matters on both models: about +9 to +10 pp over the same number of random
  same-database questions. On 3.8 Flash, random same-database questions gave no gain (−2.6, interval
  includes 0), so the gain comes from relevance, not from extra same-database context.
- The gain over no memory was smaller on 3.8 Flash (+6.8 vs +14.3) but the two configurations differ in both
  model and thinking setting, and this was not tested as a difference; it is reported only as different
  observed gains.
- Cost of the full runs: 1,690 calls, about $8.5 at the standard rate (thinking tokens at "low" averaged about 400
  per call). A 30-call pilot (about $0.13, estimated) is not included; its folder was not kept.

## 2. Mixed memory with a fixed split did not beat raw experience

Fixed memory snapshots after round 12 of the development runs (three task orders). Mixed = up to 3 raw items,
then up to 2 rules that fit in the remaining characters (k ≤ 5, 1,500 characters for every condition).
In practice mixed sent 4.33 items and 1,343 characters per question (about 3 raw + 1.4 rules), raw 4.02 items
and 1,403 characters, rules 4.62 items and 815 characters. All three conditions were re-run in one batch on
539 questions (231 development evaluation + 308 validation); correctness averaged over the three orders.

| | raw | rules | mixed |
|---|---|---|---|
| Accuracy, all 539 | 57.0% | 51.2% | 56.2% |

- **Primary, mixed vs raw: −0.8 pp (95% CI −2.3 to +0.7).** Replacing about one raw example with about 1.4 rules
  gave no measurable gain; the data are compatible with at most a +0.7 pp gain. All three orders point the
  same way (−0.4, −0.7, −1.3; none significant).
- By question set the sign differs: −3.2 (−5.5 to −0.8) on the development evaluation set, +1.0 (−1.0 to +3.0)
  on validation. These subset results were reported as planned but are not the primary test.
- Mixed beat rules alone by 4.9 pp (+2.5 to +7.4), and raw beat rules by 5.8 pp (+3.2 to +8.3), consistent
  with the main experiment's raw-vs-rules result on the sealed test split (+6.2).
- Only two questions changed consistently in all three orders, one each way, and neither change is clearly
  explained by the rules' content:
  - T1448 (student_club, validation), fixed by mixed: raw filtered `budget.category = 'Pizza'`; mixed used
    `expense_description LIKE '%pizza%'`. The two added rules are about date formats, so the fix seems to come
    from dropping the fourth raw example (an expense-total query) rather than from what a rule said.
  - T0637 (codebase_community, validation), broken by mixed: mixed added `Tags IS NOT NULL`, which the
    removed examples and added rules do not mention.
- Rerunning the raw and rules groups also shows run-to-run variation: on the development evaluation set they
  scored 60.9% and 56.0% here versus 59.7% and 57.9% in the original round-12 evaluations, with the same hints.
- Cost of the full runs: 4,851 calls, about $2.8. A 30-call pilot (about $0.02, estimated) is not included; its folder
  was not kept.

## Reading

- The main finding, that retrieving relevant past questions with correct SQL helps, held on a second model, and
  relevance (not just same-database context) accounts for the gain on both models.
- At this budget and this fixed split (3 raw + up to 2 rules), mixing did not beat raw retrieval, so the simpler raw
  retrieval stays the choice. Other splits or choosing rules per question were not tested.

Cost: the main experiment's API spend was about $115. The full runs of the two follow-up experiments came to about
$11.4 together; the two pilots add an estimated $0.15.
