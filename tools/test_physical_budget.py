#!/usr/bin/env python3
"""Tests for construction-time physical BODY and PrgBuf limits."""

from __future__ import annotations

import unittest

import numpy as np

import physical_budget
import stream_schedule


class PhysicalBudgetPlanTests(unittest.TestCase):
    def build(self, desired):
        return physical_budget.build_plan(
            desired,
            fps=15,
            cells=760,
            audio_frame_bytes=736,
            max_updates=760,
            max_runs=480,
            ring_capacity_patterns=422 * 1024 // 32,
            prebuffer_capacity_patterns=382 * 1024 // 32,
            frame_sectors=5,
            fill=True,
        )

    def test_overloaded_prediction_is_reduced_before_encoding(self) -> None:
        desired = np.asarray([0] + [480] * 80, np.int64)
        plan = self.build(desired)

        self.assertTrue(plan.schedule["feasible"])
        self.assertTrue(np.all(plan.prg_pattern_limits <= desired))
        self.assertGreater(int(plan.shortfall_patterns.sum()), 0)
        self.assertTrue(np.all(plan.control_sectors <= 5))

    def test_final_trace_may_only_shrink_the_proven_envelope(self) -> None:
        rng = np.random.default_rng(0x53454354)
        desired = np.asarray(
            [0] + rng.integers(0, 481, size=200).tolist(),
            np.int64,
        )
        plan = self.build(desired)
        actual_loads = np.asarray([
            rng.integers(0, int(limit) + 1)
            for limit in plan.prg_pattern_limits
        ], np.int64)
        actual_loads[0] = 0
        updates = rng.integers(0, 761, size=len(desired), dtype=np.int64)
        runs = rng.integers(0, 481, size=len(desired), dtype=np.int64)
        updates[0] = 0
        runs[0] = 0
        actual_control = stream_schedule.control_block_lengths(
            updates,
            runs,
            cells=760,
            audio_frame_bytes=736,
        )
        actual_control[0] = 0

        result = stream_schedule.schedule_payload_ring(
            actual_loads,
            actual_control,
            fps=15,
            ring_capacity_patterns=422 * 1024 // 32,
            prebuffer_capacity_patterns=382 * 1024 // 32,
            frame_sectors=5,
            fill=True,
            control_sector_envelope=plan.control_sectors,
        )

        self.assertTrue(result["feasible"])
        self.assertTrue(result["control_envelope"])
        self.assertTrue(np.all(
            result["n_ctrl_sec"] <= plan.control_sectors))
        np.testing.assert_array_equal(
            result["control_reserved_sectors"], plan.control_sectors)

    def test_unused_control_reservation_becomes_pad_not_apply_data(self) -> None:
        desired = np.asarray([0] + [480] * 8, np.int64)
        plan = self.build(desired)
        result = stream_schedule.schedule_payload_ring(
            np.zeros(len(desired), np.int64),
            np.zeros(len(desired), np.int64),
            fps=15,
            ring_capacity_patterns=422 * 1024 // 32,
            prebuffer_capacity_patterns=382 * 1024 // 32,
            frame_sectors=5,
            fill=True,
            control_sector_envelope=plan.control_sectors,
        )

        self.assertTrue(np.any(plan.control_sectors[1:] > 0))
        self.assertEqual(int(result["n_ctrl_sec"].sum()), 0)
        self.assertEqual(
            int(result["body_useful_control_bytes"].sum()), 0)
        self.assertGreater(int(result["body_pad_bytes"].sum()), 0)

    def test_frame_zero_is_header_staging_not_a_timed_limit(self) -> None:
        plan = self.build([999, 0, 0])
        self.assertEqual(int(plan.prg_pattern_limits[0]), 0)
        result = stream_schedule.schedule_payload_ring(
            [1195, 0, 0],
            [4096, 0, 0],
            fps=15,
            ring_capacity_patterns=422 * 1024 // 32,
            prebuffer_capacity_patterns=382 * 1024 // 32,
            frame_sectors=5,
            fill=True,
            control_sector_envelope=plan.control_sectors,
        )
        self.assertTrue(result["feasible"])
        self.assertEqual(result["f0_cold"], 1195)

    def test_reserved_control_sectors_reject_an_oversized_final_stream(self) -> None:
        plan = physical_budget.build_plan(
            [0, 0, 0],
            fps=15,
            cells=8,
            audio_frame_bytes=0,
            max_updates=0,
            max_runs=0,
            ring_capacity_patterns=128,
            prebuffer_capacity_patterns=64,
            frame_sectors=5,
        )
        with self.assertRaisesRegex(
                stream_schedule.ScheduleError, "control envelope cannot meet"):
            stream_schedule.schedule_payload_ring(
                [0, 0, 0],
                [0, 4096, 4096],
                fps=15,
                ring_capacity_patterns=128,
                prebuffer_capacity_patterns=64,
                frame_sectors=5,
                fill=True,
                control_sector_envelope=plan.control_sectors,
            )


if __name__ == "__main__":
    unittest.main()
