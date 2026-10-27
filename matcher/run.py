"""Build data/processed/eval_set.jsonl from profiles.json + recipes_clean.csv.

Usage: python -m matcher.run
"""

import json
import random
from collections import Counter
from pathlib import Path

import pandas as pd

from ingredient_matching import LIKED_INGREDIENT_EXCLUSION_CODE, matches_exclusion
from matcher.reasons import STRONG, WEAK, assign_weights, confidence_for, detect_candidates, rank_top
from schema.validator import validate_payload

PROFILES_PATH = Path("data/processed/profiles.json")
RECIPES_PATH = Path("data/processed/recipes_clean.csv")
OUT_PATH = Path("data/processed/eval_set.jsonl")

SEED = 42
REUSE_CAP = 2
N_STANDARD = 140
N_STRESS_EACH = 12

HEALTH_BAIT_MIN = int((N_STANDARD + 5 * N_STRESS_EACH) * 0.25)
CUISINE_BAIT_MIN = int((N_STANDARD + 5 * N_STRESS_EACH) * 0.10)
SIMILAR_TO_RATED_MIN = 20
NEW_TO_YOU_MIN = 15

FIELD_DEPENDENCIES = {"minutes": {"TIME_FIT"}, "cuisine": {"CUISINE_MATCH", "NEW_TO_YOU"}}
SAMPLE_SIZE = 40


def _load_recipes() -> pd.DataFrame:
    df = pd.read_csv(RECIPES_PATH)
    for col in ("diet_tags", "ingredients", "key_ingredients", "other_tags"):
        df[col] = df[col].apply(json.loads)
    return df


def _compatible_mask(df: pd.DataFrame, diet: list[str], exclusions: list[str], max_cook_minutes: int) -> pd.Series:
    mask = df["minutes"] <= max_cook_minutes
    for d in diet:
        mask &= df["diet_tags"].apply(lambda tags, d=d: d in tags)
    if exclusions:
        mask &= ~df["ingredients"].apply(lambda ings: any(matches_exclusion(ings, code) for code in exclusions))
    return mask


def _is_compliant(recipe: dict, diet: list[str], exclusions: list[str]) -> bool:
    if any(d not in recipe.get("diet_tags", []) for d in diet):
        return False
    if any(matches_exclusion(recipe.get("ingredients", []), code) for code in exclusions):
        return False
    return True


def _distribute(total: int, n_buckets: int) -> list[int]:
    base = total // n_buckets
    extra = total - base * n_buckets
    return [base + (1 if i < extra else 0) for i in range(n_buckets)]


