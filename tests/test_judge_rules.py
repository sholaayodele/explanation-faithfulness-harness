"""Unit tests for judge.rules.check_minutes_mismatch."""

import unittest

from judge.rules import check_minutes_mismatch


class TestMinutesMismatch(unittest.TestCase):
    def test_limit_and_cook_time_both_present_no_mismatch(self):
        # c_0165's actual text: a time-limit mention ("60-minute ... window") and a
        # separate, correct stated cook time ("30 minutes") that matches the recipe.
        text = (
            "This pork chop dish fits comfortably within your 60-minute cooking "
            "window, coming together in about 30 minutes. It's a light, low-calorie "
            "option built on pork, fennel, and tomatoes."
        )
        self.assertFalse(check_minutes_mismatch(text, recipe_minutes=30, max_cook_minutes=60))

    def test_stated_cook_time_mismatch(self):
        text = "Ready in 25 minutes."
        self.assertTrue(check_minutes_mismatch(text, recipe_minutes=30, max_cook_minutes=45))

    def test_only_limit_phrase_no_mismatch(self):
        text = "This fits comfortably within your 45-minute limit."
        self.assertFalse(check_minutes_mismatch(text, recipe_minutes=30, max_cook_minutes=45))


if __name__ == "__main__":
    unittest.main()
