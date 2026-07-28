#!/usr/bin/env python3
"""Unit tests for the player-only frame -1 HUD sentinel."""

from __future__ import annotations

import unittest
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gen_debugfont
import read_frameno


class FrameMinusOneTest(unittest.TestCase):
    def test_ffff_glyph_decodes_as_frame_minus_one(self) -> None:
        image = np.zeros((read_frameno.CELL, 4 * read_frameno.CELL), np.uint8)
        glyph = np.array(
            [[255 if cell == "#" else 0 for cell in row]
             for row in gen_debugfont.ORDER[15]],
            np.uint8,
        )
        for digit in range(4):
            start = digit * read_frameno.CELL
            image[:, start:start + read_frameno.CELL] = glyph

        frame, confidence = read_frameno.read_frameno(image)

        self.assertEqual(frame, read_frameno.FRAME_MINUS_ONE)
        self.assertGreaterEqual(confidence, 0.99)

    def test_combined_layout_wraps_at_each_native_width(self) -> None:
        self.assertEqual(read_frameno.HUD_H32_COMBINED_CELLS, 69)
        self.assertEqual(read_frameno.HUD_H40_COMBINED_CELLS, 69)
        self.assertEqual(
            read_frameno.hud_layout_dimensions(
                read_frameno.HUD_H32_COMBINED_LAYOUT
            ),
            (32, 3),
        )
        self.assertEqual(
            read_frameno.hud_layout_dimensions(
                read_frameno.HUD_H40_COMBINED_LAYOUT
            ),
            (40, 2),
        )
        self.assertEqual(
            read_frameno.hud_layout_field_position(
                read_frameno.HUD_H32_COMBINED_LAYOUT, 32
            ),
            (0, 1),
        )
        self.assertEqual(
            read_frameno.hud_layout_field_position(
                read_frameno.HUD_H40_COMBINED_LAYOUT, 40
            ),
            (0, 1),
        )
        y_col = next(
            col for name, col, _digits
            in read_frameno.HUD_H32_COMBINED_LAYOUT
            if name == "Y"
        )
        self.assertEqual(y_col, 54)
        self.assertEqual(
            read_frameno.hud_layout_field_position(
                read_frameno.HUD_H32_COMBINED_LAYOUT, y_col
            ),
            (22, 1),
        )
        self.assertEqual(
            read_frameno.hud_layout_field_position(
                read_frameno.HUD_H40_COMBINED_LAYOUT, y_col
            ),
            (14, 1),
        )

    def test_native_width_selects_current_combined_layout(self) -> None:
        self.assertIs(
            read_frameno.hud_layout_for_width(256),
            read_frameno.HUD_H32_COMBINED_LAYOUT,
        )
        self.assertIs(
            read_frameno.hud_layout_for_width(320),
            read_frameno.HUD_H40_COMBINED_LAYOUT,
        )


if __name__ == "__main__":
    unittest.main()