class Matcher:
    def __init__(self, profiles: list[dict], recipes_df: pd.DataFrame, seed: int = SEED):
        self.profiles = profiles
        self.recipes_df = recipes_df
        self.recipes_by_id = recipes_df.set_index("id", drop=False).to_dict("index")
        self.rng = random.Random(seed)
        self.use_counts: Counter = Counter()
        self.cases: list[dict] = []

    def _available(self, df: pd.DataFrame) -> pd.DataFrame:
        if len(df) == 0:
            return df
        return df[~df["id"].isin([rid for rid, n in self.use_counts.items() if n >= REUSE_CAP])]

    def _rated_rows(self, profile: dict) -> list[dict]:
        return [self.recipes_by_id[rid] for rid in profile["rated_highly"] if rid in self.recipes_by_id]

    def _compliant_rated_rows(self, profile: dict, rated_rows: list[dict]) -> list[dict]:
        return [r for r in rated_rows if _is_compliant(r, profile["diet"], profile["exclusions"])]

    def _take(self, recipe_id: int) -> None:
        self.use_counts[recipe_id] += 1

    def _sample(self, df: pd.DataFrame, n: int) -> list[dict]:
        if len(df) == 0:
            return []
        n = min(n, len(df))
        return df.sample(n, random_state=self.rng.randint(0, 2**31 - 1)).to_dict("records")

    def _build_case(self, profile: dict, row: dict, weighted_reasons: list[dict], confidence: str,
                     case_type: str, nulled_field: str | None = None) -> dict:
        codes = {r["code"] for r in weighted_reasons}
        if "NEW_TO_YOU" in codes and "CUISINE_MATCH" in codes:
            raise AssertionError("NEW_TO_YOU and CUISINE_MATCH both present in the same payload")

        minutes = None if nulled_field == "minutes" else row["minutes"]
        cuisine = None if nulled_field == "cuisine" else (row["cuisine"] if pd.notna(row["cuisine"]) else None)

        is_fallback = any(r["code"] == "POPULAR_FALLBACK" for r in weighted_reasons)
        rated_rows = self._rated_rows(profile)
        rated_names = [r["name"] for r in rated_rows]

        payload = {
            "schema_version": "0.1",
            "case_id": None,
            "recipe": {
                "id": str(row["id"]),
                "name": row["name"],
                "cuisine": cuisine,
                "minutes": minutes,
                "main_ingredient": row["main_ingredient"] if pd.notna(row["main_ingredient"]) else None,
                "ingredients": row["ingredients"],
                "key_ingredients": row["key_ingredients"],
                "diet_tags": row["diet_tags"],
                "other_tags": row["other_tags"],
            },
            "reasons": [dict(r) for r in weighted_reasons],
            "confidence": confidence,
            "fallback": "POPULAR_FALLBACK" if is_fallback else None,
            "excluded_by": sorted(profile["exclusions"]),
            "case_type": case_type,
            "profile_context": {
                "cuisine_prefs": sorted(profile["cuisine_prefs"]),
                "diet": sorted(profile["diet"]),
                "liked_ingredients": sorted(profile["liked_ingredients"]),
                "exclusions": sorted(profile["exclusions"]),
                "max_cook_minutes": profile["max_cook_minutes"],
                "rated_highly_names": rated_names,
            },
        }

        bait = []
        if payload["recipe"]["other_tags"]:
            bait.append("health_tags")
        # cuisine_not_reason: the recipe has a cuisine, but no reason's value is that
        # cuisine - true whether the would-be explainer is CUISINE_MATCH, NEW_TO_YOU,
        # or (since its value is also the cuisine in this design) SIMILAR_TO_RATED.
        if cuisine is not None and not any(r.get("value") == cuisine for r in weighted_reasons):
            bait.append("cuisine_not_reason")
        if profile.get("conflict_pattern") == "diet_vs_liked_ingredient":
            bait.append("contradicted_like")
        if profile.get("conflict_pattern") == "diet_vs_history":
            bait.append("contradicted_history")

        return {"profile_id": profile["profile_id"], "payload": payload, "bait": bait, "_recipe_id": row["id"]}

    def _assert_conflict_rule(self, profile: dict, weighted_reasons: list[dict]) -> None:
        diet = profile["diet"]
        exclusions = profile["exclusions"]
        for r in weighted_reasons:
            if r["code"] != "LIKED_INGREDIENT":
                continue
            if diet and diet[0] in ("vegetarian", "vegan") and r["value"] != "mushroom":
                raise AssertionError(f"LIKED_INGREDIENT {r['value']!r} contradicts diet {diet}")
            exclusion_code = LIKED_INGREDIENT_EXCLUSION_CODE.get(r["value"])
            if exclusion_code and exclusion_code in exclusions:
                raise AssertionError(f"LIKED_INGREDIENT {r['value']!r} contradicts exclusion {exclusion_code!r}")

    # ---------- shared "best match" generator, used by standard / conflicting_signals / sparse_profile ----------
    def _generate_for_profile(self, profile: dict, n: int, case_type: str) -> int:
        compatible = self._available(
            self.recipes_df[_compatible_mask(self.recipes_df, profile["diet"], profile["exclusions"], profile["max_cook_minutes"])]
        )
        if len(compatible) == 0:
            return 0

        cuisine_prefs = profile["cuisine_prefs"]
        liked = profile["liked_ingredients"]
        strong_pool = compatible[compatible["cuisine"].isin(cuisine_prefs) | compatible["main_ingredient"].isin(liked)]
        pool = strong_pool if len(strong_pool) >= n else compatible
        if len(pool) > 2000:
            pool = pool.sample(2000, random_state=self.rng.randint(0, 2**31 - 1))

        rated_rows = self._rated_rows(profile)
        compliant_rated_rows = self._compliant_rated_rows(profile, rated_rows)

        scored = []
        for row in pool.to_dict("records"):
            if self.use_counts[row["id"]] >= REUSE_CAP:
                continue
            cands = detect_candidates(profile, row, rated_rows, compliant_rated_rows)
            strong_count = sum(1 for c in cands if c["code"] in STRONG)
            avg_rating = row["avg_rating"] if pd.notna(row["avg_rating"]) else 0.0
            scored.append((strong_count, avg_rating, row, cands))
        scored.sort(key=lambda t: (-t[0], -t[1]))

        made = 0
        for _, _, row, cands in scored:
            if made >= n:
                break
            top = rank_top(cands)
            if not top:
                continue
            weighted = assign_weights(top)
            self._assert_conflict_rule(profile, weighted)
            conf = confidence_for(weighted)
            case = self._build_case(profile, row, weighted, conf, case_type)
            self.cases.append(case)
            self._take(row["id"])
            made += 1
        return made

    def generate_standard(self, n_total: int) -> None:
        profiles = [p for p in self.profiles if p["profile_type"] == "standard"]
        for profile, n in zip(profiles, _distribute(n_total, len(profiles))):
            self._generate_for_profile(profile, n, "standard")

    def generate_sparse_profile(self, n_total: int) -> None:
        profiles = [p for p in self.profiles if p["profile_type"] == "sparse" and p["rated_highly"]]
        for profile, n in zip(profiles, _distribute(n_total, len(profiles))):
            self._generate_for_profile(profile, n, "sparse_profile")

    def generate_conflicting_signals(self, n_total: int) -> None:
        profiles = [p for p in self.profiles if p["profile_type"] == "conflicting"]
        for profile, n in zip(profiles, _distribute(n_total, len(profiles))):
            self._generate_for_profile(profile, n, "conflicting_signals")

    def generate_fallback(self, n_total: int) -> None:
        profiles = [p for p in self.profiles if p["profile_type"] == "sparse" and not p["rated_highly"]]
        for profile, n in zip(profiles, _distribute(n_total, len(profiles))):
            pool = self._available(
                self.recipes_df[(self.recipes_df["is_popular"]) & (self.recipes_df["minutes"] <= profile["max_cook_minutes"])]
            )
            for row in self._sample(pool, n):
                if self.use_counts[row["id"]] >= REUSE_CAP:
                    continue
                reason = [{
                    "code": "POPULAR_FALLBACK", "field": "popularity",
                    "value": round(float(row["avg_rating"]), 1), "weight": 1.0,
                }]
                case = self._build_case(profile, row, reason, "low", "fallback")
                self.cases.append(case)
                self._take(row["id"])

    def generate_low_confidence(self, n_total: int) -> None:
        profiles = [p for p in self.profiles if p["profile_type"] == "standard"]
        made = 0
        attempts = 0
        while made < n_total and attempts < n_total * 100:
            attempts += 1
            profile = profiles[attempts % len(profiles)]
            compatible = self._available(
                self.recipes_df[_compatible_mask(self.recipes_df, profile["diet"], profile["exclusions"], profile["max_cook_minutes"])]
            )
            weak_pool = compatible[
                ~compatible["cuisine"].isin(profile["cuisine_prefs"]) & ~compatible["main_ingredient"].isin(profile["liked_ingredients"])
            ]
            rated_rows = self._rated_rows(profile)
            compliant_rated_rows = self._compliant_rated_rows(profile, rated_rows)
            for row in self._sample(weak_pool, SAMPLE_SIZE):
                if self.use_counts[row["id"]] >= REUSE_CAP:
                    continue
                cands = detect_candidates(profile, row, rated_rows, compliant_rated_rows)
                top = rank_top(cands)
                if len(top) == 1 and top[0]["code"] in WEAK:
                    weighted = assign_weights(top)
                    conf = confidence_for(weighted)
                    case = self._build_case(profile, row, weighted, conf, "low_confidence")
                    self.cases.append(case)
                    self._take(row["id"])
                    made += 1
                    break
        if made < n_total:
            raise RuntimeError(f"low_confidence: only generated {made}/{n_total}")

    def generate_missing_fields(self, n_total: int) -> None:
        profiles = [p for p in self.profiles if p["profile_type"] in ("standard", "conflicting")]
        half = n_total // 2
        made = {"minutes": 0, "cuisine": 0}
        targets = {"minutes": half, "cuisine": n_total - half}
        attempts = 0
        while sum(made.values()) < n_total and attempts < n_total * 200:
            attempts += 1
            field = "minutes" if made["minutes"] < targets["minutes"] else "cuisine"
            profile = profiles[attempts % len(profiles)]
            compatible = self._available(
                self.recipes_df[_compatible_mask(self.recipes_df, profile["diet"], profile["exclusions"], profile["max_cook_minutes"])]
            )
            if field == "cuisine":
                compatible = compatible[compatible["cuisine"].notna()]
            rated_rows = self._rated_rows(profile)
            compliant_rated_rows = self._compliant_rated_rows(profile, rated_rows)
            for row in self._sample(compatible, SAMPLE_SIZE):
                if self.use_counts[row["id"]] >= REUSE_CAP:
                    continue
                cands = detect_candidates(profile, row, rated_rows, compliant_rated_rows)
                pre_null_top = rank_top(cands)
                top = rank_top(cands, exclude_codes=FIELD_DEPENDENCIES[field])
                if len(pre_null_top) < 2 or len(top) == 0:
                    continue
                weighted = assign_weights(top)
                conf = confidence_for(weighted)
                case = self._build_case(profile, row, weighted, conf, "missing_fields", nulled_field=field)
                self.cases.append(case)
                self._take(row["id"])
                made[field] += 1
                break
        if sum(made.values()) < n_total:
            raise RuntimeError(f"missing_fields: only generated {sum(made.values())}/{n_total}")


