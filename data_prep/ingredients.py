"""Ingredient-matching helpers: main_ingredient, key_ingredients, veg/vegan contamination."""

from ingredient_matching import (
    CATEGORY_TERMS,
    MEAT_FISH_CONTAMINANTS,
    MUSHROOM_TERMS,
    OTHER_PROTEIN_TERMS,
    is_animal_derived_form,
    is_condiment_form,
    mentions_term,
)

PANTRY_STAPLES = ["salt", "pepper", "water", "oil", "olive oil", "butter", "sugar", "flour", "garlic", "onion"]


def _category_present(ingredients: list[str], terms: list[str]) -> bool:
    """True if any ingredient mentions a term, excluding condiment and animal-derived forms.

    E.g. "steak sauce" doesn't count toward beef, and "chicken broth" doesn't
    count toward chicken - neither is the dish's main ingredient.
    """
    return any(
        any(mentions_term(ing, term) for term in terms)
        and not is_condiment_form(ing)
        and not is_animal_derived_form(ing)
        for ing in ingredients
    )


def determine_main_ingredient(ingredients: list[str]) -> str | None:
    """Pick the single main ingredient among the 6 likes (with synonyms), or None.

    Condiment forms ("steak sauce") and animal-derived forms ("chicken broth")
    don't count for any term. Any "other protein" term (meat/fish outside the
    6 likes/synonyms) disqualifies main_ingredient entirely - it blocks
    mushroom and nulls out any candidate. Otherwise, 2+ distinct likes
    categories matching is ambiguous (None); a meat/fish match wins over
    mushroom; mushroom alone is returned if nothing else matched.
    """
    if _category_present(ingredients, OTHER_PROTEIN_TERMS):
        return None

    matched = {category for category, terms in CATEGORY_TERMS.items() if _category_present(ingredients, terms)}
    if len(matched) >= 2:
        return None
    if len(matched) == 1:
        return next(iter(matched))
    if _category_present(ingredients, MUSHROOM_TERMS):
        return "mushroom"
    return None


def is_vegetarian_vegan_contaminated(ingredients: list[str]) -> bool:
    """True if any ingredient mentions a meat or fish term, in any form.

    Condiment forms ("steak sauce") are excluded (typically meat-free), but
    animal-derived forms ("chicken broth") still count - unlike
    main_ingredient, a vegetarian recipe containing chicken broth is still
    a real contradiction.
    """
    return any(
        mentions_term(ing, term) and not is_condiment_form(ing)
        for ing in ingredients
        for term in MEAT_FISH_CONTAMINANTS
    )


def _is_pantry_staple(ingredient: str) -> bool:
    return any(mentions_term(ingredient, staple) for staple in PANTRY_STAPLES)


def key_ingredients_for(ingredients: list[str], limit: int = 5) -> list[str]:
    """Up to `limit` non-pantry-staple ingredients, in their original order."""
    return [ing for ing in ingredients if not _is_pantry_staple(ing)][:limit]
