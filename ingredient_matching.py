"""Shared ingredient-term vocabulary and whole-word matching.

Single source of truth for data_prep (main_ingredient, vegetarian/vegan
contamination) and schema/validator (excluded_by), so the two can't drift.
"""

import re

# main_ingredient categories, each with its synonyms. Cuts like "pork chop"
# already contain the literal word "pork", so only true synonyms are added.
CATEGORY_TERMS: dict[str, list[str]] = {
    "chicken": ["chicken"],
    "beef": ["beef", "steak", "sirloin", "brisket", "chuck"],
    "pork": ["pork", "bacon", "ham", "prosciutto"],
    "shrimp": ["shrimp", "prawn"],
    "salmon": ["salmon"],
}
MUSHROOM_TERMS: list[str] = ["mushroom"]

# Any other meat/fish term: not one of the 6 likes/synonyms above, but still
# disqualifies main_ingredient (blocks mushroom, nulls out any candidate) and
# counts toward vegetarian/vegan contamination.
OTHER_PROTEIN_TERMS: list[str] = [
    "turkey", "lamb", "veal", "sausage", "tuna", "fish",
    "crab", "lobster", "clam", "mussel", "oyster", "scallop", "anchovy", "gelatin",
    "frank", "hot dog", "pepperoni", "salami", "chorizo", "kielbasa", "bratwurst",
    "meatball", "ground meat", "lunch meat", "deli meat", "spam", "venison", "duck",
]
_SHELLFISH_SPECIES: list[str] = ["crab", "lobster", "clam", "mussel", "oyster", "scallop"]

# excluded_by code -> forms it covers, any of which disqualify a recipe.
# Derived from CATEGORY_TERMS so an exclusion can never miss a synonym that
# main_ingredient resolution already recognizes - this is exactly the bug
# that let a "flank steak" recipe (main_ingredient="beef" via the "steak"
# synonym) slip past a no_beef exclusion when EXCLUSION_FORMS was a separate,
# hand-maintained list that only had the literal word "beef". no_shellfish
# additionally covers the species names in OTHER_PROTEIN_TERMS plus the bare
# word "shellfish" itself, which is exclusion-only - never a main_ingredient
# category on its own, so it isn't in CATEGORY_TERMS.
EXCLUSION_FORMS: dict[str, list[str]] = {
    "no_pork": CATEGORY_TERMS["pork"],
    "no_beef": CATEGORY_TERMS["beef"],
    "no_shellfish": CATEGORY_TERMS["shrimp"] + _SHELLFISH_SPECIES + ["shellfish"],
    "no_peanut": ["peanut"],
    "no_mushroom": MUSHROOM_TERMS,
    "no_cilantro": ["cilantro"],
}

# A LIKED_INGREDIENT value (or a profile's liked_ingredients entry) contradicts
# an excluded_by code if the two are the same category - chicken and salmon
# have no excluded_by code, so they can never contradict one.
LIKED_INGREDIENT_EXCLUSION_CODE: dict[str, str] = {
    "beef": "no_beef",
    "pork": "no_pork",
    "shrimp": "no_shellfish",
    "mushroom": "no_mushroom",
}

# Modifier forms that disqualify an otherwise-matching ingredient:
# - condiment forms (e.g. "steak sauce") aren't meat themselves.
# - animal-derived forms (e.g. "chicken broth") still are, but aren't the
#   dish's *main* ingredient - so they're excluded from main_ingredient only,
#   not from the vegetarian/vegan contamination check.
CONDIMENT_FORMS: list[str] = ["sauce", "seasoning"]
ANIMAL_DERIVED_FORMS: list[str] = ["broth", "stock", "bouillon", "gravy", "drippings"]

# Single source of truth: every main_ingredient term (likes + other-protein),
# so the contamination check can't drift from main_ingredient's vocabulary.
MEAT_FISH_CONTAMINANTS: list[str] = sorted(
    {term for terms in CATEGORY_TERMS.values() for term in terms} | set(OTHER_PROTEIN_TERMS)
)


def mentions_term(ingredient: str, term: str) -> bool:
    """Whole-word match (plus optional trailing 's'), not a bare prefix.

    A bare prefix match would wrongly catch unrelated words that merely start
    with the term, e.g. "ham" inside "hamburger" or "beef" inside "beefsteak".
    Works for multi-word terms too (e.g. "hot dog"), matched as a phrase.
    """
    return re.search(r"\b" + re.escape(term) + r"s?\b", ingredient, re.IGNORECASE) is not None


def matches_exclusion(ingredients: list[str], exclusion_code: str) -> bool:
    """True if any ingredient matches any form of the given excluded_by code."""
    terms = EXCLUSION_FORMS.get(exclusion_code, [])
    return any(mentions_term(ing, term) for ing in ingredients for term in terms)


def is_condiment_form(ingredient: str) -> bool:
    return any(mentions_term(ingredient, form) for form in CONDIMENT_FORMS)


def is_animal_derived_form(ingredient: str) -> bool:
    return any(mentions_term(ingredient, form) for form in ANIMAL_DERIVED_FORMS)
