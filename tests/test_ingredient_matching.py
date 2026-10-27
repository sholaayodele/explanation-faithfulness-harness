"""Regression tests for ingredient_matching.EXCLUSION_FORMS deriving from CATEGORY_TERMS.

Covers the bug that let a "flank steak" recipe slip past a no_beef exclusion:
CATEGORY_TERMS["beef"] had the "steak" synonym for main_ingredient resolution,
but the old hand-maintained EXCLUSION_FORMS["no_beef"] only had the literal
word "beef".
"""

import unittest

from ingredient_matching import CATEGORY_TERMS, matches_exclusion

CATEGORY_TO_EXCLUSION = {"pork": "no_pork", "beef": "no_beef", "shrimp": "no_shellfish"}


class TestExclusionFormsCoverCategoryTerms(unittest.TestCase):
    def test_every_category_synonym_triggers_its_exclusion(self):
        for category, code in CATEGORY_TO_EXCLUSION.items():
            for synonym in CATEGORY_TERMS[category]:
                with self.subTest(category=category, synonym=synonym):
                    self.assertTrue(
                        matches_exclusion([synonym], code),
                        f"{synonym!r} (a {category} synonym) should trigger {code!r} but doesn't",
                    )

    def test_flank_steak_triggers_no_beef(self):
        self.assertTrue(matches_exclusion(["flank steak", "hoisin sauce"], "no_beef"))

    def test_prosciutto_triggers_no_pork(self):
        self.assertTrue(matches_exclusion(["prosciutto", "basil"], "no_pork"))

    def test_unrelated_broth_does_not_trigger_no_pork(self):
        # EXCLUSION_FORMS derives from CATEGORY_TERMS only, not generic
        # animal-derived forms, so an unrelated broth/stock never produces a
        # false-positive exclusion for a different meat.
        self.assertFalse(matches_exclusion(["chicken broth", "onion"], "no_pork"))


if __name__ == "__main__":
    unittest.main()
