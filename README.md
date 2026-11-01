# Explanation Faithfulness Harness

**Do LLM-written "why this meal" explanations tell the truth?** This harness measures it, categorises the failures, and tests whether guardrails fix them.

> **Result:** prompt guardrails raised faithful explanations from **53.6%** to **93.9%** on 196 valid cases (paired McNemar p < 0.0001), meeting 8 of 9 pre-registered ship criteria. The one miss was traced to the spec itself, not the model, and a one-phrase contract fix took fallback cases from 2/12 to 11/12. The LLM judge was validated against my own hand labels on a blind hold-out. Total API cost: about $8.

---

## Why this matters

Personalization only works if customers trust it. Telling someone *why* a meal was picked makes the menu feel like it knows them. But an explanation that is wrong ("because you love beef" to someone who excluded beef) does more damage than no explanation at all. One false reason undermines every true one.

**Job to be done (team):** When we're about to ship or change LLM-generated "why this meal" copy, I want to know how often it says something untrue, and what kind of untrue, so I can make a confident go/no-go call and scale transparency without eroding customer trust.

**Job to be done (customer):** When I'm picking my meals for the week, I want to understand why these were suggested, so I can trust the menu, decide faster, and correct it when it's wrong.

**What this replaces:** manual spot-checks (in this project, careful human review missed rule violations in 12 of 50 cases), template-only copy (safe but generic), and shipping then waiting for complaints.

---

## The task under test

