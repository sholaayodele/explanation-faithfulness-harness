"""Build data/processed/recipes_clean.csv from the raw Food.com CSVs.

Usage: python -m data_prep.run
"""

import ast
import json
from pathlib import Path

import pandas as pd

from data_prep.ingredients import determine_main_ingredient, is_vegetarian_vegan_contaminated, key_ingredients_for

CUISINES = [
    "italian", "mexican", "indian", "chinese", "thai",
    "greek", "french", "middle-eastern", "cajun", "caribbean",
]
DIET_TAGS = ["vegetarian", "vegan", "gluten-free"]
HEALTH_TAGS = ["low-calorie", "low-carb", "low-sodium", "low-cholesterol", "healthy"]

RAW_RECIPES = Path("data/raw/RAW_recipes.csv")
RAW_INTERACTIONS = Path("data/raw/RAW_interactions.csv")
OUT_PATH = Path("data/processed/recipes_clean.csv")

OUTPUT_COLUMNS = [
    "id", "name", "minutes", "cuisine", "diet_tags", "main_ingredient",
    "ingredients", "key_ingredients", "other_tags",
    "n_ratings", "avg_rating", "is_popular",
]
LIST_COLUMNS = ("diet_tags", "ingredients", "key_ingredients", "other_tags")


def _parse_list(raw: str) -> list[str]:
    try:
        return ast.literal_eval(raw)
    except (ValueError, SyntaxError, TypeError):
        return []


def _assign_cuisine(tags: list[str]) -> str | None:
    matched = [c for c in CUISINES if c in tags]
    return matched[0] if len(matched) == 1 else None


def _assign_diet_tags(tags: list[str]) -> list[str]:
    return [d for d in DIET_TAGS if d in tags]


def _assign_other_tags(tags: list[str]) -> list[str]:
    return [h for h in HEALTH_TAGS if h in tags]


def _ratings_stats(interactions: pd.DataFrame) -> pd.DataFrame:
    return interactions.groupby("recipe_id")["rating"].agg(n_ratings="count", avg_rating="mean")


def _check_no_vegetarian_vegan_meat(df: pd.DataFrame) -> None:
    """Invariant: no vegetarian/vegan recipe may have a meat/fish main_ingredient."""
    is_veg = df["diet_tags"].apply(lambda d: "vegetarian" in d or "vegan" in d)
    bad = df[is_veg & df["main_ingredient"].isin(["chicken", "beef", "pork", "shrimp", "salmon"])]
    if len(bad) > 0:
        raise AssertionError(
            f"{len(bad)} vegetarian/vegan recipe(s) have a meat/fish main_ingredient: {bad['id'].tolist()}"
        )


def build() -> tuple[pd.DataFrame, int]:
    """Return (cleaned recipes dataframe, count of veg/vegan recipes dropped by the meat check)."""
    recipes = pd.read_csv(RAW_RECIPES)
    interactions = pd.read_csv(RAW_INTERACTIONS)

    recipes["tags_parsed"] = recipes["tags"].apply(_parse_list)
    recipes["ingredients_parsed"] = recipes["ingredients"].apply(_parse_list)

    mask = recipes["tags_parsed"].apply(lambda t: "main-dish" in t) & recipes["minutes"].between(10, 120)
    filtered = recipes[mask].copy()

    filtered["cuisine"] = filtered["tags_parsed"].apply(_assign_cuisine)
    filtered["diet_tags"] = filtered["tags_parsed"].apply(_assign_diet_tags)
    filtered["other_tags"] = filtered["tags_parsed"].apply(_assign_other_tags)
    filtered["main_ingredient"] = filtered["ingredients_parsed"].apply(determine_main_ingredient)
    filtered["key_ingredients"] = filtered["ingredients_parsed"].apply(key_ingredients_for)

    is_veg_tagged = filtered["diet_tags"].apply(lambda d: "vegetarian" in d or "vegan" in d)
    is_contaminated = filtered["ingredients_parsed"].apply(is_vegetarian_vegan_contaminated)
    dropped_mask = is_veg_tagged & is_contaminated
    n_dropped_veg = int(dropped_mask.sum())
    filtered = filtered[~dropped_mask].copy()

    stats = _ratings_stats(interactions)
    filtered = filtered.merge(stats, left_on="id", right_index=True, how="left")
    filtered["n_ratings"] = filtered["n_ratings"].fillna(0).astype(int)
    filtered["is_popular"] = (filtered["n_ratings"] >= 20) & (filtered["avg_rating"] >= 4.0)

    filtered = filtered.drop(columns=["tags", "ingredients"]).rename(columns={"ingredients_parsed": "ingredients"})
    out = filtered[OUTPUT_COLUMNS]
    _check_no_vegetarian_vegan_meat(out)
    return out, n_dropped_veg


def _report(df: pd.DataFrame, n_dropped_veg: int) -> None:
    n = len(df)
    print(f"Final row count: {n}")

    def pct(covered: int) -> float:
        return 100 * covered / n if n else 0.0

    cuisine_cov = pct(df["cuisine"].notna().sum())
    diet_cov = pct((df["diet_tags"].apply(len) > 0).sum())
    main_ing_cov = pct(df["main_ingredient"].notna().sum())
    other_cov = pct((df["other_tags"].apply(len) > 0).sum())

    print(f"cuisine coverage: {cuisine_cov:.1f}%")
    print(f"diet_tags coverage: {diet_cov:.1f}%")
    print(f"main_ingredient coverage: {main_ing_cov:.1f}%")
    print(f"other_tags coverage: {other_cov:.1f}%")
    print(f"vegetarian/vegan recipes dropped by meat check: {n_dropped_veg}")
    print(f"is_popular count: {int(df['is_popular'].sum())}")


def main() -> None:
    out, n_dropped_veg = build()
    print("Invariant check (no vegetarian/vegan recipe has a meat/fish main_ingredient): PASSED")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    to_write = out.copy()
    for col in LIST_COLUMNS:
        to_write[col] = to_write[col].apply(json.dumps)
    to_write.to_csv(OUT_PATH, index=False)

    _report(out, n_dropped_veg)

    print(f"\nWrote {len(out)} rows to {OUT_PATH}")
    print("\n=== 20 random rows (seed=42) ===")
    sample = out.sample(20, random_state=42)[["name", "cuisine", "main_ingredient", "key_ingredients", "diet_tags"]]
    with pd.option_context("display.max_colwidth", 60, "display.width", 200):
        print(sample.to_string(index=False))


if __name__ == "__main__":
    main()
