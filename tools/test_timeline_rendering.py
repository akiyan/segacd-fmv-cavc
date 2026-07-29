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

    def test_req_cold_cap_guide_uses_the_req_cell_scale(self):
        self.assertEqual(timeline.req_cold_cap_y(100, 101, 400, 100), 175)
        self.assertEqual(timeline.req_cold_cap_y(100, 101, 400, 0), 200)
        self.assertEqual(timeline.req_cold_cap_y(100, 101, 400, 999), 100)

    def test_hud_run_scale_uses_timed_observed_maximum(self):
        data = {
            "display_vblanks": np.asarray([np.nan, 2, 2], np.float64),
            "cold_runs": np.asarray([255, 7, 12], np.float64),
        }
        gate = {
            "content_fps": 30,
            "limits": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "vblank_spill": 1,
                "prgbuf_jitter_peak_kib": 25,
            },
            "jitter_headroom_kib": 20,
        }
        specs = hudline.row_specs(data, gate, 2)
        run = next(spec for spec in specs if spec.key == "cold_runs")
        self.assertEqual(run.maximum, 12)

    def test_gpgx_transfer_rows_follow_the_gate_rows_with_one_pattern_scale(self):
        data = {
            "display_vblanks": np.asarray([np.nan, 2, 3], np.float64),
            "pattern_dma_commands": np.asarray([999, 12, 31], np.float64),
            "pattern_dma_blank_words": np.asarray(
                [9999, 3359, 1000], np.float64),
            "pattern_dma_active_words": np.asarray(
                [9999, 0, 1678], np.float64),
            "pattern_cpu_blank_words": np.asarray(
                [9999, 1047, 10], np.float64),
            "pattern_cpu_active_edge_words": np.asarray(
                [9999, 1003, 10], np.float64),
            "name_table_dma_blank_words": np.asarray(
                [9999, 1792, 1792], np.float64),
            "name_table_dma_active_words": np.asarray(
                [9999, 0, 0], np.float64),
        }
        gate = {
            "content_fps": 30,
            "limits": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "vblank_spill": 1,
                "prgbuf_jitter_peak_kib": 25,
            },
            "jitter_headroom_kib": 20,
        }
        specs = hudline.row_specs(data, gate, 2)
        keys = [spec.key for spec in specs]
        gate_end = keys.index("prgbuf_jitter_peak_kib")
        self.assertEqual(
            keys[gate_end + 1:gate_end + 8],
            [
                "pattern_dma_blank_words",
                "pattern_dma_active_words",
                "pattern_cpu_blank_words",
                "pattern_cpu_active_edge_words",
                "name_table_dma_blank_words",
                "name_table_dma_active_words",
                "pattern_dma_commands",
            ],
        )
        pattern_scales = {
            spec.maximum
            for spec in specs
            if spec.key in {
                "pattern_dma_blank_words",
                "pattern_dma_active_words",
                "pattern_cpu_blank_words",
                "pattern_cpu_active_edge_words",
            }
        }
        self.assertEqual(pattern_scales, {3359})

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
