"""Generate ~50 synthetic customer profiles for the eval set.

Usage: python -m data_prep.profiles
"""

import json
import random
from pathlib import Path

import pandas as pd

from ingredient_matching import LIKED_INGREDIENT_EXCLUSION_CODE, matches_exclusion

CUISINES = [
    "italian", "mexican", "indian", "chinese", "thai",
    "greek", "french", "middle-eastern", "cajun", "caribbean",
]
DIETS = ["vegetarian", "vegan", "gluten-free"]
TIME_BUCKETS = [20, 30, 45, 60]
LIKES = ["chicken", "beef", "pork", "shrimp", "salmon", "mushroom"]
EXCLUSIONS = ["no_pork", "no_beef", "no_shellfish", "no_peanut", "no_mushroom", "no_cilantro"]

RECIPES_PATH = Path("data/processed/recipes_clean.csv")
OUT_PATH = Path("data/processed/profiles.json")

SEED = 42
MIN_COMPATIBLE = 20
MIN_PREFERRED_COMPATIBLE = 5
MAX_ATTEMPTS = 2000

N_STANDARD = 35
N_SPARSE_COLD = 3
N_SPARSE_WITH_HISTORY = 5
# Guaranteed diet coverage among the standard profiles; the rest are random.
FORCED_STANDARD_DIETS = ["vegetarian", "vegetarian", "vegetarian", "vegan", "vegan", "gluten-free", "gluten-free"]
# (diet, liked_ingredient) pairs for the diet-vs-liked-ingredient conflict pattern
DIET_VS_LIKED = [("vegetarian", "salmon"), ("vegan", "shrimp"), ("vegetarian", "beef")]
# diets used for the diet-vs-history conflict pattern
DIET_VS_HISTORY = ["vegetarian", "vegan"]
# (cuisine, exclusions) pairs for the cuisine-vs-exclusions conflict pattern
CUISINE_VS_EXCLUSIONS = [("thai", ["no_peanut", "no_cilantro"]), ("cajun", ["no_shellfish"])]


def _load_recipes() -> pd.DataFrame:
    df = pd.read_csv(RECIPES_PATH)
    df["diet_tags"] = df["diet_tags"].apply(json.loads)
    df["ingredients"] = df["ingredients"].apply(json.loads)
    return df


def _compatible_mask(df: pd.DataFrame, diet: list[str], exclusions: list[str], max_cook_minutes: int) -> pd.Series:
    mask = df["minutes"] <= max_cook_minutes
    for d in diet:
        mask &= df["diet_tags"].apply(lambda tags, d=d: d in tags)
    if exclusions:
        mask &= ~df["ingredients"].apply(
            lambda ings: any(matches_exclusion(ings, code) for code in exclusions)
        )
    return mask


def _sample_rated_highly(rng: random.Random, pool_ids: list[int], n: int) -> list[int]:
    ids = rng.sample(pool_ids, k=min(n, len(pool_ids)))
    rng.shuffle(ids)
    return ids


def _make_standard(df: pd.DataFrame, rng: random.Random, forced_diet: str | None = None) -> dict | None:
    cuisine_prefs = rng.sample(CUISINES, k=rng.choice([1, 2]))
    if forced_diet is not None:
        diet = [forced_diet]
    else:
        diet = rng.sample(DIETS, k=1) if rng.random() < 0.2 else []
    max_cook_minutes = rng.choice(TIME_BUCKETS)
    # Vegetarian/vegan can never truthfully like a meat/fish ingredient - the
    # only achievable "like" under those diets is mushroom (or none stated).
    # Deliberate diet-vs-liked-ingredient conflicts live only in the
    # diet_vs_liked_ingredient conflicting pattern, not here.
    if diet and diet[0] in ("vegetarian", "vegan"):
        liked_ingredients = rng.choice([[], ["mushroom"]])
    else:
        liked_ingredients = rng.sample(LIKES, k=rng.choice([1, 2]))
    exclusions = rng.sample(EXCLUSIONS, k=1) if rng.random() < 0.4 else []

    # A profile can't truthfully like an ingredient it has also excluded
    # (e.g. liked_ingredients=["beef"], exclusions=["no_beef"]) - this was
    # possible before since the two were sampled independently with no
    # cross-check, which produced p_031 and the c_0121-c_0124 bug.
    if any(LIKED_INGREDIENT_EXCLUSION_CODE.get(li) in exclusions for li in liked_ingredients):
        return None

    compatible = df[_compatible_mask(df, diet, exclusions, max_cook_minutes)]
    if len(compatible) < MIN_COMPATIBLE:
        return None

    cuisine_ok = any((compatible["cuisine"] == c).sum() >= MIN_PREFERRED_COMPATIBLE for c in cuisine_prefs)
    liked_ok = (
        True
        if not liked_ingredients
        else any((compatible["main_ingredient"] == l).sum() >= MIN_PREFERRED_COMPATIBLE for l in liked_ingredients)
    )
    if not (cuisine_ok and liked_ok):
        return None

    known = compatible[compatible["cuisine"].notna() & compatible["main_ingredient"].notna()]
    if len(known) == 0:
        return None

    n_rated = rng.choice([2, 3])
    anchor_id = int(rng.choice(known["id"].tolist()))
    remaining = [i for i in compatible["id"].tolist() if i != anchor_id]
    rated_highly = [anchor_id] + _sample_rated_highly(rng, remaining, n_rated - 1)
    rng.shuffle(rated_highly)

    return {
        "profile_type": "standard",
        "cuisine_prefs": sorted(cuisine_prefs),
        "diet": sorted(diet),
        "max_cook_minutes": max_cook_minutes,
        "liked_ingredients": sorted(liked_ingredients),
        "exclusions": sorted(exclusions),
        "rated_highly": rated_highly,
        "_compatible_count": int(len(compatible)),
    }


