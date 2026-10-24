"""Structural + business-rule validation for explanation payloads (v0.1)."""

import json
import re
from pathlib import Path
from typing import Any

import jsonschema

_SCHEMA_PATH = Path(__file__).parent / "payload_v0_1.json"

_EXCLUSION_FORMS: dict[str, list[str]] = {
    "no_pork": ["pork", "bacon", "ham"],
    "no_beef": ["beef"],
    "no_shellfish": ["shellfish", "shrimp", "prawn", "crab", "lobster", "clam", "mussel", "oyster", "scallop"],
    "no_peanut": ["peanut"],
    "no_mushroom": ["mushroom"],
    "no_cilantro": ["cilantro"],
}


def _load_schema() -> dict[str, Any]:
    with _SCHEMA_PATH.open() as f:
        return json.load(f)


_SCHEMA = _load_schema()


def _structural_errors(payload: dict[str, Any]) -> list[str]:
    validator = jsonschema.Draft202012Validator(_SCHEMA)
    errors = []
    for err in validator.iter_errors(payload):
        path = "/".join(str(p) for p in err.absolute_path) or "<root>"
        errors.append(f"{path}: {err.message}")
    return errors


def _ingredient_mentions(ingredients: list[str], term: str) -> bool:
    pattern = re.compile(r"\b" + re.escape(term) + r"\w*", re.IGNORECASE)
    return any(pattern.search(ing) for ing in ingredients)


def _reason_by_code(reasons: list[dict[str, Any]], code: str) -> dict[str, Any] | None:
    for reason in reasons:
        if reason.get("code") == code:
            return reason
    return None


def _business_rule_errors(payload: dict[str, Any]) -> list[str]:
    errors = []
    recipe = payload.get("recipe", {})
    reasons = payload.get("reasons", [])
    case_type = payload.get("case_type")
    confidence = payload.get("confidence")
    fallback = payload.get("fallback")
    excluded_by = payload.get("excluded_by", [])

    weights = [r.get("weight") for r in reasons if isinstance(r.get("weight"), (int, float))]
    if len(weights) == len(reasons) and len(set(weights)) != len(weights):
        errors.append("reasons: weights must be strictly decreasing (no ties)")

    cuisine_match = _reason_by_code(reasons, "CUISINE_MATCH")
    if cuisine_match is not None:
        if recipe.get("cuisine") is None:
            errors.append("CUISINE_MATCH present but recipe.cuisine is null")
        elif cuisine_match.get("value") != recipe.get("cuisine"):
            errors.append(
                f"CUISINE_MATCH.value ({cuisine_match.get('value')!r}) != recipe.cuisine ({recipe.get('cuisine')!r})"
            )

    time_fit = _reason_by_code(reasons, "TIME_FIT")
    if time_fit is not None:
        recipe_minutes = time_fit.get("recipe_minutes")
        if recipe.get("minutes") is None:
            errors.append("TIME_FIT present but recipe.minutes is null")
        elif recipe_minutes is None:
            errors.append("TIME_FIT missing recipe_minutes")
        elif recipe_minutes != recipe.get("minutes"):
            errors.append(
                f"TIME_FIT.recipe_minutes ({recipe_minutes}) != recipe.minutes ({recipe.get('minutes')})"
            )
        elif time_fit.get("value") is not None and recipe_minutes > time_fit.get("value"):
            errors.append(
                f"TIME_FIT.recipe_minutes ({recipe_minutes}) > TIME_FIT.value ({time_fit.get('value')})"
            )

    diet_compliant = _reason_by_code(reasons, "DIET_COMPLIANT")
    if diet_compliant is not None and diet_compliant.get("value") not in recipe.get("diet_tags", []):
        errors.append(
            f"DIET_COMPLIANT.value ({diet_compliant.get('value')!r}) not in recipe.diet_tags ({recipe.get('diet_tags')!r})"
        )

    liked_ingredient = _reason_by_code(reasons, "LIKED_INGREDIENT")
    if liked_ingredient is not None:
        if recipe.get("main_ingredient") is None:
            errors.append("LIKED_INGREDIENT present but recipe.main_ingredient is null")
        elif liked_ingredient.get("value") != recipe.get("main_ingredient"):
            errors.append(
                f"LIKED_INGREDIENT.value ({liked_ingredient.get('value')!r}) != recipe.main_ingredient ({recipe.get('main_ingredient')!r})"
            )

    ingredients = recipe.get("ingredients", [])
    for code in excluded_by:
        for term in _EXCLUSION_FORMS.get(code, []):
            if _ingredient_mentions(ingredients, term):
                errors.append(f"excluded_by contains {code!r} but recipe.ingredients mentions {term!r}")
                break

    is_fallback_case = case_type == "fallback"
    is_fallback_value = fallback == "POPULAR_FALLBACK"
    has_popular_fallback_reason = _reason_by_code(reasons, "POPULAR_FALLBACK") is not None

    if is_fallback_case != is_fallback_value:
        errors.append(
            f"fallback ({fallback!r}) and case_type ({case_type!r}) are inconsistent "
            "(fallback == 'POPULAR_FALLBACK' iff case_type == 'fallback')"
        )
    if is_fallback_case and (len(reasons) != 1 or not has_popular_fallback_reason):
        errors.append("case_type 'fallback' requires reasons to contain exactly one POPULAR_FALLBACK reason")
    if has_popular_fallback_reason and not is_fallback_value:
        errors.append("reasons contains POPULAR_FALLBACK but fallback is not set to 'POPULAR_FALLBACK'")

    if case_type == "low_confidence" and confidence != "low":
        errors.append(f"case_type 'low_confidence' requires confidence == 'low', got {confidence!r}")

    if case_type != "missing_fields" and recipe.get("minutes") is None:
        errors.append("recipe.minutes is null but case_type is not 'missing_fields'")

    return errors


def validate_payload(payload: dict[str, Any]) -> list[str]:
    """Return all validation errors for a payload; an empty list means it is valid."""
    errors = _structural_errors(payload)
    if errors:
        return errors
    return _business_rule_errors(payload)
