#!/usr/bin/env python3
"""Regression tests for mixline section splitting and source preservation."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path



ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mixline = load_module(
    "mixline_render_sections",
    ROOT / ".agents/skills/mixline/scripts/render_mixline.py",
)


def receipt(keys: list[str], heights: dict[str, int] | None = None) -> dict:
    heights = heights or {}
    return {
        "plot_top": 10,
        "rows": [
            {"key": key, "height": heights.get(key, 4)}
            for key in keys
        ],
    }


class MixlineRenderingTests(unittest.TestCase):
    def test_extracts_one_contiguous_logvdpline_block(self):
        keys = [
            "display_vblanks",
            "pattern_dma_ready_pressure",
            "name_table_dma_ready_pressure",
            *mixline.LOGVDPLINE_KEYS,
            "pump_gap_ticks",
        ]
        heights = {
            "pattern_dma_ready_pressure": 12,
            "name_table_dma_ready_pressure": 12,
        }
        log_range, hud_ranges = mixline.split_hudline_ranges(
            receipt(keys, heights),
            image_height=70,
        )
        self.assertEqual(log_range, (38, 66))
        self.assertEqual(hud_ranges, [(10, 38), (66, 70)])

    def test_plain_hudline_remains_one_source_range(self):
        log_range, hud_ranges = mixline.split_hudline_ranges(
            receipt([
                "display_vblanks",
                "pattern_dma_ready_pressure",
                "name_table_dma_ready_pressure",
                "sector_slip",
            ]),
            image_height=30,
        )
        self.assertIsNone(log_range)
        self.assertEqual(hud_ranges, [(10, 30)])

    def test_rejects_a_partial_logvdpline_block(self):
        with self.assertRaisesRegex(SystemExit, "incomplete LOGVDP"):
            mixline.split_hudline_ranges(
                receipt([
                    "display_vblanks",
                    mixline.LOGVDPLINE_KEYS[0],
                ]),
                image_height=30,
            )


if __name__ == "__main__":
    unittest.main()
