#!/usr/bin/env python3
"""Regression tests for untimed frame-zero HUDline exclusion."""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


render = load_module(
    "hudline_render",
    ROOT / ".agents/skills/hudline/scripts/render_hudline.py",
)
report = load_module(
    "hudline_report",
    ROOT / ".agents/skills/hudline/scripts/report_overages.py",
)


class HudlineFrameZeroTests(unittest.TestCase):
    def test_c_and_a_statistics_omit_frame_zero(self):
        data = {
            "cd_wait_count": np.asarray([255, 0, 2, 4], np.float64),
            "adpcm_decode_units": np.asarray(
                [254, 60, 64, 64], np.float64),
        }
        rows = [
            {
                "cd_wait_count": str(c_value),
                "adpcm_decode_units": str(a_value),
            }
            for c_value, a_value in zip(
                (255, 0, 2, 4),
                (254, 60, 64, 64),
                strict=True,
            )
        ]
        for implementation, source in (
            (render, data),
            (report, rows),
        ):
            with self.subTest(implementation=implementation.__name__):
                c_stats = implementation.cd_wait_statistics(source)
                self.assertEqual(c_stats["minimum"], 0)
                self.assertEqual(c_stats["mean"], 2.0)
                self.assertEqual(c_stats["median"], 2)
                self.assertEqual(c_stats["maximum"], 4)
                self.assertEqual(c_stats["sample_count"], 3)
                a_stats = implementation.adpcm_decode_statistics(source)
                self.assertEqual(a_stats["minimum"], 60)
                self.assertAlmostEqual(
                    a_stats["mean"], 62.666666666666664)
                self.assertEqual(a_stats["median"], 64)
                self.assertEqual(a_stats["maximum"], 64)
                self.assertEqual(a_stats["sample_count"], 3)

    def test_rendered_vblank_omits_frame_zero_and_terminal_hold(self):
        data = {
            "frame": np.asarray([0, 1, 2, 3], np.int64),
            "capture_first": np.asarray([10, 37, 41, 45], np.float64),
        }
        values, normal = render.derive_display_vblanks(data, 15)
        self.assertEqual(normal, (4,))
        self.assertTrue(math.isnan(float(values[0])))
        self.assertEqual(float(values[1]), 4)
        self.assertEqual(float(values[2]), 4)
        self.assertTrue(math.isnan(float(values[3])))

    def test_reported_vblank_omits_frame_zero_and_terminal_hold(self):
        rows = [
            {"capture_first": str(start)}
            for start in (10, 37, 41, 45)
        ]
        self.assertEqual(
            report.displayed_vblanks(rows),
            [None, 4, 4, None],
        )

    def test_rendered_vblank_edge_holds_are_visible_but_not_alert_eligible(self):
        starts = np.arange(12, dtype=np.int64) * 2
        starts[2:] += 1
        starts[6:] += 1
        starts[11:] += 1
        data = {
            "frame": np.arange(12, dtype=np.int64),
            "capture_first": starts.astype(np.float64),
        }
        values, normal = render.derive_display_vblanks(data, 30)
        eligible, exempt, edge_frames = render.display_vblank_alert_masks(
            data,
            values,
            expected_frames=12,
            content_fps=30,
            cadence_pattern=normal,
        )
        self.assertEqual(edge_frames, 4)
        self.assertEqual(int(np.count_nonzero(eligible)), 4)
        self.assertEqual(
            int(np.count_nonzero(eligible & (values != normal))),
            1,
        )
        self.assertEqual(
            int(np.count_nonzero(exempt & (values != normal))),
            2,
        )

    def test_24fps_render_targets_follow_the_two_three_phase(self):
        starts = [0, 2]
        for frame in range(1, 11):
            starts.append(starts[-1] + (3 if frame & 1 else 2))
        data = {
            "frame": np.arange(12, dtype=np.int64),
            "capture_first": np.asarray(starts, np.float64),
        }
        values, cadence = render.derive_display_vblanks(data, 24)
        targets = render.display_vblank_targets(data, cadence)
        self.assertEqual(cadence, (2, 3))
        np.testing.assert_array_equal(values[1:-1], targets[1:-1])
        eligible, _exempt, edge_frames = render.display_vblank_alert_masks(
            data,
            values,
            expected_frames=12,
            content_fps=24,
            cadence_pattern=cadence,
        )
        self.assertEqual(edge_frames, 3)
        self.assertEqual(int(np.count_nonzero(eligible)), 6)

    def test_report_counts_edge_holds_as_diagnostic_only(self):
        starts = list(range(0, 24, 2))
        for index in range(2, len(starts)):
            starts[index] += 1
        for index in range(11, len(starts)):
            starts[index] += 1
        rows = [
            {
                "frame": str(frame),
                "capture_first": str(start),
                "sector_slip": "0",
                "control_desync": "0",
                "audio_resync": "0",
                "vblank_spill": "0",
                "prgbuf_jitter_peak_kib": "0",
                "cd_wait_count": "0",
                "adpcm_decode_units": "0",
            }
            for frame, start in enumerate(starts)
        ]
        gate = {
            "gate": "PASS",
            "alert": "NONE",
            "content_fps": 30,
            "expected_frames": 12,
            "limits": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "vblank_spill": 1,
                "prgbuf_jitter_peak_kib": 25,
            },
            "maxima": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "vblank_spill": 0,
                "prgbuf_jitter_peak_kib": 0,
                "cd_wait_count": 0,
            },
            "display_vblank_alert_evaluated_frames": 4,
            "display_vblank_edge_exempt_frames": 4,
            "display_vblank_exempted_violation_count": 2,
            "display_vblank_violation_count": 0,
        }
        text = report.render_markdown(rows, list(rows[0]), gate)
        self.assertIn(
            "0.00% / 0 / 4 "
            "(normal phase 0x02; first/last 4 content frames excluded from ALERT; "
            "2 observed edge violation(s)).",
            text,
        )

    def test_report_uses_phase_correct_24fps_targets(self):
        starts = [0, 2]
        for frame in range(1, 11):
            starts.append(starts[-1] + (3 if frame & 1 else 2))
        rows = [
            {
                "frame": str(frame),
                "capture_first": str(start),
                "sector_slip": "0",
                "control_desync": "0",
                "audio_resync": "0",
                "vblank_spill": "0",
                "prgbuf_jitter_peak_kib": "0",
                "cd_wait_count": "0",
                "adpcm_decode_units": "0",
            }
            for frame, start in enumerate(starts)
        ]
        gate = {
            "gate": "PASS",
            "alert": "NONE",
            "content_fps": 24,
            "expected_frames": 12,
            "limits": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "vblank_spill": 2,
                "prgbuf_jitter_peak_kib": 30,
            },
            "maxima": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "vblank_spill": 0,
                "prgbuf_jitter_peak_kib": 0,
                "cd_wait_count": 0,
            },
            "display_vblank_alert_evaluated_frames": 6,
            "display_vblank_edge_exempt_frames": 3,
            "display_vblank_exempted_violation_count": 0,
            "display_vblank_violation_count": 0,
        }
        text = report.render_markdown(rows, list(rows[0]), gate)
        self.assertIn(
            "normal phase 0x02/0x03; first/last 3 content frames",
            text,
        )

    def test_c_never_creates_a_gate_overage_event(self):
        rows = [
            {
                "sector_slip": "0",
                "control_desync": "0",
                "audio_resync": "0",
                "cd_wait_count": str(c_value),
                "vblank_spill": "0",
                "prgbuf_jitter_peak_kib": "0",
            }
            for c_value in (0, 255, 255)
        ]
        gate = {
            "limits": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "vblank_spill": 1,
                "prgbuf_jitter_peak_kib": 25,
            },
            "maxima": {
                "sector_slip": 0,
                "control_desync": 0,
                "audio_resync": 0,
                "cd_wait_count": 255,
                "vblank_spill": 0,
                "prgbuf_jitter_peak_kib": 0,
            },
        }
        self.assertEqual(report.gate_overage_events(rows, gate), {})

    def test_blank_optional_schema_columns_are_not_available_fields(self):
        rows = [
            {
                "pump_gap_ticks": "",
            },
            {
                "pump_gap_ticks": "276",
            },
        ]
        self.assertFalse(
            report.has_values(rows, "missing_field")
        )
        self.assertTrue(report.has_values(rows, "pump_gap_ticks"))

    def test_incomplete_prefix_keeps_the_expected_frame_axis(self):
        image = Image.new("RGBA", (32, 16), (0, 0, 0, 255))
        spec = render.RowSpec(
            "metric",
            "METRIC",
            "units",
            1,
            (255, 255, 255),
            height=10,
        )
        bottom = render.draw_rows(
            image,
            {
                "frame": np.asarray([0, 1, 2], np.int64),
                "metric": np.asarray([0, 1, 1], np.float64),
            },
            [spec],
            {"content_fps": 30, "limits": {}},
            left=5,
            top=0,
            ppf=2,
            axis_frames=5,
        )
        self.assertEqual(bottom, 10)
        self.assertEqual(image.getpixel((14, 5))[:3], render.GRID)
        with self.assertRaisesRegex(
            SystemExit, "shorter than the observed prefix"
        ):
            render.draw_rows(
                image,
                {"frame": np.asarray([0, 1, 2], np.int64)},
                [spec],
                {"content_fps": 30, "limits": {}},
                left=5,
                top=0,
                ppf=2,
                axis_frames=2,
            )

    def test_point_plot_draws_unconnected_points_without_bar_fill(self):
        color = (98, 184, 224)
        image = Image.new("RGBA", (32, 12), (0, 0, 0, 255))
        spec = render.RowSpec(
            "metric",
            "METRIC",
            "units",
            10,
            color,
            height=10,
            point_plot=True,
        )
        render.draw_rows(
            image,
            {
                "frame": np.asarray([0, 1, 2, 3], np.int64),
                "metric": np.asarray([0, 0, 4, 7], np.float64),
            },
            [spec],
            {"content_fps": 30, "limits": {}},
            left=5,
            top=0,
            ppf=2,
            axis_frames=4,
        )
        self.assertEqual(image.getpixel((8, 8))[:3], color)
        self.assertEqual(image.getpixel((10, 5))[:3], color)
        self.assertEqual(image.getpixel((12, 3))[:3], color)
        self.assertNotEqual(image.getpixel((10, 6))[:3], color)
        self.assertNotEqual(image.getpixel((11, 4))[:3], color)


if __name__ == "__main__":
    unittest.main()
