# v1 vs. v2 — judged by v2

Both generator versions judged by judge v2 on the same 200 cases. All numbers computed from `results/v1_outputs.jsonl`, `results/v2_outputs.jsonl`, and their judge-v2 judgment files already on disk; this script makes no API calls.

## Headline metrics (95% Wilson CI)

| metric | v1 | v2 |
|---|---|---|
| Faithfulness rate | 105/200 (52.5%) [45.6%, 59.3%] | 184/200 (92.0%) [87.4%, 95.0%] |
| Hallucination rate (≥ 1 claim supported=false) | 82/200 (41.0%) [34.4%, 47.9%] | 16/200 (8.0%) [5.0%, 12.6%] |
| Primary-reason coverage | 200/200 (100.0%) [98.1%, 100.0%] | 196/200 (98.0%) [95.0%, 99.2%] |
| Length compliance (≤ 40 words) | 195/200 (97.5%) [94.3%, 98.9%] | 195/200 (97.5%) [94.3%, 98.9%] |

## Pass rate by case_type

| case_type | v1 | v2 |
|---|---|---|
| standard | 79/140 (56.4%) | 135/140 (96.4%) |
| sparse_profile | 6/12 (50.0%) | 12/12 (100.0%) |
| fallback | 2/12 (16.7%) | 2/12 (16.7%) |
| low_confidence | 3/12 (25.0%) | 12/12 (100.0%) |
| conflicting_signals | 9/12 (75.0%) | 12/12 (100.0%) |
| missing_fields | 6/12 (50.0%) | 11/12 (91.7%) |

## Pass rate by bait type

| bait type | v1 | v2 |
|---|---|---|
| health_tags | 32/79 (40.5%) | 71/79 (89.9%) |
| cuisine_not_reason | 7/20 (35.0%) | 17/20 (85.0%) |
| contradicted_like | 3/6 (50.0%) | 6/6 (100.0%) |
| contradicted_history | 4/4 (100.0%) | 4/4 (100.0%) |
| none | 65/107 (60.7%) | 100/107 (93.5%) |

## Failure counts by type

| failure type | v1 | v2 |
|---|---|---|
| non_causal_reason | 60 | 2 |
| sensitive_inference | 29 | 0 |
| fabrication | 12 | 12 |
| exclusion_violation | 4 | 4 |
| omission | 0 | 4 |

## McNemar test (paired verdicts, same case_ids)

n = 200 paired cases.

- v1 fail → v2 pass: **81**
- v1 pass → v2 fail: **2**
- McNemar χ² (continuity-corrected, df=1): **73.301**, p = **0.0000**

Statistically significant at α=0.05 — the shift in pass/fail verdicts between v1 and v2 is unlikely due to chance alone.

## Pre-registered criteria (CLAUDE.md, "v2 pre-registration")

| criterion | threshold | actual | verdict |
|---|---|---|---|
| Faithfulness ≥ 85%, CI lower bound > 80% | ≥85%, CI lo >80% | 92.0%, CI lo 87.4% | **MET** |
| Stress case_type sparse_profile ≥ 70% | ≥70% | 100.0% (n=12) | MET |
| Stress case_type fallback ≥ 70% | ≥70% | 16.7% (n=12) | **NOT MET** |
| Stress case_type low_confidence ≥ 70% | ≥70% | 100.0% (n=12) | MET |
| Stress case_type conflicting_signals ≥ 70% | ≥70% | 100.0% (n=12) | MET |
| Stress case_type missing_fields ≥ 70% | ≥70% | 91.7% (n=12) | MET |
| non_causal_reason count ≤ 10 | ≤10 | 2 | **MET** |
| sensitive_inference count ≤ 3 | ≤3 | 0 | **MET** |
| Primary-reason coverage ≥ 98% | ≥98% | 98.0% | **MET** |

**Overall: not all criteria met.**

### Root cause: fallback failures

