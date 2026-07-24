#!/usr/bin/env python3
"""Regression tests for untimed frame-zero HUDline exclusion."""

from __future__ import annotations

import importlib.util
import math
import sys
import unittest
from pathlib import Path

import numpy as np


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


if __name__ == "__main__":
    unittest.main()
