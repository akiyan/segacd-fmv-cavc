from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import resource_tokens


class ResourceTokenTests(unittest.TestCase):
    def env(self, root: Path):
        return patch.dict(os.environ, {
            "SEGACD_RESOURCE_ROOT": str(root),
            "SEGACD_CPU_TOKENS": "2",
            "SEGACD_GPU_TOKENS": "1",
            "SEGACD_EMU_TOKENS": "1",
        }, clear=False)

    def test_exact_request_never_keeps_partial_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            first = resource_tokens.acquire_tokens("cpu", count=1)
            with self.assertRaises(resource_tokens.ResourceBusyError):
                resource_tokens.acquire_tokens(
                    "cpu", count=2, wait=False)
            second = resource_tokens.acquire_tokens(
                "cpu", count=1, wait=False)
            self.assertEqual(second.count, 1)
            second.release()
            first.release()

    def test_release_makes_slots_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            lease = resource_tokens.acquire_tokens("cpu", count=2)
            with self.assertRaises(resource_tokens.ResourceBusyError):
                resource_tokens.acquire_tokens(
                    "cpu", count=1, wait=False)
            lease.release()
            replacement = resource_tokens.acquire_tokens(
                "cpu", count=2, wait=False)
            replacement.release()

    def test_different_stems_do_not_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            first = resource_tokens.acquire_stem("movie-a")
            second = resource_tokens.acquire_stem("movie-b")
            second.release()
            first.release()

    def test_same_stem_fails_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            first = resource_tokens.acquire_stem("movie-a")
            with self.assertRaises(resource_tokens.ResourceBusyError):
                resource_tokens.acquire_stem("movie-a")
            first.release()

    def test_inherited_stem_marker_is_reentrant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            env = resource_tokens.held_stem_environment("movie-a")
            with patch.dict(os.environ, env, clear=True):
                nested = resource_tokens.acquire_stem("movie-a")
            self.assertTrue(nested.reentrant)
            self.assertEqual(nested.count, 0)

    def test_shell_run_holds_requested_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            result = subprocess.run([
                sys.executable,
                str(Path(resource_tokens.__file__)),
                "run",
                "--resource", "cpu",
                "--count", "2",
                "--capacity", "2",
                "--",
                "sh", "-c", "printf token-shell-ok",
            ], check=False, capture_output=True, text=True, env=os.environ)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "token-shell-ok")


if __name__ == "__main__":
    unittest.main()
