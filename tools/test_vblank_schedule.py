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
        self.assertEqual(sum(groups[1:]), 20)


class PlannerTests(unittest.TestCase):
    def test_cold280_one_run_fits_two_h40_vblanks(self) -> None:
        plan = schedule.plan_frame(
            ((0, 280, 0, 0),), 2,
            mode="H40", interblank_nt=True)
        self.assertEqual(plan.groups, 2)
        self.assertEqual(sum(plan.patterns), 280)
        self.assertLessEqual(
            abs(plan.pattern_work[0] - (
                plan.pattern_work[1] + plan.final_reserved_work)),
            schedule.WORDS_PER_PATTERN,
        )

    def test_timed_fragmentation_is_rejected_instead_of_adding_a_field(
            self,
    ) -> None:
        runs = tuple((index * 2, 1, 0, 0) for index in range(280))
        with self.assertRaisesRegex(ValueError, "across 2 VBlanks"):
            schedule.plan_frame(
                runs, 2, mode="H40", interblank_nt=True)

    def test_frame0_full_refresh_matches_six_group_measurement(self) -> None:
        plan = schedule.plan_frame(
            ((0, 1120, 0, 0),), 1,
            mode="H40", interblank_nt=True,
            max_groups=schedule.MAX_VBLANK_GROUPS)
        self.assertEqual(plan.groups, 6)
        self.assertEqual(sum(plan.patterns), 1120)

    def test_short_runs_are_not_cut_at_a_group_boundary(self) -> None:
        runs = (
            (0, 230, 0, 0),
            (300, 2, 0, 0),
            (400, 48, 0, 0),
        )
        plan = schedule.plan_frame(
            runs, 2, mode="H40", interblank_nt=True)
        self.assertNotEqual(plan.patterns[0], 231)
        self.assertEqual(sum(plan.patterns), 280)

    def test_encoded_table_is_always_eight_words(self) -> None:
        plan = schedule.plan_frame(
            (), 3, mode="H40", interblank_nt=False)
        self.assertEqual(plan.groups, 3)
        self.assertEqual(
            len(plan.patterns), schedule.MAX_VBLANK_GROUPS)
        self.assertEqual(plan.patterns, (0,) * schedule.MAX_VBLANK_GROUPS)

    def test_non_nt_final_group_reserves_hud_format_and_flip(self) -> None:
        self.assertEqual(
            schedule.final_reserved_work(
                "H32", interblank_nt=False, palette_switch=False),
            schedule.DEBUG_FORMAT_WORK
            + schedule.DEBUG_STAGE_WORK
            + schedule.FLIP_GUARD_WORK,
        )

    def test_interblank_nt_removes_the_full_nt_dma_from_final_group(
            self,
    ) -> None:
        self.assertEqual(
            schedule.final_reserved_work(
                "H40", interblank_nt=True, palette_switch=False),
            schedule.DEBUG_STAGE_WORK + schedule.FLIP_GUARD_WORK,
        )

    def test_every_modeled_group_fits_its_physical_blank(self) -> None:
        plan = schedule.plan_frame(
            tuple((index * 3, 3, 0, 0) for index in range(80)),
            2,
            mode="H32",
            interblank_nt=False,
            palette_switch=True,
            max_groups=schedule.MAX_VBLANK_GROUPS,
        )
        limit = schedule.VBLANK_WORK_LIMIT["H32"]
        for group in range(plan.groups):
            reserve = (
                plan.final_reserved_work if group == plan.groups - 1 else 0)
            self.assertLessEqual(plan.pattern_work[group] + reserve, limit)


if __name__ == "__main__":
    unittest.main()
