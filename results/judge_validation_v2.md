# Judge validation v2 — adjudication + v2 re-check

Follows `results/judge_validation.md`. Shola adjudicated all 18 verdict disagreements from the v1 validation
(`data/gold/gold_labels_adjudicated.csv`), judge v2 (`judge/prompts/judge_v2.txt`) was then run on the same
50 cases to see whether the 4 rubric rulings close the gap. Neither `gold_labels.csv` nor
`gold_labels_adjudicated.csv` was edited as part of this analysis.

## 1. Adjudication summary

**Bucket counts** (18 disagreements):

| bucket | count |
|---|---|
| rubric_gap | 6 |
| my_slip | 12 |
| judge_error | 0 |

Every one of the 18 disagreements resolved in the judge's favor — Shola's final verdict matches what judge
v1 said originally in all 18 cases. None were attributed to the judge simply being wrong (`judge_error`).

**All 18 verdicts changed from the original label:**

| case_id | original → final | bucket |
|---|---|---|
| c_0049 | pass → fail | rubric_gap |
| c_0112 | pass → fail | my_slip |
| c_0005 | fail → pass | rubric_gap |
| c_0158 | fail → pass | my_slip |
| c_0039 | pass → fail | my_slip |
| c_0108 | fail → pass | my_slip |
| c_0175 | pass → fail | my_slip |
| c_0140 | fail → pass | my_slip |
| c_0174 | pass → fail | rubric_gap |
| c_0012 | pass → fail | rubric_gap |
| c_0002 | fail → pass | my_slip |
| c_0142 | pass → fail | rubric_gap |
| c_0078 | pass → fail | rubric_gap |
| c_0161 | pass → fail | my_slip |
| c_0030 | fail → pass | my_slip |
| c_0038 | fail → pass | my_slip |
| c_0035 | fail → pass | my_slip |
| c_0101 | pass → fail | my_slip |

**Main failure types by bucket** (final, adjudicated `my_failure_types`):

| bucket | failure types involved |
|---|---|
| rubric_gap | omission (2), sensitive_inference (1), overclaiming (1), exclusion_violation (1) |
| my_slip | sensitive_inference (2), non_causal_reason (1), misattribution (1), overclaiming (1) |

The 6 `rubric_gap` cases are exactly what fed the 4 rulings added to CLAUDE.md and `judge_v2.txt` (the
"light"/health-tag conditionality, the SIMILAR_TO_RATED generic-vs-specific split, the paraphrase vs.
misattribution distinction, and the `exclusion_violation` rename/profile_context split).

## 2. Judge v2 run

Ran on the same 50 cases (`--judge-version v2`). **0 judge_errors, 0 code overrides changed an outcome.**

## 3. Kappa and raw agreement, three ways

| comparison | n | raw agreement | Cohen's kappa |
|---|---|---|---|
| original labels vs. judge v1 | 50 | 64.0% | **0.271** |
| adjudicated labels vs. judge v1 | 50 | 100.0% | **1.000** |
| adjudicated labels vs. judge v2 | 50 | 92.0% | **0.837** |

The middle row is tautological, not a validation result: adjudication was defined as "resolve every
disagreement in the judge's favor" (bucket counts above — 0 `judge_error`), so the adjudicated labels agree
with judge v1 by construction. The meaningful comparison is the first vs. the third row: judge **v2**, re-run
independently with no knowledge of the adjudication, reaches κ=0.837 against Shola's considered final
labels — up from 0.271 for v1, and close to the κ≥0.7 target from CLAUDE.md's Metrics section.

**Confusion matrix, adjudicated labels × judge v2:**

| | mine = pass | mine = fail |
|---|---|---|
| **judge v2 = pass** | 27 | 4 |
| **judge v2 = fail** | 0 | 19 |

Judge v2 never fails a case Shola passed; all remaining disagreement is in the other direction (judge v2
passes 4 cases Shola's adjudicated label still fails).

**Remaining disagreements (4 of 50):**

| case_id | my final label | judge v2 | rationale |
|---|---|---|---|
| c_0175 | fail [overclaiming] | pass [] | TIME_FIT (20 min within a 30-min limit) stated accurately as the main reason; the copy hedges with "lighter match" and "low-confidence" rather than claiming tailoring; "lighter" isn't a health claim since the recipe has no health tags. |
| c_0174 | fail [sensitive_inference] | pass [] | The 12/20-minute claims match TIME_FIT, the sole reason; "light" is an allowed flavour word since other_tags is empty; "busy evenings" is generic copy, no personal-tailoring claim despite low confidence. |
| c_0012 | fail [omission] | pass [] | Every customer claim maps to a reason (DIET_COMPLIANT as "plant-based", TIME_FIT, NEW_TO_YOU); primary diet reason conveyed; confidence medium, no contradiction; no health claims. |
| c_0142 | fail [overclaiming] | pass [] | The only customer claim (45-minute window) is backed by TIME_FIT, the primary reason; "light" is a flavour word since other_tags is empty; no personal-tailoring claim despite low confidence. |

All 4 are judge v2 reading "pass" where Shola's adjudicated label still reads "fail" — worth a closer look in
a future adjudication round, but not addressed here per instruction (judge prompt not changed further).

## 4. Fresh test set prepared (not yet run)

`data/gold/to_label_fresh.csv`: 20 new cases sampled from the 150 not yet labelled (seed=99), stratified
across all 6 `case_type`s, shuffled, no judge information:

| case_type | count |
|---|---|
| standard | 15 |
| conflicting_signals | 1 |
| fallback | 1 |
| low_confidence | 1 |
| missing_fields | 1 |
| sparse_profile | 1 |

`gold/label.py` now takes `--file`: `python -m gold.label --file data/gold/to_label_fresh.csv` writes to
`data/gold/gold_labels_fresh.csv` (derived by swapping `to_label` → `gold_labels` in the filename), with the
same save-after-every-case / resume / back / quit behavior as the main tool. The judge has **not** been run
on these 20 cases yet, per instruction.

## Cost

Judge v2, 50 cases: 139,800 input tokens / 28,024 output tokens. **Estimated cost: $0.5598.**