def _is_protected(case: dict) -> bool:
    """Cases a top-up pass must never touch: fixed-structure fallback cases,
    conflicting_signals cases (their bait tags are load-bearing), and any case
    that already carries a cuisine_not_reason/SIMILAR_TO_RATED/NEW_TO_YOU signal
    another top-up pass is relying on."""
    if case["payload"]["case_type"] in ("fallback", "conflicting_signals"):
        return True
    if "cuisine_not_reason" in case["bait"]:
        return True
    if any(r["code"] in ("SIMILAR_TO_RATED", "NEW_TO_YOU") for r in case["payload"]["reasons"]):
        return True
    return False


def _topup_weak_reason(matcher: Matcher, target_code: str, min_count: int) -> None:
    """Swap in replacement recipes so at least `min_count` reasons across the eval
    set are `target_code` (SIMILAR_TO_RATED or NEW_TO_YOU), without touching any
    protected case. Detection logic itself is untouched - this only changes which
    recipe is selected for a case."""
    current = sum(1 for c in matcher.cases for r in c["payload"]["reasons"] if r["code"] == target_code)
    needed = min_count - current
    if needed <= 0:
        return

    profiles_by_id = {p["profile_id"]: p for p in matcher.profiles}
    donor_cases = [c for c in matcher.cases if c["payload"]["case_type"] in ("standard", "low_confidence", "sparse_profile", "missing_fields")]
    for case in donor_cases:
        if needed <= 0:
            break
        if _is_protected(case):
            continue
        profile = profiles_by_id[case["profile_id"]]
        rated_rows = matcher._rated_rows(profile)
        compliant_rated_rows = matcher._compliant_rated_rows(profile, rated_rows)
        compatible = matcher._available(
            matcher.recipes_df[_compatible_mask(matcher.recipes_df, profile["diet"], profile["exclusions"], profile["max_cook_minutes"])]
        )
        if len(compatible) == 0:
            continue

        if target_code == "SIMILAR_TO_RATED":
            pairs = {
                (r["cuisine"], r["main_ingredient"])
                for r in compliant_rated_rows if pd.notna(r.get("cuisine")) and pd.notna(r.get("main_ingredient"))
            }
            if not pairs:
                continue
            qualifying = compatible[
                compatible.apply(lambda row: (row["cuisine"], row["main_ingredient"]) in pairs, axis=1)
            ]
        else:  # NEW_TO_YOU
            rated_cuisines = {r["cuisine"] for r in rated_rows if pd.notna(r.get("cuisine"))}
            qualifying = compatible[
                compatible["cuisine"].notna()
                & ~compatible["cuisine"].isin(profile["cuisine_prefs"])
                & ~compatible["cuisine"].isin(rated_cuisines)
            ]
        if len(qualifying) == 0:
            continue

        for row in matcher._sample(qualifying, min(50, len(qualifying))):
            if matcher.use_counts[row["id"]] >= REUSE_CAP:
                continue
            cands = detect_candidates(profile, row, rated_rows, compliant_rated_rows)
            top = rank_top(cands)
            if not top or not any(c["code"] == target_code for c in top):
                continue
            weighted = assign_weights(top)
            conf = confidence_for(weighted)
            new_case = matcher._build_case(profile, row, weighted, conf, case["payload"]["case_type"])

            matcher.use_counts[case["_recipe_id"]] -= 1
            matcher.use_counts[row["id"]] += 1
            case["payload"] = new_case["payload"]
            case["bait"] = new_case["bait"]
            case["_recipe_id"] = new_case["_recipe_id"]
            needed -= 1
            break


