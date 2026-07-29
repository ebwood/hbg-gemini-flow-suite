from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import suite_cli
from media_cleanup import retain_or_remove_original


class SuiteCliTests(unittest.TestCase):
    def test_pop_option_supports_equals_form(self) -> None:
        arguments, value = suite_cli.pop_option(
            ["t2v", "prompt", "--out-dir=demo", "--aspect", "9:16"],
            "--out-dir",
        )
        self.assertEqual(value, "demo")
        self.assertEqual(arguments, ["t2v", "prompt", "--aspect", "9:16"])

    def test_pop_option_rejects_missing_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires a value"):
            suite_cli.pop_option(["--out-dir"], "--out-dir")

    def test_normalized_output_dir_preserves_absolute_path(self) -> None:
        absolute = Path("/tmp/gemini-flow-suite-test")
        self.assertEqual(
            suite_cli.normalized_output_dir(str(absolute), Path("/fallback")),
            absolute,
        )

    def test_flag_parses_false_values(self) -> None:
        with patch.dict(os.environ, {"FEATURE_FLAG": "off"}):
            self.assertFalse(suite_cli.flag("FEATURE_FLAG", True))


class CleanupTests(unittest.TestCase):
    def test_retain_original_moves_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "input.png"
            output_dir = root / "result"
            source.write_bytes(b"image")

            retained = retain_or_remove_original(source, output_dir, True)

            expected = output_dir / ".originals" / "input.png"
            self.assertEqual(retained, str(expected))
            self.assertTrue(expected.is_file())
            self.assertFalse(source.exists())

    def test_remove_original_deletes_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "input.mp4"
            source.write_bytes(b"video")

            retained = retain_or_remove_original(source, Path(temp), False)

            self.assertIsNone(retained)
            self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()
