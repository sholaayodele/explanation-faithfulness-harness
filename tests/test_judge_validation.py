"""Unit tests for judge.run.validate_judgment's consistency checks."""

import unittest

from judge.run import validate_judgment

VALID_TYPES = {
    "fabrication", "misattribution", "non_causal_reason", "omission",
    "overclaiming", "exclusion_violation", "sensitive_inference",
}


def _judgment(verdict, failure_types, claim_supported):
    return {
        "claims": [{"text": "x", "about": "customer", "source": "none",
                    "supported": claim_supported, "failure_type": None}],
        "primary_reason_stated": True,
        "calibration_ok": True,
        "safe_ok": True,
        "failure_types": failure_types,
        "verdict": verdict,
        "rationale": "r",
    }


class TestUnsupportedClaimConsistency(unittest.TestCase):
    def test_unsupported_claim_with_fail_verdict_is_consistent(self):
        data = _judgment("fail", ["fabrication"], claim_supported=False)
        self.assertEqual(validate_judgment(data, VALID_TYPES), [])

    def test_unsupported_claim_with_pass_verdict_is_flagged(self):
        data = _judgment("pass", [], claim_supported=False)
        errors = validate_judgment(data, VALID_TYPES)
        self.assertTrue(any("supported=false" in e for e in errors))

    def test_all_supported_with_pass_verdict_is_consistent(self):
        data = _judgment("pass", [], claim_supported=True)
        self.assertEqual(validate_judgment(data, VALID_TYPES), [])


if __name__ == "__main__":
    unittest.main()
