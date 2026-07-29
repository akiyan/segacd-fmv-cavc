#!/usr/bin/env python3
"""Regression tests for analysis R2V and run metrics."""
from __future__ import annotations

import unittest

import layout_preview as layout
import r2v_model
from tile_alloc import count_slot_runs, slot_runs


class AnalysisDmaTests(unittest.TestCase):
    def test_r2v_digits_follow_the_observed_maximum(self) -> None:
        self.assertEqual(layout.r2v_value_digits(1792), 4)
        self.assertEqual(layout.r2v_label_template(5183), "R2V:0000")

    def test_frame0_is_excluded_from_timed_metrics(self) -> None:
        self.assertEqual(layout.timed_metric_value(0, 1518), 0)
        self.assertEqual(layout.timed_metric_value(1, 185), 185)

    def test_run_digits_cover_full_h40_worst_case(self) -> None:
        self.assertEqual(layout.H40_FULL_TILES, 1120)
        self.assertEqual(layout.dma_run_worst_case(1120), 1120)
        self.assertEqual(layout.DMA_RUN_DIGITS, 4)
        self.assertEqual(layout.run_label_template(), "Run:0000")

    def test_dma_tile_capacity_pays_for_the_full_name_table(self) -> None:
        # H40/24: 2.5 VBLANKs * 7790 B - 1120 * 2 B, then / 32 B.
        self.assertEqual(layout.dma_tile_capacity("H40", 24, 1120), 538)

    def test_r2v_name_table_words_are_mode_grid_and_cadence_aware(self) -> None:
        self.assertEqual(
            r2v_model.name_table_words("H40", 40, 28, 30),
            64 * 28,
        )
        self.assertEqual(
            r2v_model.name_table_words("H40", 40, 28, 24),
            40 * 28 + r2v_model.DEBUG_HUD_WORDS,
        )
        self.assertEqual(
            r2v_model.name_table_words("H32", 32, 18, 30),
            32 * 18 + r2v_model.DEBUG_HUD_WORDS,
        )

    def test_r2v_components_count_short_runs_without_repairs(self) -> None:
        components = r2v_model.calculate_words(
            [210], [20], [12], [1], [1792])
        self.assertEqual(int(components["pattern_words"][0]), 3360)
        self.assertEqual(int(components["repair_words"][0]), 8)
        self.assertEqual(int(components["cram_words"][0]), 64)
        self.assertEqual(int(components["words"][0]), 5224)

    def test_slot_run_count_matches_packed_order(self) -> None:
        self.assertEqual(count_slot_runs([]), 0)
        self.assertEqual(count_slot_runs([4]), 1)
        self.assertEqual(count_slot_runs([4, 5, 6, 9, 10, 3]), 3)

    def test_slot_runs_are_the_player_records(self) -> None:
        self.assertEqual(slot_runs([]), [])
        self.assertEqual(slot_runs([4, 5, 6, 9, 10, 3]), [(4, 3), (9, 2), (3, 1)])
        # Pool wrap is a discontinuity; reuse entries have already been omitted.
        self.assertEqual(slot_runs([1398, 1399, 0, 1]), [(1398, 2), (0, 2)])


if __name__ == "__main__":
    unittest.main()
