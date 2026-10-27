"""Validator regression test for the no_beef/CATEGORY_TERMS synonym bug
that let c_0121-c_0124 (LIKED_INGREDIENT=beef, excluded_by no_beef, a
"steak"-cut recipe) pass validation undetected.
"""

import copy
import unittest

from schema.validator import validate_payload

_BASE_PAYLOAD = {
    "schema_version": "0.1",
    "case_id": "c_9999",
    "recipe": {
        "id": "food_999999",
        "name": "test flank steak",
        "cuisine": "chinese",
        "minutes": 20,
        "main_ingredient": "beef",
        "ingredients": ["flank steak", "soy sauce", "garlic"],
        "key_ingredients": ["flank steak"],
        "diet_tags": [],
        "other_tags": [],
    },
    "reasons": [
        {"code": "LIKED_INGREDIENT", "field": "liked_ingredients", "value": "beef", "weight": 1.0},
    ],
    "confidence": "high",
    "fallback": None,
    "excluded_by": ["no_beef"],
    "case_type": "standard",
    "profile_context": {
        "cuisine_prefs": [],
        "diet": [],
        "liked_ingredients": ["beef"],
        "exclusions": ["no_beef"],
        "max_cook_minutes": 30,
        "rated_highly_names": [],
    },
}


class TestExcludedIngredientSynonymCaught(unittest.TestCase):
    def test_flank_steak_with_no_beef_exclusion_fails_validation(self):
        payload = copy.deepcopy(_BASE_PAYLOAD)
        errors = validate_payload(payload)
        self.assertTrue(
            any("no_beef" in e for e in errors),
            f"expected an excluded_by/no_beef violation, got: {errors}",
        )


if __name__ == "__main__":
    unittest.main()
