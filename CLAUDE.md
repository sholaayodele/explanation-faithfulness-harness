# CLAUDE.md — Explanation Faithfulness Harness

## What this project is
A portfolio project: an eval harness that measures whether LLM-generated "why this meal" explanations only say things that are true.
Context: meal-kit personalization (HelloFresh-style "Sous Chef" experience). The ranker is NOT the subject; the explanation layer is.

**Job to be done (team):** When we're about to ship or change LLM-generated "why this meal" copy, I want to know how often it says something untrue, and what kind of untrue, so I can make a confident go/no-go call and scale transparency without eroding customer trust.

**Owner:** Shola (PM). Shola owns the spec, rubric, gold labels and decisions. Claude Code writes scaffolding and code.

## The task under test
Given a structured explanation payload, the model writes a short customer-facing explanation that only makes claims the payload supports.

- **Input:** one payload (see schema below).
- **Output:** 1–2 sentences, max ~40 words, plain customer copy.
- **Pass = all four rules hold. Binary per case: one unsupported claim fails the case.**

| # | Rule | Pass means | Failure types |
|---|------|-----------|---------------|
| 1 | Grounded | Every claim about the customer or meal maps to a reason code or recipe field | fabrication, misattribution |
| 2 | Primary reason | The highest-weighted reason is stated | omission |
| 3 | Calibrated | Low confidence / fallback → hedged or honest copy, never "picked just for you" | overclaiming |
| 4 | Safe | No excluded ingredients; no health/weight/life inferences not in payload | profile_contradiction, sensitive_inference |

**Out of scope:** recommendation quality, persuasiveness/delight, general writing quality beyond length. No UI. No real customer data. No fine-tuning.

## Payload schema (v0.1 — draft, Shola approves changes)
```json
{
  "case_id": "c_0001",
  "recipe": {"id": "food_12345", "name": "...", "cuisine": "thai", "minutes": 25,
             "key_ingredients": ["..."], "diet_tags": ["vegetarian"]},
  "reasons": [
    {"code": "CUISINE_MATCH", "field": "cuisine_prefs", "value": "thai", "weight": 0.5},
    {"code": "TIME_FIT", "field": "max_cook_minutes", "value": 30, "recipe_minutes": 25, "weight": 0.3}
  ],
  "confidence": "high",
  "fallback": null,
  "excluded_by": ["no_pork"],
  "case_type": "standard"
}
```
**Reason codes:** `CUISINE_MATCH`, `TIME_FIT`, `DIET_COMPLIANT`, `LIKED_INGREDIENT`, `SIMILAR_TO_RATED`, `NEW_TO_YOU`, `POPULAR_FALLBACK`.
- `confidence`: `high | medium | low`
- `fallback`: `null | "POPULAR_FALLBACK"` (no personal signal)
- `case_type`: `standard | sparse_profile | fallback | low_confidence | conflicting_signals | missing_fields`

## Data
- Source: Kaggle "Food.com Recipes and Interactions", file `RAW_recipes.csv` → `data/raw/` (gitignored).
- Derive: cuisine (from tags), minutes, diet flags (from tags + ingredients), key ingredients.
- Profiles: ~50 synthetic, ~15 deliberately sparse or conflicting.
- Matcher: rule-based; outputs top meals per profile with reason codes = ground truth.
- Eval set: ~200 payloads, ~30% stress cases (non-`standard` case_type). Fixed random seed.

## Metrics
- Faithfulness rate (all claims supported)
- Hallucination rate (≥1 unsupported claim)
- Primary-reason coverage
- Failure counts by type and by case_type
- Judge–human agreement: Cohen's kappa vs `data/gold/gold_labels.csv` (target ≥ 0.7)
- Length compliance

## Judge design
1. **Rule checks (deterministic, run first):** excluded ingredient mentioned; stated cook time ≠ recipe minutes; length > 40 words.
2. **LLM judge:** extract each claim → mark supported/unsupported against payload → assign failure type(s) → overall pass/fail. Output strict JSON.
- Judge model must be stronger than the generator.

## Models and budget
- Generator: `claude-haiku-5-5`. Judge: `claude-sonnet-5-5`.
- Total API budget: ~€5. Always run on 10 cases before a full run.
- Cache every API response to `results/cache/` keyed by (prompt version, case_id); never re-call for a cached result.
- Log token usage and estimated cost per run.
- API key comes from `.env` via python-dotenv. Never print, log or commit it.

## Iterations
- **v1:** naive prompt ("explain why this meal was chosen").
- **v2:** guardrails — only listed reasons, phrasing per code, honest fallback copy, toned-down copy at low confidence, optional post-check that falls back to template copy on judge failure.
- Prompts live in `generator/prompts/` as versioned files (`v1.txt`, `v2.txt`). Never overwrite an old version.

## Repo structure
```
data/raw/          # Kaggle CSV (gitignored)
data/processed/    # cleaned recipes, profiles, eval set
data/gold/         # Shola's hand labels
schema/            # payload_v0_1.json + validator
generator/         # generation code + prompts/
judge/             # rule checks + LLM judge
results/           # run outputs, metrics, charts, cache/
notebooks/         # exploration only
```

## Conventions
- Python 3.11+, pandas, anthropic, scikit-learn, python-dotenv. Add any new dependency to `requirements.txt`.
- Scripts runnable from repo root, e.g. `python -m generator.run --version v1 --limit 10`.
- Outputs as CSV/JSONL with `case_id` on every row. Fixed seeds everywhere.
- Small functions, type hints, short docstrings. No over-engineering.

## Rules for Claude Code
- **Never create, edit or auto-fill gold labels.** They must be Shola's own, or the kappa is meaningless.
- **Do not change the pass rules, failure taxonomy, reason codes or schema without asking first.**
- Never write metrics or results into the README that weren't produced by an actual run. Use `[X]` placeholders.
- Propose a plan before large steps (matcher, judge, v2 guardrails) and wait for approval.
- Never commit `.env`, `.venv/`, `data/raw/` or the cache.
- When a run finishes, report: cases run, pass rate, cost, and 3 example failures.

## Build order / status
- [x] 1. Environment setup + `check_setup.py` passes
- [ ] 2. Schema + validator
- [ ] 3. Data prep on RAW_recipes.csv
- [ ] 4. Synthetic profiles
- [ ] 5. Matcher + 200-case eval set
- [ ] 6. v1 generator (10 cases, then 200)
- [ ] 7. Rule checks + LLM judge
- [ ] 8. Gold labels (Shola, ~50 cases) + kappa
- [ ] 9. v1 metrics
- [ ] 10. v2 guardrails + rerun + comparison chart
- [ ] 11. README case study (Shola writes; Claude helps format)
