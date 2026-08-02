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

    def test_r2v_counts_one_repair_per_dma_run(self):
        components = timeline.calculate_r2v_words(
            np.asarray([0, 3360, 3312]),
            np.asarray([0, 96, 31]),
            np.asarray([0, 75, 19]),
            np.asarray([0, 0, 1]),
        )
        np.testing.assert_array_equal(
            components["repair_words"], [0, 96, 31])
        np.testing.assert_array_equal(
            components["name_table_words"], [1792, 1792, 1792])
        np.testing.assert_array_equal(
            components["cram_words"], [0, 0, 64])
        np.testing.assert_array_equal(
            components["words"], [1792, 5248, 5199])

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
        specs = hudline.row_specs(data, gate, (2,))
        run = next(spec for spec in specs if spec.key == "cold_runs")
        self.assertEqual(run.maximum, 12)

    def test_dma_start_rows_follow_vblank_before_gate_rows(self):
        data = {
            "display_vblanks": np.asarray([np.nan, 2, 2], np.float64),
            "pattern_dma_ready_pressure": np.asarray(
                [0, 0xC8, 0xD4], np.float64),
            "name_table_dma_ready_pressure": np.asarray(
                [np.nan, 0xC4, 0xD6], np.float64),
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
        specs = hudline.row_specs(data, gate, (2,))
        keys = [spec.key for spec in specs]
        self.assertEqual(
            keys[:4],
            [
                "display_vblanks",
                "pattern_dma_ready_pressure",
                "name_table_dma_ready_pressure",
                "sector_slip",
            ],
        )
        by_key = {spec.key: spec for spec in specs}
        self.assertEqual(
            by_key["pattern_dma_ready_pressure"].height,
            hudline.DEFAULT_ROW_HEIGHT * 3,
        )
        self.assertEqual(
            by_key["name_table_dma_ready_pressure"].height,
            hudline.DEFAULT_ROW_HEIGHT * 3,
        )
        self.assertEqual(
            by_key["display_vblanks"].height,
            hudline.DEFAULT_ROW_HEIGHT,
        )
        self.assertTrue(
            by_key["pattern_dma_ready_pressure"].point_plot)
        self.assertTrue(
            by_key["name_table_dma_ready_pressure"].point_plot)
        self.assertEqual(
            by_key["pattern_dma_ready_pressure"].maximum,
            hudline.PATTERN_READY_MISSED_PRESSURE,
        )
        self.assertEqual(
            by_key["pattern_dma_ready_pressure"].deadline_value,
            hudline.PATTERN_READY_DEADLINE_SCANLINE,
        )
        self.assertTrue(
            by_key["pattern_dma_ready_pressure"].show_zero)
        self.assertEqual(
            by_key["name_table_dma_ready_pressure"].maximum,
            hudline.NT_READY_MISSED_PRESSURE,
        )
        self.assertEqual(
            by_key["name_table_dma_ready_pressure"].deadline_value,
            hudline.NT_READY_DEADLINE_SCANLINE,
        )
        self.assertTrue(
            by_key["name_table_dma_ready_pressure"].show_zero)
        point_keys = {
            spec.key for spec in specs if spec.point_plot
        }
        self.assertEqual(
            point_keys,
            {
                "pattern_dma_ready_pressure",
                "name_table_dma_ready_pressure",
            },
        )

    def test_pattern_ready_pressure_starts_at_zero_and_marks_missed_head(self):
        pressure = hudline.derive_pattern_ready_pressure({
            "pattern_dma_ready_vcounter": np.asarray(
                [0xFF, 0x00, 0xC3, 0xDF, 0xE0, 0xE5, 0xE5, 0xFC],
                np.float64,
            ),
            "cold_runs": np.asarray(
                [1, 1, 1, 1, 1, 1, 1, 0],
                np.float64,
            ),
            "pass2_delay_q4": np.asarray(
                [1, 30, 40, 50, 120, 2, 120, 0],
                np.float64,
            ),
        })
        self.assertEqual(float(pressure[0]), 0)
        self.assertEqual(float(pressure[1]), 0)
        self.assertEqual(float(pressure[2]), 0xC3)
        self.assertEqual(float(pressure[3]), 0xDF)
        self.assertEqual(float(pressure[4]), 0xE0)
        self.assertEqual(float(pressure[5]), 0)
        self.assertEqual(
            float(pressure[6]),
            hudline.PATTERN_READY_MISSED_PRESSURE,
        )
        self.assertTrue(np.isnan(pressure[7]))
        summary = hudline.pattern_ready_pressure_summary(pressure)
        self.assertEqual(
            summary["maximum"],
            hudline.PATTERN_READY_MISSED_PRESSURE,
        )
        self.assertEqual(summary["minimum_margin_scanlines"], 0)
        self.assertEqual(summary["missed_frames"], 1)
        self.assertEqual(summary["sample_count"], 6)

    def test_nt_ready_pressure_targets_second_vblank_at_30fps(self):
        pressure = hudline.derive_name_table_ready_pressure({
            "name_table_dma_ready_vcounter": np.asarray(
                [0, 0xD0, 0x00, 0xC3, 0xE5, 0x10, 0xDF, 0xE5, 0xFC],
                np.float64,
            ),
            "transfer_vblanks": np.asarray(
                [0, 0, 1, 1, 1, 2, 2, 2, 2],
                np.float64,
            ),
        }, 30.0)
        np.testing.assert_array_equal(
            pressure,
            [0, 0, 0, 0xC3, 0, 0x100, 0x100, 0xE5, 0xFC],
        )
        summary = hudline.name_table_ready_pressure_summary(
            pressure,
        )
        self.assertEqual(summary["maximum"], 0x100)
        self.assertEqual(summary["minimum_margin_scanlines"], 0)
        self.assertEqual(summary["missed_frames"], 4)
        self.assertEqual(summary["sample_count"], 8)

    def test_nt_ready_pressure_targets_fourth_vblank_at_15fps(self):
        pressure = hudline.derive_name_table_ready_pressure({
            "name_table_dma_ready_vcounter": np.asarray(
                [0, 0xC0, 0xC1, 0xC2, 0xE7], np.float64,
            ),
            "transfer_vblanks": np.asarray(
                [0, 2, 3, 4, 4], np.float64,
            ),
        }, 15.0)
        np.testing.assert_array_equal(
            pressure,
            [0, 0, 0xC1, 0x100, 0xE7],
        )

    def test_nt_ready_pressure_follows_24fps_two_three_phase(self):
        pressure = hudline.derive_name_table_ready_pressure({
            "frame": np.arange(5, dtype=np.int64),
            "name_table_dma_ready_vcounter": np.asarray(
                [0, 0xD0, 0xD1, 0xD2, 0xD3], np.float64,
            ),
            "transfer_vblanks": np.asarray(
                [0, 1, 1, 2, 2], np.float64,
            ),
        }, 24.0)
        np.testing.assert_array_equal(
            pressure,
            [0, 0xD0, 0, 0x100, 0xD3],
        )

    def test_nt_ready_pressure_is_absent_when_dma_path_is_absent(self):
        pressure = hudline.derive_name_table_ready_pressure({
            "name_table_dma_ready_vcounter": np.asarray(
                [0, 0, 0], np.float64,
            ),
            "transfer_vblanks": np.asarray(
                [0, 1, 2], np.float64,
            ),
        }, 30.0)
        self.assertTrue(np.all(np.isnan(pressure)))

    def test_pattern_ready_deadline_and_missed_point_colors_are_distinct(self):
        spec = hudline.RowSpec(
            "pattern_dma_ready_pressure",
            "PATTERN READY PRESSURE",
            "scanlines",
            hudline.PATTERN_READY_MISSED_PRESSURE,
            (98, 184, 224),
            deadline_value=hudline.PATTERN_READY_DEADLINE_SCANLINE,
        )
        self.assertEqual(
            hudline.value_color(0xDF, spec, {}),
            spec.color,
        )
        self.assertEqual(
            hudline.value_color(
                hudline.PATTERN_READY_DEADLINE_SCANLINE,
                spec,
                {},
            ),
            hudline.WARN,
        )
        self.assertEqual(
            hudline.value_color(
                hudline.PATTERN_READY_MISSED_PRESSURE,
                spec,
                {},
            ),
            hudline.FAIL,
        )

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
        specs = hudline.row_specs(data, gate, (2,))
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
