"""Ingredient-matching helpers: main_ingredient, key_ingredients, veg/vegan contamination."""

from ingredient_matching import mentions_term

BROTH_FORMS = ["broth", "stock", "bouillon"]

# main_ingredient categories, each with its synonyms. Cuts like "pork chop"
# already contain the literal word "pork", so only true synonyms are added.
CATEGORY_TERMS = {
    "chicken": ["chicken"],
    "beef": ["beef", "steak", "sirloin", "brisket", "chuck"],
    "pork": ["pork", "bacon", "ham", "prosciutto"],
    "shrimp": ["shrimp", "prawn"],
    "salmon": ["salmon"],
}
MUSHROOM_TERMS = ["mushroom"]

# Any other meat/fish term: not one of the 6 likes/synonyms above, but still
# disqualifies main_ingredient (blocks mushroom, nulls out any candidate).
# Includes processed/ambiguous meats, since those can't be cleanly assigned
# to one of the 6 likes either.
OTHER_PROTEIN_TERMS = [
    "turkey", "lamb", "veal", "sausage", "tuna", "fish",
    "crab", "lobster", "clam", "mussel", "oyster", "scallop", "anchovy", "gelatin",
    "frank", "hot dog", "pepperoni", "salami", "chorizo", "kielbasa", "bratwurst",
    "meatball", "ground meat", "lunch meat", "deli meat", "spam", "venison", "duck",
]

# Broader than the above: used only to check whether a vegetarian/vegan-tagged
# recipe actually contains meat or fish (any form, including broth - unlike
# main_ingredient, broth/stock/bouillon still counts here).
MEAT_FISH_CONTAMINANTS = [
    "chicken", "beef", "pork", "bacon", "ham", "turkey", "lamb", "veal", "sausage",
    "shrimp", "prawn", "salmon", "tuna", "fish", "crab", "lobster", "clam", "mussel",
    "oyster", "scallop", "anchovy", "gelatin",
]

PANTRY_STAPLES = ["salt", "pepper", "water", "oil", "olive oil", "butter", "sugar", "flour", "garlic", "onion"]


def _is_broth_form(ingredient: str) -> bool:
    return any(mentions_term(ingredient, form) for form in BROTH_FORMS)


def _category_present(ingredients: list[str], terms: list[str]) -> bool:
    return any(
        any(mentions_term(ing, term) for term in terms) and not _is_broth_form(ing)
        for ing in ingredients
    )


def determine_main_ingredient(ingredients: list[str]) -> str | None:
    """Pick the single main ingredient among the 6 likes (with synonyms), or None.

    Broth/stock/bouillon forms don't count for any term. Any "other protein"
    term (meat/fish outside the 6 likes/synonyms) disqualifies main_ingredient
    entirely - it blocks mushroom and nulls out any candidate. Otherwise, 2+
    distinct likes categories matching is ambiguous (None); a meat/fish match
    wins over mushroom; mushroom alone is returned if nothing else matched.
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
    """True if any ingredient mentions a meat or fish term, in any form."""
    return any(mentions_term(ing, term) for ing in ingredients for term in MEAT_FISH_CONTAMINANTS)


def _is_pantry_staple(ingredient: str) -> bool:
    return any(mentions_term(ingredient, staple) for staple in PANTRY_STAPLES)


def key_ingredients_for(ingredients: list[str], limit: int = 5) -> list[str]:
    """Up to `limit` non-pantry-staple ingredients, in their original order."""
    return [ing for ing in ingredients if not _is_pantry_staple(ing)][:limit]