def _make_sparse(df: pd.DataFrame, rng: random.Random, cold_start: bool) -> dict:
    max_cook_minutes = rng.choice(TIME_BUCKETS)
    compatible = df[_compatible_mask(df, [], [], max_cook_minutes)]
    rated_highly = [] if cold_start else _sample_rated_highly(rng, compatible["id"].tolist(), rng.choice([2, 3]))
    return {
        "profile_type": "sparse",
        "cuisine_prefs": [],
        "diet": [],
        "max_cook_minutes": max_cook_minutes,
        "liked_ingredients": [],
        "exclusions": [],
        "rated_highly": rated_highly,
        "_compatible_count": int(len(compatible)),
    }


def _make_conflicting_diet_vs_liked(df: pd.DataFrame, rng: random.Random, diet: str, liked: str) -> dict | None:
    cuisine_prefs = rng.sample(CUISINES, k=1)
    max_cook_minutes = rng.choice(TIME_BUCKETS)
    exclusions = rng.sample(EXCLUSIONS, k=1) if rng.random() < 0.3 else []

    compatible = df[_compatible_mask(df, [diet], exclusions, max_cook_minutes)]
    if len(compatible) < MIN_COMPATIBLE:
        return None

    rated_highly = _sample_rated_highly(rng, compatible["id"].tolist(), rng.choice([2, 3]))
    return {
        "profile_type": "conflicting",
        "conflict_pattern": "diet_vs_liked_ingredient",
        "cuisine_prefs": sorted(cuisine_prefs),
        "diet": [diet],
        "max_cook_minutes": max_cook_minutes,
        "liked_ingredients": [liked],
        "exclusions": sorted(exclusions),
        "rated_highly": rated_highly,
        "_compatible_count": int(len(compatible)),
    }


def _make_conflicting_diet_vs_history(df: pd.DataFrame, rng: random.Random, diet: str) -> dict | None:
    cuisine_prefs = rng.sample(CUISINES, k=rng.choice([1, 2]))
    max_cook_minutes = rng.choice(TIME_BUCKETS)
    liked_ingredients = rng.sample(LIKES, k=1)

    compatible = df[_compatible_mask(df, [diet], [], max_cook_minutes)]
    if len(compatible) < MIN_COMPATIBLE:
        return None

    # history contradicts the stated diet: pick non-compliant (meat/fish) recipes.
    non_compliant = df[~df["diet_tags"].apply(lambda tags, d=diet: d in tags) & df["main_ingredient"].notna()]
    if len(non_compliant) < 2:
        return None
    rated_highly = _sample_rated_highly(rng, non_compliant["id"].tolist(), rng.choice([2, 3]))

    return {
        "profile_type": "conflicting",
        "conflict_pattern": "diet_vs_history",
        "cuisine_prefs": sorted(cuisine_prefs),
        "diet": [diet],
        "max_cook_minutes": max_cook_minutes,
        "liked_ingredients": sorted(liked_ingredients),
        "exclusions": [],
        "rated_highly": rated_highly,
        "_compatible_count": int(len(compatible)),
    }


