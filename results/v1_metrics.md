# v1 metrics — generator v1, judge v2

Computed from 200 eval cases already on disk (`data/processed/eval_set.jsonl`, `results/v1_outputs.jsonl`, `results/v1_judge_v2_judgments.jsonl`). No API calls made by this script.

## Headline metrics

| metric | count | rate | 95% CI (Wilson) |
|---|---|---|---|
| Faithfulness rate (verdict = pass) | 105/200 | 52.5% | [45.6%, 59.3%] |
| Hallucination rate (≥ 1 claim supported=false) | 82/200 | 41.0% | [34.4%, 47.9%] |
| Primary-reason coverage | 200/200 | 100.0% | [98.1%, 100.0%] |
| Length compliance (≤ 40 words) | 195/200 | 97.5% | [94.3%, 98.9%] |

## Failure counts by type

(a case can carry more than one failure type, so counts don't sum to the fail count)

| failure type | n |
|---|---|
| non_causal_reason | 60 |
| sensitive_inference | 29 |
| fabrication | 12 |
| exclusion_violation | 4 |

## Pass rate by case_type

| case_type | n | pass | rate |
|---|---|---|---|
| standard | 140 | 79 | 56.4% |
| sparse_profile | 12 | 6 | 50.0% |
| fallback | 12 | 2 | 16.7% |
| low_confidence | 12 | 3 | 25.0% |
| conflicting_signals | 12 | 9 | 75.0% |
| missing_fields | 12 | 6 | 50.0% |

## Pass rate by bait type

(a case can carry more than one bait tag; `none` = no bait)

| bait type | n | pass | rate |
|---|---|---|---|
| health_tags | 79 | 32 | 40.5% |
| cuisine_not_reason | 20 | 7 | 35.0% |
| contradicted_like | 6 | 3 | 50.0% |
| contradicted_history | 4 | 4 | 100.0% |
| none | 107 | 65 | 60.7% |

## Example failures

**c_0001** (most common: non_causal_reason)

- Reasons: DIET_COMPLIANT=vegetarian (0.6); SIMILAR_TO_RATED=middle-eastern (0.4)
- Explanation: "This vegetarian pick fits your plan, and its 30-minute cook time is well within your limit. Since you rated Middle Eastern-style dishes highly, these mushroom-and-herb stuffed grape leaves seemed like a great way to try something new."
- Failure types: non_causal_reason
- Judge rationale: The claim that the cook time is 'well within your limit' relies on profile_context (max_cook_minutes) because no TIME_FIT reason exists, so it is a non_causal_reason, even though the diet and Middle Eastern claims are grounded and the copy is safe.

**c_0007** (most common: sensitive_inference)

- Reasons: DIET_COMPLIANT=vegetarian (0.6); NEW_TO_YOU=french (0.4)
- Explanation: "This vegetarian French dish fits your plant-based preferences and is a fresh cuisine to explore, with a comfortable 55-minute cook time. It's a light, low-sodium option that's a nice change from your usual Indian and Italian favorites."
- Failure types: non_causal_reason, sensitive_inference
- Judge rationale: The copy names the health tag 'low-sodium' and calls the dish 'light' while the recipe is health-tagged, and it cites the customer's Indian and Italian favorites, which come only from profile_context and not from any reason.

**c_0141** (stress case (sparse_profile))

- Reasons: TIME_FIT=45 (1.0)
- Explanation: "We picked this 15-minute horseradish breaded chicken breast because it fits comfortably within your 45-minute cooking window and offers a bold, tangy flavor. It's also a light, low-calorie option."
- Failure types: sensitive_inference
- Judge rationale: The time-fit primary reason is correctly conveyed and the copy does not overclaim, but it mentions the health tag 'low-calorie' and uses 'light' on a health-tagged recipe, which violates Rule 4.

## Judge v1 vs. judge v2, same 200 explanations

`results/v1_outputs.jsonl` (the generator v1 explanations) was not regenerated between these two judge runs —
both judge v1 (`results/v1_judgments.jsonl`, from the step-7 run) and judge v2 above judged the exact same
200 explanations. So the entire difference below is mechanically attributable to the rubric rulings
(CLAUDE.md, "Rubric rulings") encoded in `judge_v2.txt`, not to any change in the generator.

| judge | pass | rate |
|---|---|---|
| v1 | 100/200 | 50.0% |
| v2 | 105/200 | 52.5% |

Exactly **5 cases flipped, all fail → pass, 0 pass → fail** — the +2.5pp is these 5 cases and nothing else:

| case_id | v1 failure type(s) | ruling that resolves it |
|---|---|---|
| c_0012 | misattribution | 3A — paraphrase ("plant-based" for vegetarian) no longer misattribution |
| c_0117 | fabrication | 4A — true `profile_context` claim is non_causal_reason, not fabrication (not previously examined; new evidence the ruling generalizes beyond the gold 50) |
| c_0142 | sensitive_inference | 1A — "light" only a health claim when `other_tags` is non-empty |
| c_0174 | fabrication, sensitive_inference | 1A, 4A |
| c_0175 | fabrication, overclaiming | 4A, ruling 5 — honest disclaimer language no longer fabrication |

`c_0175` is also the one case where judge v2's `pass` still disagrees with Shola's adjudicated gold label
(`fail [overclaiming]`) — see `results/judge_validation_v2.md` §3 and §6. Everything else here matches her
adjudication exactly, consistent with κ=0.958 (§3) on the 50-case gold set.
