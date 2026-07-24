#!/usr/bin/env python3
"""Tests for the optional physical slot-locality pipeline."""
from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

import slot_locality_pipeline as pipeline


class SlotLocalityPipelineTests(unittest.TestCase):
    def test_policy_defaults_off_and_accepts_explicit_on(self) -> None:
        self.assertFalse(pipeline.Policy().enabled)
        self.assertFalse(pipeline.policy_from_env({}).enabled)
        self.assertTrue(
            pipeline.policy_from_env({"CBRSIM_SLOT_LOCALITY": "true"}).enabled)
        self.assertFalse(
            pipeline.policy_from_env({"CBRSIM_SLOT_LOCALITY": "0"}).enabled)

    def test_policy_rejects_unknown_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            pipeline.policy_from_env({"CBRSIM_SLOT_LOCALITY": "sometimes"})

    def test_disabled_initial_plan_is_identity(self) -> None:
        plan, kind = pipeline.select_initial_plan(
            pipeline.Policy(enabled=False),
            [(), (0, 2), (1, 3)],
            4,
            cold_cap=2,
            packed_execution=True,
        )
        self.assertEqual(kind, "identity-off")
        self.assertEqual(plan.physical_by_logical, (0, 1, 2, 3))
        np.testing.assert_array_equal(
            plan.baseline_runs, plan.optimized_runs)

    def test_disabled_decision_record_omits_map(self) -> None:
        record = pipeline.decision_record(
            pipeline.Policy(enabled=False),
            stage="",
            player_execution="packed_suffix",
            physical_by_logical=np.arange(4),
            baseline_runs=np.array([0, 2]),
            optimized_runs=np.array([0, 2]),
            risk_frames=np.array([False, True]),
        )
        self.assertFalse(record["enabled"])
        self.assertEqual(record["trace"], "identity")
        self.assertNotIn("physical_by_logical", record)

    def test_only_enabled_top_level_invocation_needs_multiple_passes(self) -> None:
        common = {
            "stage": "",
            "emit_decisions": "out/decisions.pkl",
            "loaded_map": "",
        }
        self.assertTrue(pipeline.requires_multi_pass(
            pipeline.Policy(enabled=True), **common))
        self.assertFalse(pipeline.requires_multi_pass(
            pipeline.Policy(enabled=False), **common))
        self.assertFalse(pipeline.requires_multi_pass(
            pipeline.Policy(enabled=True),
            **{**common, "stage": "seed"}))

    def test_enabled_pipeline_runs_seed_then_accounting(self) -> None:
        calls = []

        def fake_run(command, *, env, check):
            calls.append((tuple(command), dict(env), bool(check)))
            return subprocess.CompletedProcess(command, 0)

        def fake_derive(_decision_log, output_path, **_kwargs):
            np.save(output_path, np.arange(4, dtype=np.uint16))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with (
                    patch.object(pipeline.subprocess, "run", fake_run),
                    patch.object(
                        pipeline, "derive_completed_map", fake_derive)):
                pipeline.run_accounting_passes(
                    ("python", "sim.py"),
                    {"BASE": "1"},
                    policy=pipeline.Policy(enabled=True),
                    decision_log=root / "decisions.pkl",
                    map_path=root / "map.npy",
                    retry_path=root / "retry.npy",
                    packed_execution=True,
                )
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0][1]["CBRSIM_SLOT_LOCALITY_STAGE"], "seed")
        self.assertEqual(
            calls[1][1]["CBRSIM_SLOT_LOCALITY_STAGE"], "final")
        self.assertTrue(calls[0][2])
        self.assertFalse(calls[1][2])


if __name__ == "__main__":
    unittest.main()
