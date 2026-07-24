#!/usr/bin/env python3
"""Tests for construction-time physical BODY and PrgBuf limits."""

from __future__ import annotations

import unittest

import numpy as np

import physical_budget
import stream_schedule


class PhysicalBudgetPlanTests(unittest.TestCase):
    def test_timed_body_trace_ignores_boot_only_frame_zero(self) -> None:
        source = np.array([1195, 7, 8], np.int64)

        timed = physical_budget.timed_body_trace(source)

        np.testing.assert_array_equal(timed, [0, 7, 8])
        np.testing.assert_array_equal(source, [1195, 7, 8])

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

    def test_joint_plan_reassigns_worst_case_descriptor_pad_to_payload(self) -> None:
        desired = np.asarray([0] + [480] * 200, np.int64)
        preloaded = np.asarray([0] + [24] * 200, np.int64)
        baseline = self.build(desired)
        joint = physical_budget.build_joint_plan(
            desired,
            max_preloaded_patterns=preloaded,
            fps=15,
            cells=760,
            audio_frame_bytes=736,
            max_updates=760,
            max_cold=480,
            ring_capacity_patterns=422 * 1024 // 32,
            prebuffer_capacity_patterns=382 * 1024 // 32,
            frame_sectors=5,
        )

        self.assertTrue(joint.schedule["feasible"])
        self.assertGreater(
            int(joint.prg_pattern_limits.sum()),
            int(baseline.prg_pattern_limits.sum()),
        )
        self.assertLess(
            int(joint.control_sectors.sum()),
            int(baseline.control_sectors.sum()),
        )
        self.assertTrue(np.all(
            joint.prg_pattern_limits + preloaded
            <= joint.cold_pattern_limits))
        self.assertTrue(np.all(joint.cold_pattern_limits <= 480))

    def test_joint_plan_cold_limit_proves_identity_run_envelope(self) -> None:
        desired = np.asarray([0] + [480] * 80, np.int64)
        preloaded = np.asarray([0] + [16] * 80, np.int64)
        joint = physical_budget.build_joint_plan(
            desired,
            max_preloaded_patterns=preloaded,
            fps=15,
            cells=760,
            audio_frame_bytes=736,
            max_updates=760,
            max_cold=480,
            ring_capacity_patterns=422 * 1024 // 32,
            prebuffer_capacity_patterns=382 * 1024 // 32,
            frame_sectors=5,
        )
        actual_control = stream_schedule.control_block_lengths(
            np.full(len(desired), 760, np.int64),
            joint.cold_pattern_limits,
            cells=760,
            audio_frame_bytes=736,
        )
        actual_control[0] = 0
        self.assertTrue(np.all(
            actual_control <= joint.control_block_limits))

    def test_shared_sector_savings_fund_the_next_frame_before_decisions(
            self) -> None:
        def second_limit(first_control_bytes):
            planner = physical_budget.SharedSectorPlanner(
                3,
                max_prg_patterns=480,
                max_cold_patterns=480,
                prebuffer_capacity_patterns=640,
                frame_sectors=5,
            )
            first = planner.begin_frame(0)
            self.assertEqual(first.prg_patterns, 0)
            planner.commit_frame(
                0, prg_patterns=0, cold_patterns=0,
                control_block_bytes=0)
            frame1 = planner.begin_frame(1)
            self.assertEqual(frame1.prg_patterns, 480)
            planner.commit_frame(
                1, prg_patterns=480, cold_patterns=480,
                control_block_bytes=first_control_bytes)
            return planner.begin_frame(2).prg_patterns

        self.assertEqual(second_limit(1000), 416)
        self.assertEqual(second_limit(4096), 352)

    def test_shared_sector_prefix_rounds_control_and_payload_separately(
            self) -> None:
        with self.assertRaisesRegex(
                stream_schedule.ScheduleError, "shared BODY prefix"):
            physical_budget.verify_shared_sector_prefix(
                [0, 64, 640],
                [0, 5 * 2048, 0],
                prebuffer_capacity_patterns=64,
                frame_sectors=5,
            )

    def test_shared_sector_plan_freezes_realized_one_pass_trace(self) -> None:
        planner = physical_budget.SharedSectorPlanner(
            4,
            max_prg_patterns=480,
            max_cold_patterns=480,
            prebuffer_capacity_patterns=640,
            frame_sectors=5,
        )
        realized_prg = [0, 320, 320, 320]
        realized_control = [0, 1500, 1600, 1700]
        for frame in range(4):
            limit = planner.begin_frame(frame)
            self.assertLessEqual(realized_prg[frame], limit.prg_patterns)
            planner.commit_frame(
                frame,
                prg_patterns=realized_prg[frame],
                cold_patterns=realized_prg[frame],
                control_block_bytes=realized_control[frame],
            )
        plan = planner.finish([0, 480, 480, 480])
        np.testing.assert_array_equal(
            plan.realized_prg_patterns, realized_prg)
        np.testing.assert_array_equal(
            plan.realized_control_block_bytes, realized_control)
        self.assertEqual(plan.planning_passes, 1)

    def test_shared_sector_forward_ring_check_limits_a_late_burst(
            self) -> None:
        planner = physical_budget.SharedSectorPlanner(
            5,
            max_prg_patterns=128,
            max_cold_patterns=128,
            prebuffer_capacity_patterns=64,
            frame_sectors=1,
            fps=15,
            ring_capacity_patterns=128,
            maximum_control_block_bytes=[0, 0, 0, 0, 0],
        )
        loads = [0, 0, 128]
        for frame, load in enumerate(loads):
            limit = planner.begin_frame(frame)
            self.assertLessEqual(load, limit.prg_patterns)
            planner.commit_frame(
                frame,
                prg_patterns=load,
                cold_patterns=load,
                control_block_bytes=0,
            )
        # The prefix-only ledger would permit 64 patterns here. The finite
        # ring proof sees that they would need an impossible earlier delivery.
        self.assertEqual(planner.begin_frame(3).prg_patterns, 0)


if __name__ == "__main__":
    unittest.main()
