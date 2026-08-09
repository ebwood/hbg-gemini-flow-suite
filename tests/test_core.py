from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import suite_cli
from media_cleanup import clean_video, retain_or_remove_original
from scripts.cdp_bridge import rewrite_host_header
from sync_auth import is_google_cookie


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

    def test_gemini_diamond_retry_uses_original_after_no_mark_skip(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "gemini_web_video_sample.mp4"
            output = root / "clean.mp4"
            source.write_bytes(b"video")
            commands: list[list[str]] = []

            def fake_run_checked(command: list[str]) -> None:
                commands.append(command)
                destination = Path(command[command.index("--output") + 1])
                destination.write_bytes(b"clean")

            skipped = subprocess.CompletedProcess(
                args=[], returncode=1, stdout="[SKIP] no visible mark\n", stderr=""
            )
            with patch("media_cleanup.subprocess.run", return_value=skipped), patch(
                "media_cleanup.run_checked", side_effect=fake_run_checked
            ):
                self.assertEqual(clean_video(source, output), output.resolve())

            diamond_command = commands[0]
            self.assertEqual(
                diamond_command[diamond_command.index("--input") + 1],
                str(source.resolve()),
            )
            self.assertTrue(output.is_file())


class FlowCompatibilityTests(unittest.TestCase):
    def test_flow_auth_keeps_google_com_and_dot_google_cookies(self) -> None:
        self.assertTrue(is_google_cookie({"domain": ".google.com"}))
        self.assertTrue(is_google_cookie({"domain": "accounts.google.com"}))
        self.assertTrue(is_google_cookie({"domain": "labs.google"}))
        self.assertTrue(is_google_cookie({"domain": ".labs.google"}))
        self.assertFalse(is_google_cookie({"domain": "example.com"}))

    def test_cdp_bridge_rewrites_only_the_host_header(self) -> None:
        request = (
            b"GET /json/version HTTP/1.1\r\n"
            b"Host: host.docker.internal:19223\r\n"
            b"Connection: close\r\n\r\n"
        )
        rewritten = rewrite_host_header(request, 9223)
        self.assertIn(b"Host: 127.0.0.1:9223", rewritten)
        self.assertIn(b"GET /json/version HTTP/1.1", rewritten)


if __name__ == "__main__":
    unittest.main()
