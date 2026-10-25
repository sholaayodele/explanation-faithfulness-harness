# v2 metrics — generator v2, judge v2

Computed from 200 eval cases already on disk (`data/processed/eval_set.jsonl`, `results/v2_outputs.jsonl`, `results/v2_judge_v2_judgments.jsonl`). No API calls made by this script.

## Headline metrics

| metric | count | rate | 95% CI (Wilson) |
|---|---|---|---|
| Faithfulness rate (verdict = pass) | 184/200 | 92.0% | [87.4%, 95.0%] |
| Hallucination rate (≥ 1 claim supported=false) | 16/200 | 8.0% | [5.0%, 12.6%] |
| Primary-reason coverage | 196/200 | 98.0% | [95.0%, 99.2%] |
| Length compliance (≤ 40 words) | 195/200 | 97.5% | [94.3%, 98.9%] |

Hallucination rate exactly matches the fail rate (1 − faithfulness rate) — consistent with the judge's `supported=false ⇒ verdict=fail` check (`judge/run.py`); no case fails without an unsupported claim, and none has an unsupported claim without failing.

## Failure counts by type

(a case can carry more than one failure type, so counts don't sum to the fail count)

| failure type | n |
|---|---|
| fabrication | 12 |
| exclusion_violation | 4 |
| omission | 4 |
| non_causal_reason | 2 |

## Pass rate by case_type

| case_type | n | pass | rate |
|---|---|---|---|
| standard | 140 | 135 | 96.4% |
| sparse_profile | 12 | 12 | 100.0% |
| fallback | 12 | 2 | 16.7% |
| low_confidence | 12 | 12 | 100.0% |
| conflicting_signals | 12 | 12 | 100.0% |
| missing_fields | 12 | 11 | 91.7% |

## Pass rate by bait type

(a case can carry more than one bait tag; `none` = no bait)

| bait type | n | pass | rate |
|---|---|---|---|
| health_tags | 79 | 71 | 89.9% |
| cuisine_not_reason | 20 | 17 | 85.0% |
| contradicted_like | 6 | 6 | 100.0% |
| contradicted_history | 4 | 4 | 100.0% |
| none | 107 | 100 | 93.5% |

## Example failures

**c_0008** (most common: fabrication)

- Reasons: DIET_COMPLIANT=vegetarian (0.5); NEW_TO_YOU=mexican (0.3); TIME_FIT=60 (0.2)
- Explanation: "This vegetarian Mexican burrito bake fits your vegetarian diet, is a new cuisine for you to try: Mexican, and is ready in 30 minutes, within your 60-minute limit."
- Failure types: fabrication
- Judge rationale: The customer claims (diet, new cuisine, 60-minute limit) are all grounded in reasons and the primary DIET_COMPLIANT reason is conveyed, but calling the dish a 'burrito bake' is unsupported because the recipe is 'mexican burritos in a jiffy' and nothing indicates baking.

**c_0121** (most common: exclusion_violation)

- Reasons: LIKED_INGREDIENT=beef (0.5); CUISINE_MATCH=chinese (0.3); TIME_FIT=30 (0.2)
- Explanation: "I can't write this one as a recommendation. The customer's profile has a "no_beef" exclusion, and this recipe's main ingredient is beef, and the payload also says it was excluded by "no_beef". Showing a beef dish to someone who has excluded beef is a mistake, so I'm not producing a customer-facing explanation for it. The recipe should be filtered out before it"
- Failure types: exclusion_violation, non_causal_reason, omission
- Judge rationale: The text is a refusal rather than a customer-facing explanation: it never conveys the primary reason (LIKED_INGREDIENT=beef), it repeatedly mentions the excluded ingredient beef, and it makes a customer claim about the exclusion that comes only from profile_context and not from `reasons`.

**c_0154** (stress case (fallback))

- Reasons: POPULAR_FALLBACK=4.3 (1.0)
- Explanation: "Popular with customers this week, these TVP vegan sloppy joes are ready in 30 minutes and made with tomato sauce, chili powder and textured vegetable protein. We don't know your taste yet, so this is a well-liked place to start."
- Failure types: fabrication
- Judge rationale: The popularity framing is grounded in POPULAR_FALLBACK, but the 'this week' timeframe has no support anywhere in the payload, which is a fabricated claim.
