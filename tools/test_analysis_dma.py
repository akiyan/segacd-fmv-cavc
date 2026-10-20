#!/usr/bin/env python3
"""Regression tests for analysis R2V and run metrics."""
from __future__ import annotations

import unittest

import layout_preview as layout
import r2v_model
from tile_alloc import slot_runs


class AnalysisDmaTests(unittest.TestCase):

    def test_frame0_is_excluded_from_timed_metrics(self) -> None:
        self.assertEqual(layout.timed_metric_value(0, 1518), 0)
        self.assertEqual(layout.timed_metric_value(1, 185), 185)

    def test_r2v_name_table_words_match_single_nt_and_debug_routes(self) -> None:
        self.assertEqual(
            r2v_model.name_table_words(40, 28, 30),
            1768 + 52,
        )
        self.assertEqual(
            r2v_model.name_table_words(40, 28, 24),
            1768 + 52,
        )
        self.assertEqual(
            r2v_model.name_table_words(40, 19, 15),
            1192 + 52,
        )
        self.assertEqual(
            r2v_model.name_table_words(40, 28, 24, debug_hud_words=0),
            1768,
        )
        with self.assertRaises(ValueError):
            r2v_model.name_table_words(41, 28, 30)

    def test_slot_runs_are_the_player_records(self) -> None:
        self.assertEqual(slot_runs([]), [])
        self.assertEqual(slot_runs([4, 5, 6, 9, 10, 3]), [(4, 3), (9, 2), (3, 1)])
        # Pool wrap is a discontinuity; reuse entries have already been omitted.
        self.assertEqual(slot_runs([1398, 1399, 0, 1]), [(1398, 2), (0, 2)])


if __name__ == "__main__":
    unittest.main()