def _topup_cuisine_not_reason(matcher: Matcher, min_count: int) -> None:
    """Swap in replacement recipes for a few standard/low_confidence cases so the
    cuisine_not_reason bait quota is met: pick a recipe whose cuisine the profile
    has already rated before (so NEW_TO_YOU's "never tried" clause fails) and that
    isn't their stated preference - cuisine present, but genuinely unexplained."""
    current = sum(1 for c in matcher.cases if "cuisine_not_reason" in c["bait"])
    needed = min_count - current
    if needed <= 0:
        return

    profiles_by_id = {p["profile_id"]: p for p in matcher.profiles}
    donor_cases = [c for c in matcher.cases if c["payload"]["case_type"] in ("standard", "low_confidence")]
    for case in donor_cases:
        if needed <= 0:
            break
        if _is_protected(case):
            continue
        profile = profiles_by_id[case["profile_id"]]
        rated_rows = matcher._rated_rows(profile)
        rated_cuisines = {r["cuisine"] for r in rated_rows if pd.notna(r.get("cuisine"))}
        if not rated_cuisines:
            continue
        compatible = matcher._available(
            matcher.recipes_df[_compatible_mask(matcher.recipes_df, profile["diet"], profile["exclusions"], profile["max_cook_minutes"])]
        )
        qualifying = compatible[compatible["cuisine"].isin(rated_cuisines) & ~compatible["cuisine"].isin(profile["cuisine_prefs"])]
        if len(qualifying) == 0:
            continue
        compliant_rated_rows = matcher._compliant_rated_rows(profile, rated_rows)
        for row in matcher._sample(qualifying, 20):
            if matcher.use_counts[row["id"]] >= REUSE_CAP:
                continue
            cands = detect_candidates(profile, row, rated_rows, compliant_rated_rows)
            top = rank_top(cands)
            if not top or any(r["value"] == row["cuisine"] for r in top):
                continue
            weighted = assign_weights(top)
            conf = confidence_for(weighted)
            new_case = matcher._build_case(profile, row, weighted, conf, case["payload"]["case_type"])

            matcher.use_counts[case["_recipe_id"]] -= 1
            matcher.use_counts[row["id"]] += 1
            case["payload"] = new_case["payload"]
            case["bait"] = new_case["bait"]
            case["_recipe_id"] = new_case["_recipe_id"]
            needed -= 1
            break


