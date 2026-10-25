# Judge validation — v1, 50-case gold sample

Validates the v1 LLM judge (`claude-sonnet-5-5`) against Shola's hand labels in `data/gold/gold_labels.csv`
(50 cases, stratified across all 6 `case_type`s, seed=42; `data/gold/to_label.csv` is the blank template).
The judge prompt was **not** changed as part of this validation.

## 1. Label validation

All 50 rows checked: `my_verdict` is `pass` or `fail` on every row, and every `my_failure_types` token is a
valid taxonomy name (no numeric tokens needed mapping — the labelling tool already saves names). No
pass/fail vs. failure-type inconsistencies either (no row has `pass` with failure types listed, or `fail`
with none).

**0 problems found.**

## 2. Judge–human agreement on verdicts

- **Raw agreement:** 32/50 = **64.0%**
- **Cohen's kappa:** **0.271** (fair agreement — well below the κ ≥ 0.7 target)

**Confusion matrix** (judge × mine):

| | mine = pass | mine = fail |
|---|---|---|
| **judge = pass** | 19 | 8 |
| **judge = fail** | 10 | 13 |

## 3. Per-failure-type agreement

| failure_type | both flagged | only me | only judge |
|---|---|---|---|
| fabrication | 0 | 3 | 2 |
| misattribution | 0 | 0 | 2 |
| non_causal_reason | 8 | 6 | 6 |
| omission | 0 | 1 | 0 |
| overclaiming | 0 | 1 | 1 |
| profile_contradiction | 0 | 3 | 0 |
| sensitive_inference | 0 | 0 | **9** |

`sensitive_inference` is the standout: the judge raised it 9 times where Shola never did, and the two sides
never agreed on it even once in 50 cases. Looking at the disagreements below, this is almost entirely the
judge treating "light" (and once "healthy") as a Rule-4 health-synonym violation in cases Shola read as fine.

## 4. Judge self-agreement (`--no-cache --repeat 2`, same 50 cases)

- **Verdict match rate: 0.980** (49/50 — both runs agreed on pass/fail)
- **Failure-type match rate: 0.940** (47/50 — both runs produced the exact same failure_types set)
- **Tokens:** 237,896 input / 69,736 output
- **Estimated cost: $1.1732**

The judge is highly self-consistent — the low judge–human agreement in section 2 is not run-to-run noise.
It reflects a real, repeatable gap between how the judge prompt currently interprets Rule 4 (especially
health-synonym framing) and how Shola does.

## 5. Full disagreement list (25 of 50)

| case_id | my verdict / types | judge verdict / types | judge rationale | my note |
|---|---|---|---|---|
| c_0049 | pass [] | fail [sensitive_inference] | Uses the health tag "healthy" as a neutral fact, which Rule 4 prohibits even so — though all customer claims are grounded and the primary reason is conveyed. | — |
| c_0112 | pass [] | fail [non_causal_reason] | "Fits your cooking time comfortably" is a customer claim backed only by profile_context — no TIME_FIT reason exists. | — |
| c_0005 | fail [non_causal_reason] | pass [] | Every customer claim maps to a reason (LIKED_INGREDIENT, DIET_COMPLIANT, NEW_TO_YOU); no excluded ingredients or health claims. | — |
| c_0158 | fail [overclaiming] | pass [] | Frames the pick as popular (POPULAR_FALLBACK), states minutes as a meal fact, avoids personal-tailoring language under low confidence/fallback. | — |
| c_0039 | pass [] | fail [non_causal_reason, sensitive_inference] | States TIME_FIT correctly, but names "low-carb"/"low-sodium" and claims it "fits your schedule" — not covered by TIME_FIT. | — |
| c_0108 | fail [non_causal_reason] | pass [] | Conveys LIKED_INGREDIENT=pork and DIET_COMPLIANT=gluten-free; only meal facts otherwise; no health tags. | — |
| c_0175 | pass [] | fail [fabrication, overclaiming] | Time-fit stated correctly, but "a lighter match for your tastes" asserts an unsupported taste match under low confidence. | — |
| c_0140 | fail [non_causal_reason] | pass [] | Every claim maps to a listed reason (mushroom, Indian cuisine, vegan diet); top-weighted reason conveyed; meal facts from recipe fields. | — |
| c_0055 | fail [profile_contradiction] | fail [non_causal_reason] | "Well within your cooking time" is a time-limit claim from profile_context only — no TIME_FIT reason. | — |
| c_0004 | fail [fabrication] | fail [non_causal_reason] | The "roasted okra" rated-dish example and "within your cooking time limit" come only from profile_context — SIMILAR_TO_RATED's actual value is middle-eastern. | — |
| c_0174 | pass [] | fail [fabrication, sensitive_inference] | "Light" works as a health-style synonym for this fat-free dish; "for busy evenings" infers life circumstances no reason supports. | — |
| c_0012 | pass [] | fail [misattribution] | DIET_COMPLIANT=vegetarian, but copy says "plant-based preferences," implying vegan — misstates the reason's value. | — |
| c_0017 | fail [non_causal_reason] | fail [misattribution] | SIMILAR_TO_RATED only says "similar to highly rated items," but copy claims this exact recipe was rated before (from profile_context). | — |
| c_0002 | fail [non_causal_reason] | pass [] | Top-weighted DIET_COMPLIANT conveyed; time-limit and rated-highly claims map to TIME_FIT and SIMILAR_TO_RATED. | — |
| c_0142 | pass [] | fail [sensitive_inference] | TIME_FIT conveyed correctly, but "light pasta" works as a health-style synonym. | — |
| c_0029 | fail [non_causal_reason] | fail [non_causal_reason, sensitive_inference] | States the banned tag "low-calorie" and claims it "fits your schedule" with no TIME_FIT reason. | — |
| c_0078 | pass [] | fail [sensitive_inference] | Claims backed by LIKED_INGREDIENT/CUISINE_MATCH/TIME_FIT, but "light" reads as a health synonym (recipe is tagged low-calorie). | — |
| c_0026 | fail [profile_contradiction] | fail [non_causal_reason] | SIMILAR_TO_RATED only gives "italian"; the specific "rated a chicken dish highly" claim comes from profile_context. | f |
| c_0161 | pass [] | fail [sensitive_inference] | Conveys popularity, avoids personal-tailoring, but describes the meal as "healthy" — banned even as a neutral fact. | unsure |
| c_0030 | fail [non_causal_reason] | pass [] | Every claim maps to a listed reason (LIKED_INGREDIENT=mushroom primary, CUISINE_MATCH=mexican); no excluded ingredients/health tags. | — |
| c_0007 | fail [fabrication] | fail [non_causal_reason, sensitive_inference] | States "low-sodium" and "light"; also cites Indian/Italian favorites from profile_context only, not any reason. | — |
| c_0038 | fail [profile_contradiction] | pass [] | The only customer claim (quick-cooking preference) paraphrases TIME_FIT, the primary reason; no excluded ingredients/health tags. | unsure |
| c_0035 | fail [fabrication] | pass [] | The only customer claim (30-minute window) is backed by TIME_FIT, the primary reason; no health claim. | — |
| c_0110 | fail [non_causal_reason, omission] | fail [non_causal_reason] | "Fits your time limit" sourced only from profile_context — no TIME_FIT reason. | — |
| c_0101 | pass [] | fail [sensitive_inference] | Pork/Chinese/30-minute claims backed by reasons, but "light" reads as a synonym for the recipe's low-calorie tag. | — |
