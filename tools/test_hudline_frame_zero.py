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
        self.assertEqual(normal, 4)
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


if __name__ == "__main__":
    unittest.main()