10 of 12 `fallback` cases fail, all `fabrication` — the only stress `case_type` v2 does not improve on at all
(16.7% pass, identical to v1). The cause is specific: `generator/prompts/v2.txt`'s rule 1 prescribes
`"popular with customers this week"` as the required phrasing for `POPULAR_FALLBACK`, but the
`POPULAR_FALLBACK` reason only ever carries a `popularity` rating value — no time period. Judge v2 reads
"this week" as an unsupported temporal claim:

> **c_0154**: "Popular with customers this week, these TVP vegan sloppy joes are ready in 30 minutes..." —
> judge rationale: *"The popularity framing is grounded in POPULAR_FALLBACK, but the 'this week' timeframe
> has no support anywhere in the payload, which is a fabricated claim."*
>
> **c_0155**: "...is popular with customers this week..." — judge rationale: *"...'this week' adds a
> timeframe for the popularity score (4.3) that the payload does not support."*

The generator is doing exactly what rule 1 told it to do; the prescribed template phrase is itself the
unsupported claim.

## Chart

![Hallucination rate by case_type: v1 vs v2](hallucination_by_case_type.png)

## Copy quality observation

v2's copy frequently reads as the phrasing guide (rule 1 of `generator/prompts/v2.txt`) copied near-verbatim rather than adapted into natural sentences — the model is reliably grounded, but the prose is template-shaped. For example:

- **c_0015**: "You love mushroom, and this vegan dish is made with brown button mushrooms, which you like. It's a new cuisine for you to try: French, and it's ready in 20 minutes."
- **c_0151**: "A new cuisine for you to try: Indian. This shahi murg is an aromatic chicken dish with yoghurt and spices, ready in 40 minutes."
- **c_0172**: "A new cuisine for you to try: this Italian chicken pasta toss with spaghetti, tomatoes and parmesan is ready in 35 minutes."

## v2.1 follow-up

Pre-registered in CLAUDE.md ("v2.1 pre-registration") before this run: `generator/prompts/v2_1.txt` changes
only the `POPULAR_FALLBACK` phrasing in rule 1 and the fallback example, from "popular with customers this
week" to "highly rated by other customers". Tested on the 12 `fallback` cases only — **other case types are
not re-run and stay untested.**

**Pass rate: 11/12 (91.7%)** — meets the pre-registered success threshold (≥70%, ≥9/12).

| failure type | count |
|---|---|
| fabrication | 1 |

**All 12 explanations:**

| case_id | verdict | failure type | v2.1 explanation |
|---|---|---|---|
| c_0153 | fail | fabrication | "A popular pick with other customers this week: this Mexican grilled chicken is ready in 23 minutes, and it's a safe, well-liked place to start." |
| c_0154 | pass | — | "This tvp vegan sloppy joe is highly rated by other customers and ready in 30 minutes. We don't know your taste yet, so it's a well-liked place to start." |
| c_0155 | pass | — | "Highly rated by other customers, this garlic chicken breasts in balsamic vinegar is ready in 30 minutes. We don't know your taste yet, so it's a well-liked place to start." |
| c_0156 | pass | — | "This linguine with garlic shrimp is highly rated by other customers and ready in 25 minutes. We don't know your taste yet, so it's a popular place to start." |
| c_0157 | pass | — | "Highly rated by other customers, this Mexican-twist hamburger casserole with pasta, taco seasoning and cheddar takes 55 minutes. We don't know your taste yet, so it's a popular place to start." |
| c_0158 | pass | — | "Highly rated by other customers, this chorizo potato frittata is ready in 25 minutes. We don't know your taste yet, so it's a well-liked place to start." |
| c_0159 | pass | — | "Highly rated by other customers, this pork chop dish with balsamic vinegar and shallot sauce is ready in 20 minutes. We don't know your taste yet, so it's a well-liked place to start." |
| c_0160 | pass | — | "Highly rated by other customers, this pepper seared tuna steaks dish is ready in 20 minutes. We don't know your taste yet, so it's a well-liked place to start." |
| c_0161 | pass | — | "This quinoa black bean salad is highly rated by other customers and ready in 15 minutes. We don't know your taste yet, so it's a well-liked place to start." |
| c_0162 | pass | — | "Highly rated by other customers, this broiled shrimp is ready in 17 minutes. We don't know your taste yet, so it's a well-liked place to start." |
| c_0163 | pass | — | "Highly rated by other customers, this Korean hamburger is ready in 17 minutes. We don't know your taste yet, so it's a well-liked option to try." |
| c_0164 | pass | — | "Highly rated by other customers, this dorito taco salad with seasoned ground beef, lettuce and cheddar takes 20 minutes. We don't know your taste yet, so it's a popular place to start." |

