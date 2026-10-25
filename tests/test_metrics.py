"""Unit tests for metrics.run.wilson_ci."""

import unittest

from metrics.run import wilson_ci


class TestWilsonCI(unittest.TestCase):
    def test_known_interval(self):
        # 80/100: Wilson 95% interval (z=1.96) is approximately (0.7112, 0.8666).
        lo, hi = wilson_ci(80, 100)
        self.assertAlmostEqual(lo, 0.7112, places=3)
        self.assertAlmostEqual(hi, 0.8666, places=3)

    def test_zero_n_returns_zero_interval(self):
        self.assertEqual(wilson_ci(0, 0), (0.0, 0.0))

    def test_interval_contains_point_estimate(self):
        lo, hi = wilson_ci(37, 50)
        self.assertLessEqual(lo, 37 / 50)
        self.assertGreaterEqual(hi, 37 / 50)


if __name__ == "__main__":
    unittest.main()
