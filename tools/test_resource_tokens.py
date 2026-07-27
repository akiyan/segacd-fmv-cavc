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

    def test_default_emu_capacity_is_qualified_two(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(resource_tokens.resource_capacity("emu"), 2)

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

    def test_requested_workers_honor_capacity_override_and_stage_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            self.assertEqual(resource_tokens.requested_cpu_workers(), 2)
            with patch.dict(os.environ, {"CBRSIM_WORKERS": "1"}):
                self.assertEqual(resource_tokens.requested_cpu_workers(), 1)
            with patch.dict(os.environ, {
                "SEGACD_CPU_TOKENS": "8",
                "CBRSIM_WORKERS": "6",
            }):
                self.assertEqual(
                    resource_tokens.requested_cpu_workers(limit=4), 4)

    def test_requested_workers_reject_nonpositive_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            with patch.dict(os.environ, {"CBRSIM_WORKERS": "0"}):
                with self.assertRaises(resource_tokens.ResourceTokenError):
                    resource_tokens.requested_cpu_workers()

    def test_cpu_workers_cli_reports_shared_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp)):
            result = subprocess.run([
                sys.executable,
                str(Path(resource_tokens.__file__)),
                "cpu-workers",
                "--limit", "1",
            ], check=False, capture_output=True, text=True, env=os.environ)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "1\n")


if __name__ == "__main__":
    unittest.main()
