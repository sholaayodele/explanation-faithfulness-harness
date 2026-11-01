"""Regression tests: data_prep.run, data_prep.profiles and matcher.run must
refuse to overwrite their committed output file unless --force is passed.

Each module's main() checks OUT_PATH.exists() before doing any real work, so
these tests patch OUT_PATH to a temp file and never touch the real repo data
or require RAW_recipes.csv/profiles.json/recipes_clean.csv to exist.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import data_prep.profiles as profiles_module
import data_prep.run as data_prep_run_module
import matcher.run as matcher_module


class TestOverwriteGuard(unittest.TestCase):
    def _assert_refuses_without_force(self, module, module_name):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "existing_output"
            out_path.write_text("original content")
            with patch.object(module, "OUT_PATH", out_path):
                with self.assertRaises(SystemExit, msg=f"{module_name}.main() should refuse without --force"):
                    module.main(force=False)
                self.assertEqual(
                    out_path.read_text(), "original content",
                    f"{module_name}.main() must not touch the existing file when it refuses",
                )

    def test_data_prep_run_refuses_to_overwrite(self):
        self._assert_refuses_without_force(data_prep_run_module, "data_prep.run")

    def test_data_prep_profiles_refuses_to_overwrite(self):
        self._assert_refuses_without_force(profiles_module, "data_prep.profiles")

    def test_matcher_run_refuses_to_overwrite(self):
        self._assert_refuses_without_force(matcher_module, "matcher.run")

    def test_data_prep_run_allows_overwrite_with_force_flag_set(self):
        # force=True must skip the refusal path. build() is patched to raise a
        # sentinel right after the guard, so this stays fast and isolated -
        # it doesn't run the real (slow, RAW_recipes.csv-dependent) pipeline.
        sentinel = RuntimeError("sentinel: reached past the overwrite guard")
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "existing_output"
            out_path.write_text("original content")
            with patch.object(data_prep_run_module, "OUT_PATH", out_path), \
                 patch.object(data_prep_run_module, "build", side_effect=sentinel):
                with self.assertRaises(RuntimeError) as ctx:
                    data_prep_run_module.main(force=True)
                self.assertIs(ctx.exception, sentinel, "main(force=True) should not refuse via the overwrite guard")


if __name__ == "__main__":
    unittest.main()
