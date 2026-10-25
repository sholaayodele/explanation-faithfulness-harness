"""Reason detection, ranking, weighting and confidence for the matcher."""

PRIORITY = ["LIKED_INGREDIENT", "CUISINE_MATCH", "DIET_COMPLIANT", "SIMILAR_TO_RATED", "NEW_TO_YOU", "TIME_FIT"]
STRONG = {"LIKED_INGREDIENT", "CUISINE_MATCH", "DIET_COMPLIANT"}
WEAK = {"SIMILAR_TO_RATED", "NEW_TO_YOU", "TIME_FIT"}
WEIGHTS_BY_COUNT = {1: [1.0], 2: [0.6, 0.4], 3: [0.5, 0.3, 0.2]}


def detect_candidates(profile: dict, recipe: dict, rated_rows: list[dict], compliant_rated_rows: list[dict]) -> list[dict]:
    """All reason candidates a (profile, recipe) pair supports, unranked, uncapped."""
    candidates = []
    cuisine_prefs = profile.get("cuisine_prefs", [])
    liked = profile.get("liked_ingredients", [])
    diet = profile.get("diet", [])
    recipe_cuisine = recipe.get("cuisine")
    recipe_main_ingredient = recipe.get("main_ingredient")

    if liked and recipe_main_ingredient in liked:
        candidates.append({"code": "LIKED_INGREDIENT", "field": "liked_ingredients", "value": recipe_main_ingredient})

    if recipe_cuisine is not None and recipe_cuisine in cuisine_prefs:
        candidates.append({"code": "CUISINE_MATCH", "field": "cuisine_prefs", "value": recipe_cuisine})

    if diet:
        candidates.append({"code": "DIET_COMPLIANT", "field": "diet", "value": diet[0]})

    if recipe_cuisine is not None and recipe_main_ingredient is not None:
        for rr in compliant_rated_rows:
            if rr.get("cuisine") == recipe_cuisine and rr.get("main_ingredient") == recipe_main_ingredient:
                candidates.append({"code": "SIMILAR_TO_RATED", "field": "rated_highly", "value": recipe_cuisine})
                break

    if recipe_cuisine is not None and recipe_cuisine not in cuisine_prefs:
        rated_cuisines = {rr.get("cuisine") for rr in rated_rows}
        if recipe_cuisine not in rated_cuisines:
            candidates.append({"code": "NEW_TO_YOU", "field": "cuisine_prefs", "value": recipe_cuisine})

    max_cook_minutes = profile["max_cook_minutes"]
    if max_cook_minutes <= 30 or recipe["minutes"] <= 0.5 * max_cook_minutes:
        candidates.append({
            "code": "TIME_FIT", "field": "max_cook_minutes",
            "value": max_cook_minutes, "recipe_minutes": recipe["minutes"],
        })
    return candidates


def rank_top(candidates: list[dict], exclude_codes: set[str] | None = None, limit: int = 3) -> list[dict]:
    """Keep the top `limit` candidates by fixed priority order, dropping any excluded codes."""
    exclude_codes = exclude_codes or set()
    pool = [c for c in candidates if c["code"] not in exclude_codes]
    pool.sort(key=lambda c: PRIORITY.index(c["code"]))
    return pool[:limit]


def assign_weights(top: list[dict]) -> list[dict]:
    """Weight by rank, per the fixed count->weights table."""
    weights = WEIGHTS_BY_COUNT[len(top)]
    return [{**c, "weight": w} for c, w in zip(top, weights)]


def confidence_for(top: list[dict]) -> str:
    """high: strong primary + a strong/SIMILAR_TO_RATED second reason.
    medium: strong primary alone or with only TIME_FIT/NEW_TO_YOU support;
             weak primary with any support.
    low: a single weak reason (or fallback, handled separately)."""
    primary = top[0]["code"]
    if primary in STRONG:
        if len(top) == 1:
            return "medium"
        secondary = top[1]["code"]
        return "high" if (secondary in STRONG or secondary == "SIMILAR_TO_RATED") else "medium"
    return "medium" if len(top) >= 2 else "low"
