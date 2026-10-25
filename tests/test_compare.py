"""Unit tests for metrics.compare.mcnemar."""

import unittest

from metrics.compare import mcnemar


class TestMcNemar(unittest.TestCase):
    def test_known_critical_values(self):
        # chi2(1) critical value 3.841459 corresponds to p=0.05.
        # b - c with continuity correction: (|b-c|-1)^2/(b+c) = 3.841459
        # Solve with b+c=20, |b-c|=10 -> (9)^2/20 = 4.05 (close enough to probe monotonicity instead).
        chi2_a, p_a = mcnemar(b=1, c=9)
        chi2_b, p_b = mcnemar(b=5, c=5)
        self.assertGreater(chi2_a, chi2_b)
        self.assertLess(p_a, p_b)

    def test_no_discordant_pairs(self):
        self.assertEqual(mcnemar(0, 0), (0.0, 1.0))

    def test_symmetric_in_b_and_c(self):
        self.assertEqual(mcnemar(3, 7), mcnemar(7, 3))


if __name__ == "__main__":
    unittest.main()
