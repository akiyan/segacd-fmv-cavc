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
        self.assertEqual(read_frameno.HUD_H32_COMBINED_CELLS, 39)
        self.assertEqual(read_frameno.HUD_H40_COMBINED_CELLS, 39)
        self.assertEqual(
            read_frameno.hud_layout_dimensions(
                read_frameno.HUD_H32_COMBINED_LAYOUT
            ),
            (32, 2),
        )
        self.assertEqual(
            read_frameno.hud_layout_dimensions(
                read_frameno.HUD_H40_COMBINED_LAYOUT
            ),
            (39, 1),
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
        transfer_vblank_col = next(
            col for name, col, _digits
            in read_frameno.HUD_H32_COMBINED_LAYOUT
            if name == "transfer_vblanks"
        )
        self.assertEqual(transfer_vblank_col, 36)
        self.assertEqual(
            read_frameno.hud_layout_field_position(
                read_frameno.HUD_H32_COMBINED_LAYOUT,
                transfer_vblank_col,
            ),
            (4, 1),
        )
        self.assertEqual(
            read_frameno.hud_layout_field_position(
                read_frameno.HUD_H40_COMBINED_LAYOUT,
                transfer_vblank_col,
            ),
            (36, 0),
        )

    def test_standard_layout_uses_descriptive_unpacked_fields(self) -> None:
        self.assertIn("vblank_spill", read_frameno.HUD_FIELDS)
        self.assertIn("transfer_ticks", read_frameno.HUD_FIELDS)
        self.assertIn("apply_backpressure", read_frameno.HUD_FIELDS)
        self.assertIn("reader_ahead_frames", read_frameno.HUD_FIELDS)
        self.assertNotIn(
            "vblank_spill_transfer_ticks", read_frameno.HUD_FIELDS)

    def test_packed_cells_are_unpacked_losslessly(self) -> None:
        layout = read_frameno.HUD_H40_COMBINED_LAYOUT
        width, height = read_frameno.hud_layout_dimensions(layout)
        image = np.zeros(
            (height * read_frameno.CELL, width * read_frameno.CELL),
            np.uint8,
        )
        physical_values = {
            name: 0 for name, _col, _digits in layout
        }
        physical_values.update({
            "frame": 1,
            "vblank_spill_transfer_ticks": 0xA345,
            "pump_gap_apply_backpressure": 0x807B,
            "reader_ahead_slot": 0xC5,
        })
        for name, logical_col, digits in layout:
            value = physical_values[name]
            for digit in range(digits):
                shift = (digits - digit - 1) * 4
                nibble = (value >> shift) & 0xF
                glyph = np.array(
                    [
                        [255 if cell == "#" else 0 for cell in row]
                        for row in gen_debugfont.ORDER[nibble]
                    ],
                    np.uint8,
                )
                col, row = read_frameno.hud_layout_field_position(
                    layout, logical_col + digit)
                image[
                    row * read_frameno.CELL:(row + 1) * read_frameno.CELL,
                    col * read_frameno.CELL:(col + 1) * read_frameno.CELL,
                ] = glyph

        hud = read_frameno.read_hud(image, layout=layout)

        self.assertEqual(hud["vblank_spill"][0], 0xA)
        self.assertEqual(hud["transfer_ticks"][0], 0x345)
        self.assertEqual(hud["pump_gap_ticks"][0], 0x07B)
        self.assertEqual(hud["apply_backpressure"][0], 1)
        self.assertEqual(hud["reader_ahead_frames"][0], 0xC)
        self.assertEqual(hud["reader_slot_sector"][0], 0x5)

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