`c_0153` still fails on "this week" — the model reintroduced that phrase on its own even though the prompt
no longer prescribes it (rule 1's `POPULAR_FALLBACK` line now reads "highly rated by other customers"; rule
5's example parenthetical still names "popular with customers this week" as an example of honest framing,
which may be the source — that occurrence was deliberately left unchanged, out of this pre-registration's
scope). Judge rationale: *"The copy correctly frames the pick as popular and makes no personal-tailoring or
health claims, but 'this week' gives a popularity timeframe that appears nowhere in the payload (the reason
only has a popularity score of 5.0), so it is fabricated."*

## Corrected for invalid ground truth

`c_0121`–`c_0124` have a self-contradictory payload (see `data/processed/invalid_cases.txt`): `profile p_031`
has `liked_ingredients: ["beef"]` and `exclusions: ["no_beef"]` simultaneously, a matcher/validator bug
(fixed in `ingredient_matching.py`, `matcher/run.py`, `data_prep/profiles.py` — `eval_set.jsonl` itself was
not regenerated, so these 4 cases remain in it). **The original 200-case numbers and the pre-registered
verdict above are unchanged and still stand** — this section recomputes the same judge-v2 judgments already
on disk with those 4 cases excluded, for comparison only.

Re-applying the judge's deterministic rule checks (no LLM calls) with the fixed ingredient matching changed
**0 verdicts** in either the 200-case v1 or v2 run: the judge's explanation-text check already caught all 4
cases correctly in both versions (both generators' text explicitly says "beef"), so the bug only ever
affected the upstream matcher/validator, never the judge's assessment of these 4 cases.

| metric | v1 (200) | v1 (196 valid) | v2 (200) | v2 (196 valid) |
|---|---|---|---|---|
| Faithfulness rate | 52.5% [45.6%, 59.3%] | 53.6% [46.6%, 60.4%] | 92.0% [87.4%, 95.0%] | 93.9% [89.6%, 96.5%] |
| Hallucination rate | 41.0% | 41.8% [35.2%, 48.8%] | 8.0% | 6.1% [3.5%, 10.4%] |
| Primary-reason coverage | 100.0% | 100.0% | 98.0% | **100.0%** |

All 4 excluded cases failed in both v1 and v2 (the pass count is unchanged; only the denominator shrinks),
so every rate ticks up slightly. v2's primary-reason coverage reaches exactly 100% once excluded, since all
4 `primary_reason_stated: false` cases in the original v2 count were c_0121–c_0124 (the refusal texts never
state a reason at all).

**Corrected failure counts (v2, 196 valid):** `fabrication`: 12 (unchanged — the `POPULAR_FALLBACK` issue is
unrelated to this bug); `exclusion_violation`: 0 (was 4, all 4 were the invalid cases); `omission`: 0 (was
4, same); `non_causal_reason`: 0 (was 2, both were c_0121/c_0124). `sensitive_inference` stays 0.

**Pre-registered criteria, recomputed on 196 valid cases:** every criterion's verdict is **unchanged** —
still 8/9 met, `fallback` still the one miss (2/12 = 16.7%, unaffected since none of the 4 excluded cases
are `fallback`). Correcting for the invalid ground truth makes the numbers slightly better but changes no
decision.