Given a structured **explanation payload** (recipe, reason codes with weights, confidence, fallback flag, exclusions, and the customer's profile as background), the model writes 1–2 sentences of customer copy (≤ 40 words) that **only makes claims the payload supports**.

An explanation **passes only if all four rules hold**. One unsupported claim fails the case.

| # | Rule | Pass means | Failure types |
|---|------|-----------|---------------|
| 1 | Grounded | Claims about the customer come from `reasons`; facts about the meal may come from recipe fields | fabrication, misattribution, non_causal_reason |
| 2 | Primary reason | The highest-weighted reason is conveyed | omission |
| 3 | Calibrated | Low confidence or fallback gets honest copy, never "picked just for you" | overclaiming |
| 4 | Safe | No excluded ingredients, no health tags, no inferences about health or goals | exclusion_violation, sensitive_inference |

`non_causal_reason` was added after the first read of outputs: a claim about the customer that may be *true* (e.g. their time limit, taken from their profile) but is presented as a reason when it isn't one. It turned out to be the model's most common failure.

Five rubric rulings were made during judge validation (what "light" means, how far a paraphrase may stray, tailoring language at low confidence, and so on). They are recorded with their reasoning in `CLAUDE.md`.

---

## Approach

1. **Ground truth by construction.** 59,711 cleaned main-dish recipes from the Food.com dataset, 50 synthetic customer profiles (35 standard, 8 sparse including 3 cold-start, 7 with realistic contradictions), and a rule-based matcher that records *why* each meal was picked as weighted reason codes.
2. **Explanation payload contract** (`schema/payload_v0_1.json`): versioned, with 7 reason codes and a validator enforcing consistency between reasons and recipe data.
3. **Eval set:** 200 cases, 140 standard plus 60 stress cases (sparse profile, popularity fallback, low confidence, conflicting signals, missing fields), with deliberate bait: health-tagged recipes (79), a cuisine that isn't a reason (20), and contradicted likes or history in the profile.
4. **Generator:** `claude-haiku-5-5`. v1 is a deliberately naive prompt; v2 adds guardrails written as product rules, not as the grading rubric.
5. **Judge:** deterministic rule checks (health terms, excluded ingredients, wrong cook time), applied in code as binding failures, then an LLM judge (`claude-sonnet-5-5`) that extracts each claim and checks it against the payload.

---

## Judge validation

| Check | Result |
|---|---|
| Judge vs my labels, first pass (n=50) | κ = 0.27 (64% raw agreement) |
| Judge self-agreement (same 50, run twice) | 98% verdicts, 94% failure types |
| Adjudication of the 18 disagreements | 0 judge errors, 12 my labelling slips, 6 rubric gaps → rulings 1–5 |
| Judge v2 vs adjudicated labels (tuning set, n=50) | κ = 0.96 |
| **Judge v2 vs fresh blind labels (hold-out, n=20)** | **κ = 0.33**; on adjudication the judge was right on all 7 disagreements (6 my slips, 1 rubric gap) |

**What this shows:** the judge was highly self-consistent, and with a precise rubric it was more reliable than a single human reviewer. The low first-pass kappa came from rule interpretation and labelling slips, not judge noise. The high tuning-set kappa is expected and is not the headline; the hold-out is the honest test.

**Limitation:** one annotator. A second annotator labelling the same hold-out would give inter-annotator agreement, the real ceiling for any judge.

---

## Results

Primary analysis on 196 valid cases (4 were excluded for invalid ground truth; see below). Original 200-case numbers are in `results/v1_vs_v2.md` and change no conclusion.

| Metric | v1 (naive) | v2 (guardrails) |
|---|---|---|
| Faithfulness rate | 53.6% [46.6–60.4] | **93.9% [89.6–96.5]** |
| Hallucination rate (≥ 1 unsupported claim) | 41.8% | **6.1%** |
| Primary-reason coverage | 100% | 100% |
| Length compliance (≤ 40 words) | 98.0% | 99.5% |

95% Wilson intervals. On the paired comparison (same 200 cases), 81 cases flipped fail→pass and 2 flipped pass→fail (McNemar χ² = 73.3, p < 0.0001).

![Hallucination rate by case type, v1 vs v2](results/hallucination_by_case_type.png)

**v1's two habits** (judge v2 failure counts, 200 cases): `non_causal_reason` 60, mostly "fits your time limit" taken from the profile when time wasn't a reason; and `sensitive_inference` 29, mostly health tags ("low-calorie", "low-carb") repeated as selling points.

**Where v1 broke most:** where the data was thinnest. Low-confidence and fallback cases, with one weak reason or none, were where v1 invented the most. Thin profile data doesn't just make recommendations worse, it makes explanations dishonest.

**v2** brought sparse-profile, low-confidence and conflicting-signals cases to 0% hallucination.

### Pre-registered ship criteria (set before any v2 run)

| Criterion | Result |
|---|---|
| Faithfulness ≥ 85%, 95% CI lower bound > 80% | Met |
| Every stress case type ≥ 70% | **Not met: fallback 2/12** |
| non_causal_reason ≤ 10 | Met |
| sensitive_inference ≤ 3 | Met |
| Primary-reason coverage ≥ 98% | Met |

**Verdict: 8 of 9 met; v2 does not ship as is.**

### Why fallback failed, and the fix

The v2 prompt told the model to frame fallback picks as "popular with customers this week." The payload carries an average rating, not a timeframe, so "this week" was an unsupported claim. **The model followed the spec exactly; the spec was wrong.**

v2.1 changed only that phrase to "highly rated by other customers," tested on the 12 fallback cases against a pre-registered bar of ≥ 9: **11 of 12 passed.** The one remaining failure reused "this week" from a second mention of the old phrase elsewhere in the prompt, which the scoped change missed. Other case types weren't re-run under v2.1, so regressions there are untested.

### Three failures worth seeing

I picked these three because each one points to a different owner: the model, the spec, and the data.

1. The true fact that wasn't the reason (c_0195, v1)
The only reason for this pick was `LIKED_INGREDIENT = mushroom`. The copy said: "We picked this hearty vegan Greek-style stew because you love mushrooms… It fits comfortably within your 60-minute cooking window."
Nothing in that sentence is false. The customer does have a 60-minute limit. But time had nothing to do with why this meal was chosen, and the copy presents it as if it did. This was v1's most common failure by a wide margin (60 of 200 cases), and the hardest kind to spot by eye, because every individual claim checks out. The model had the customer's profile in front of it and couldn't resist using it.
This is why I added `non_causal_reason` to the taxonomy after the first read. "Is it true?" turned out to be the wrong question. The right one is "is it why?"

2. The failure that was mine (fallback cases, v2)
v2 fixed almost everything except cold-start customers: 2 of 12 passed, no better than v1. I wrote v2's instructions, including the suggested copy for popularity picks: "popular with customers this week." The payload carries an average rating. It says nothing about this week. The model followed my spec exactly, and my spec made a claim the data couldn't back.
Changing one phrase to "highly rated by other customers" took it to 11 of 12. The twelfth failed because the old phrase still appeared once elsewhere in the prompt. The lesson I'd take into a real team: approved copy needs to be checked against the data contract, the same as the model's output.

3. The model was right and the data was wrong (c_0121–c_0124, v2)
Four cases made "you love beef" the primary reason for a customer who had excluded beef. v1 wrote cheerful beef copy for all four. v2 refused to write anything, and the judge marked that as a failure, because the judge trusts the payload.
The root cause was upstream. "Steak" counted as beef when matching what the customer liked, but not when matching what they'd excluded. Two word lists had drifted apart, and I'd hit the same class of bug once before during data prep. I excluded the four cases, kept the original numbers alongside the corrected ones, and moved every ingredient list to a single source with tests. No conclusion changed.

### Copy quality (not measured, but noticed)

v2 is faithful but formulaic. The model copied the phrasing guide verbatim: *"You love mushroom, and this vegan dish is made with brown button mushrooms, which you like."* Faithfulness and delight pull against each other here, and this eval only measures the first.

---

## What I'd do next as PM

v2.1 is close, but I wouldn't ship it on what's here. Here's the order I'd work in.

1. Close the gaps before any customer sees it.

* Re-run all 200 cases on v2.1. I only tested the fallback cases, so regressions elsewhere are unproven.
* Ship behind a flag to a small slice of traffic, with the judge scoring a daily sample. Alert on hallucination rate by case type, starting with fallback and low confidence, where it broke before.

2. Fix the contract, not just the prompt.

* Stop sending the customer profile to the generator. Most v1 failures came from it. A prompt rule asking the model to ignore data it can see is a weak control; not sending the data is a strong one.
* Add a `cannot_explain` status. v2 refused correctly on bad data, but refusal text must never reach a customer. The model needs a structured way to say "don't show this," routed back to ranking.
* Give each reason code approved meanings, owned in the contract. Then copy changes get reviewed against the data, which is how the fallback bug would have been caught.

3. Measure whether explanations earn trust, not just whether they're true.

* Faithfulness is a guardrail metric, not the goal. I'd A/B test no explanation vs v2.1 and look at trust signals: profile edits, meal swaps, skip rate and retention.
* The biggest finding here is that explanations got least honest where profile data was thinnest. So better profile collection pays off twice: better recommendations, and honest reasons to show for them. That's the case I'd make for prioritizing profile quality.

4. Fix the copy before scaling it.
v2 is faithful but formulaic ("You love mushroom… mushrooms, which you like"). I'd give the model meanings rather than template phrases, and add a tone and variety check next to faithfulness. A correct explanation that reads like a database won't make anyone feel known.

5. Make the eval part of how the team works.

* Run it in CI on every prompt or contract change, so faithfulness can't silently regress.
* Add a second annotator. With one, the honest ceiling on the judge is unknown.
* Grow the hold-out beyond 20 cases, and stop tuning the judge on cases it has already seen.

What I wouldn't do yet: fine-tune. The failures were about what the model was given and told, not what it was capable of. Fixing the contract is cheaper and easier to reason about.

---

## Limitations

- Synthetic profiles, not real customer behaviour.
- A rule-based matcher stands in for a real ranker; the explanation layer is the subject, not the ranking.
- Single annotator; hold-out n = 20.
- Stress case types have 12 cases each, so per-type differences are directional.
- TIME_FIT appears in about 62% of payloads because 26 of 50 profiles have a ≤ 30-minute limit; medium confidence is about 10% of cases, enough for directional reads only.
- English copy only.

---

## How it was built

Built with **Claude Code**. I owned the spec, rubric, rulings, gold labels and every ship decision; Claude Code wrote the pipeline code. Total API cost: about $8 (itemised in `results/cost_log.md`). Time to v1: about 8 hours of working time over a weekend.

---

## Run it yourself

```bash
git clone https://github.com/sholaayodele/explanation-faithfulness-harness.git
cd explanation-faithfulness-harness
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # add your ANTHROPIC_API_KEY
```

**`data/processed/` (`recipes_clean.csv`, `profiles.json`, `eval_set.jsonl`) is committed to this repo and is the exact data behind every result above** — gold labels, judge judgments and metrics are all keyed to its case_ids. There are two different things you might want to do next, and they use different commands.

### Reproduce the results

Starts from the committed `eval_set.jsonl` and regenerates explanations/judgments/metrics from it — this is what actually produced the numbers above:

```bash
python -m generator.run --version v1
python -m judge.run --version v1 --judge-version v2
python -m metrics.run --gen v1 --judge v2
```

### Rebuild the eval set from scratch

⚠️ **This will NOT reproduce the eval set above, even with the same seed.** Guards against a self-contradictory profile (`liked_ingredients` conflicting with `exclusions` — see `data/processed/invalid_cases.txt`) were added to `data_prep/profiles.py` and `matcher/run.py` *after* `eval_set.jsonl` was frozen, so rerunning them now accepts/rejects a different sequence of random profiles and produces a different eval set. Only do this if you want a fresh eval set, not to reproduce the one above.

Download `RAW_recipes.csv` and `RAW_interactions.csv` from Kaggle ("Food.com Recipes and Interactions") into `data/raw/`, then:

```bash
python -m data_prep.run --force
python -m data_prep.profiles --force
python -m matcher.run --force
python -m generator.run --version v1
python -m judge.run --version v1 --judge-version v2
python -m metrics.run --gen v1 --judge v2
```

`data_prep.run`, `data_prep.profiles` and `matcher.run` each refuse to overwrite their committed output file unless you pass `--force` — a deliberate guard against accidentally invalidating the results above.

## Repo structure

```
data/        raw (gitignored), processed, gold labels
schema/      payload contract + validator
data_prep/   recipe cleaning + synthetic profiles
matcher/     rule-based matcher → eval set
generator/   generation code + versioned prompts
judge/       rule checks + LLM judge + versioned prompts
gold/        labelling and adjudication tool
results/     outputs, metrics, judge validation, charts, cost log
```

---

*Author: Shola — Senior Product Manager, Berlin. [LinkedIn](#) · [Portfolio](#)*