def _make_conflicting_cuisine_vs_exclusions(
    df: pd.DataFrame, rng: random.Random, cuisine: str, exclusions: list[str]
) -> dict | None:
    max_cook_minutes = rng.choice(TIME_BUCKETS)
    liked_ingredients = rng.sample(LIKES, k=rng.choice([1, 2]))

    compatible = df[_compatible_mask(df, [], exclusions, max_cook_minutes)]
    if len(compatible) < MIN_COMPATIBLE:
        return None

    rated_highly = _sample_rated_highly(rng, compatible["id"].tolist(), rng.choice([2, 3]))
    return {
        "profile_type": "conflicting",
        "conflict_pattern": "cuisine_vs_exclusions",
        "cuisine_prefs": [cuisine],
        "diet": [],
        "max_cook_minutes": max_cook_minutes,
        "liked_ingredients": sorted(liked_ingredients),
        "exclusions": sorted(exclusions),
        "rated_highly": rated_highly,
        "_compatible_count": int(len(compatible)),
    }


def _fill(builder, count: int) -> list[dict]:
    """Call `builder()` until `count` non-None (accepted) profiles are produced."""
    results = []
    attempts = 0
    while len(results) < count:
        attempts += 1
        if attempts > MAX_ATTEMPTS:
            raise RuntimeError(f"Could not generate enough profiles after {MAX_ATTEMPTS} attempts")
        profile = builder()
        if profile is not None:
            results.append(profile)
    return results


def generate_profiles(df: pd.DataFrame, rng: random.Random) -> list[dict]:
    profiles = []

    for forced_diet in FORCED_STANDARD_DIETS:
        profiles += _fill(lambda forced_diet=forced_diet: _make_standard(df, rng, forced_diet=forced_diet), 1)
    profiles += _fill(lambda: _make_standard(df, rng), N_STANDARD - len(FORCED_STANDARD_DIETS))

    profiles += [_make_sparse(df, rng, cold_start=True) for _ in range(N_SPARSE_COLD)]
    profiles += [_make_sparse(df, rng, cold_start=False) for _ in range(N_SPARSE_WITH_HISTORY)]

    for diet, liked in DIET_VS_LIKED:
        profiles += _fill(lambda diet=diet, liked=liked: _make_conflicting_diet_vs_liked(df, rng, diet, liked), 1)
    for diet in DIET_VS_HISTORY:
        profiles += _fill(lambda diet=diet: _make_conflicting_diet_vs_history(df, rng, diet), 1)
    for cuisine, exclusions in CUISINE_VS_EXCLUSIONS:
        profiles += _fill(
            lambda cuisine=cuisine, exclusions=exclusions: _make_conflicting_cuisine_vs_exclusions(
                df, rng, cuisine, exclusions
            ),
            1,
        )

    # IDs are assigned only now, after every profile has been accepted, so
    # they run p_001..p_050 with no gaps regardless of how many attempts
    # (rejections) each profile took to generate.
    for i, profile in enumerate(profiles, start=1):
        profile["profile_id"] = f"p_{i:03d}"
        profiles[i - 1] = {"profile_id": profile.pop("profile_id"), **profile}

    return profiles


def _report(profiles: list[dict]) -> None:
    by_type = {}
    for p in profiles:
        by_type.setdefault(p["profile_type"], 0)
        by_type[p["profile_type"]] += 1
    print("Counts by type:", by_type)

    conflict_counts = {}
    for p in profiles:
        if p["profile_type"] == "conflicting":
            conflict_counts.setdefault(p["conflict_pattern"], 0)
            conflict_counts[p["conflict_pattern"]] += 1
    print("Conflict pattern counts:", conflict_counts)

    def value_counts(field_getter):
        counts = {}
        for p in profiles:
            for v in field_getter(p):
                counts[v] = counts.get(v, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: -kv[1]))

    print("Cuisine distribution:", value_counts(lambda p: p["cuisine_prefs"]))
    print("Time bucket distribution:", value_counts(lambda p: [p["max_cook_minutes"]]))
    print("Diet distribution:", value_counts(lambda p: p["diet"]))
    print("Liked-ingredient distribution:", value_counts(lambda p: p["liked_ingredients"]))
    print("Exclusion distribution:", value_counts(lambda p: p["exclusions"]))

    compatible_counts = [p["_compatible_count"] for p in profiles]
    compatible_counts.sort()
    n = len(compatible_counts)
    median = compatible_counts[n // 2] if n % 2 else (compatible_counts[n // 2 - 1] + compatible_counts[n // 2]) / 2
    print(f"Compatible-recipe count: min={compatible_counts[0]}, median={median}")


def main() -> None:
    df = _load_recipes()
    rng = random.Random(SEED)
    profiles = generate_profiles(df, rng)

    _report(profiles)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    to_write = [{k: v for k, v in p.items() if not k.startswith("_")} for p in profiles]
    with OUT_PATH.open("w") as f:
        json.dump(to_write, f, indent=2)
    print(f"\nWrote {len(to_write)} profiles to {OUT_PATH}")


if __name__ == "__main__":
    main()
