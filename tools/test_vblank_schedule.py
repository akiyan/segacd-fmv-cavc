#!/usr/bin/env python3
"""Regression tests for encoder-authored VBlank work groups."""
from __future__ import annotations

import unittest

import vblank_schedule as schedule


class CadenceTests(unittest.TestCase):
    def test_fixed_cadences_keep_their_authoritative_interval(self) -> None:
        self.assertEqual(
            schedule.nominal_group_counts(5, 30),
            (1, 2, 2, 2, 2))
        self.assertEqual(
            schedule.nominal_group_counts(4, 15),
            (1, 4, 4, 4))

    def test_24fps_uses_natural_two_three_distribution(self) -> None:
        groups = schedule.nominal_group_counts(9, 24)
        self.assertEqual(groups[:6], (1, 2, 3, 2, 3, 2))
        self.assertEqual(set(groups[1:]), {2, 3})


class PlannerTests(unittest.TestCase):
    def test_cold280_one_run_fits_two_h40_vblanks(self) -> None:
        plan = schedule.plan_frame(
            ((0, 280, 0, 0),), 2,
            mode="H40", nt_dma_flip=True)
        self.assertEqual(plan.groups, 2)
        self.assertEqual(sum(plan.patterns), 280)
        self.assertGreater(plan.patterns[0], plan.patterns[1])

    def test_fragmentation_adds_a_safe_warning_group(self) -> None:
        runs = tuple((index * 2, 1, 0, 0) for index in range(280))
        plan = schedule.plan_frame(
            runs, 2, mode="H40", nt_dma_flip=True)
        self.assertGreater(plan.groups, 2)
        self.assertEqual(sum(plan.patterns), 280)

    def test_frame0_full_refresh_matches_six_group_measurement(self) -> None:
        plan = schedule.plan_frame(
            ((0, 1120, 0, 0),), 1,
            mode="H40", nt_dma_flip=True)
        self.assertEqual(plan.groups, 6)
        self.assertEqual(sum(plan.patterns), 1120)

    def test_short_runs_are_not_cut_at_a_group_boundary(self) -> None:
        runs = (
            (0, 230, 0, 0),
            (300, 2, 0, 0),
            (400, 48, 0, 0),
        )
        plan = schedule.plan_frame(
            runs, 2, mode="H40", nt_dma_flip=True)
        self.assertNotEqual(plan.patterns[0], 231)
        self.assertEqual(sum(plan.patterns), 280)

    def test_encoded_table_is_always_eight_words(self) -> None:
        plan = schedule.plan_frame(
            (), 3, mode="H40", nt_dma_flip=False)
        self.assertEqual(plan.groups, 3)
        self.assertEqual(
            len(plan.patterns), schedule.MAX_VBLANK_GROUPS)
        self.assertEqual(plan.patterns, (0,) * schedule.MAX_VBLANK_GROUPS)


if __name__ == "__main__":
    unittest.main()
