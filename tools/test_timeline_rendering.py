#!/usr/bin/env python3
"""Regression tests for whole-movie timeline scaling."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import analysis_style as style  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


timeline = load_module(
    "timeline_render_scale",
    ROOT / ".agents/skills/timeline/scripts/render_timeline.py",
)
hudline = load_module(
    "hudline_render_scale",
    ROOT / ".agents/skills/hudline/scripts/render_hudline.py",
)


class TimelineRenderingTests(unittest.TestCase):
    def test_codec_run_scale_uses_timed_observed_maximum(self):
        values = np.asarray([255, 3, 9, 4], np.float64)
        self.assertEqual(timeline.run_scale_max(values), 9)
        self.assertEqual(timeline.run_scale_max(np.asarray([255, 0])), 1)

    def test_r2v_counts_cpu_words_once_and_one_repair_per_dma_run(self):
        components = timeline.calculate_r2v_words(
            np.asarray([0, 3360, 3312]),
            np.asarray([0, 96, 31]),
            np.asarray([0, 75, 19]),
            np.asarray([0, 0, 1]),
        )
        np.testing.assert_array_equal(
            components["repair_words"], [0, 21, 12])
        np.testing.assert_array_equal(
            components["name_table_words"], [1792, 1792, 1792])
        np.testing.assert_array_equal(
            components["cram_words"], [0, 0, 64])
        np.testing.assert_array_equal(
            components["words"], [1792, 5173, 5180])

    def test_r2v_scale_uses_exact_timed_calculated_maximum(self):
        values = np.asarray([9999, 1792, 5183, 2400], np.int64)
        self.assertEqual(timeline.r2v_scale_max(values), 5183)
        self.assertEqual(
            timeline.r2v_scale_max(np.asarray([9999, 0], np.int64)), 1)

    def test_r2v_rejects_more_short_runs_than_total_runs(self):
        with self.assertRaisesRegex(ValueError, "short-run"):
            timeline.calculate_r2v_words(
                np.asarray([16]), np.asarray([1]), np.asarray([2]),
                np.asarray([0]))

    def test_hud_run_scale_uses_timed_observed_maximum(self):
        data = {
            "display_vblanks": np.asarray([np.nan, 2, 2], np.float64),
            "cold_runs_low8": np.asarray([255, 7, 12], np.float64),
        }
        gate = {
            "content_fps": 30,
            "limits": {"S": 0, "D": 0, "R": 0, "M": 1, "J": 25},
            "jitter_headroom_kib": 20,
        }
        specs = hudline.row_specs(data, gate, 2)
        run = next(spec for spec in specs if spec.key == "cold_runs_low8")
        self.assertEqual(run.maximum, 12)

    def test_word_banks_are_combined_before_pixel_scaling(self):
        capacities = {"Prg": 60, "Wr0": 20, "Wr1": 20}
        remaining = {"Prg": 60, "Wr0": 6, "Wr1": 6}
        raw_segments = style.meter_supply_segments(
            remaining, capacities, height=10)
        self.assertEqual(raw_segments[0][0], "Wrd")
        self.assertEqual(dict(raw_segments), {"Wrd": 1, "Prg": 6})

    def test_positive_combined_word_balance_stays_visible(self):
        capacities = {"Prg": 60, "Wr0": 20, "Wr1": 20}
        remaining = {"Prg": 60, "Wr0": 1, "Wr1": 1}
        segments = dict(
            style.meter_supply_segments(remaining, capacities, height=10)
        )
        self.assertEqual(segments["Wrd"], 1)
        self.assertLessEqual(sum(segments.values()), 10)


if __name__ == "__main__":
    unittest.main()