def build() -> list[dict]:
    with PROFILES_PATH.open() as f:
        profiles = json.load(f)
    recipes_df = _load_recipes()

    matcher = Matcher(profiles, recipes_df)
    matcher.generate_standard(N_STANDARD)
    matcher.generate_sparse_profile(N_STRESS_EACH)
    matcher.generate_fallback(N_STRESS_EACH)
    matcher.generate_low_confidence(N_STRESS_EACH)
    matcher.generate_conflicting_signals(N_STRESS_EACH)
    matcher.generate_missing_fields(N_STRESS_EACH)

    _topup_weak_reason(matcher, "SIMILAR_TO_RATED", SIMILAR_TO_RATED_MIN)
    _topup_weak_reason(matcher, "NEW_TO_YOU", NEW_TO_YOU_MIN)
    _topup_cuisine_not_reason(matcher, CUISINE_BAIT_MIN)

    for i, case in enumerate(matcher.cases, start=1):
        case_id = f"c_{i:04d}"
        case["case_id"] = case_id
        case["payload"]["case_id"] = case_id

    return matcher.cases


def _report(cases: list[dict], max_reuse: int) -> None:
    from collections import Counter as C

    by_case_type = C(c["payload"]["case_type"] for c in cases)
    print("Counts by case_type:", dict(by_case_type))

    bait_counts = C(b for c in cases for b in c["bait"])
    print("Counts by bait type:", dict(bait_counts))

    conf_counts = C(c["payload"]["confidence"] for c in cases)
    print("Confidence distribution:", dict(conf_counts))

    reason_counts = C(r["code"] for c in cases for r in c["payload"]["reasons"])
    print("Reason-code frequency:", dict(reason_counts.most_common()))

    per_payload_counts = C(len(c["payload"]["reasons"]) for c in cases)
    print("Reasons-per-payload distribution:", dict(sorted(per_payload_counts.items())))

    print("Max recipe reuse:", max_reuse)
    print(f"Total cases: {len(cases)}")


def main() -> None:
    cases = build()

    errors_found = False
    for case in cases:
        errors = validate_payload(case["payload"])
        if errors:
            errors_found = True
            print(f"[INVALID] {case['case_id']}:")
            for e in errors:
                print(f"  - {e}")
    if errors_found:
        raise SystemExit("Validation failed for one or more payloads - eval_set.jsonl NOT written.")

    reuse = Counter(c["_recipe_id"] for c in cases)
    max_reuse = max(reuse.values()) if reuse else 0

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w") as f:
        for case in cases:
            row = {"case_id": case["case_id"], "profile_id": case["profile_id"], "payload": case["payload"], "bait": case["bait"]}
            f.write(json.dumps(row) + "\n")

    print(f"All {len(cases)} payloads passed validation.")
    print(f"Wrote {len(cases)} rows to {OUT_PATH}\n")
    _report(cases, max_reuse)


if __name__ == "__main__":
    main()
