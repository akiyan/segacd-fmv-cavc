#!/usr/bin/env python3
"""Verify OCR for the contiguous movie-player DEBUG HUD."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import gen_debugfont  # noqa: E402
import read_frameno  # noqa: E402


GLYPHS = {format(i, "X"): rows for i, rows in enumerate(gen_debugfont.ORDER[:16])}


def _draw_cell(dst, x, y, rows):
    for dy, row in enumerate(rows):
        for dx, pixel in enumerate(row):
            if pixel == "#":
                dst[y + dy, x + dx] = 235


def make_hud(width, values, origin=(5, 4), complete=True, black_backing=False,
             layout=None):
    height = 32
    yy, xx = np.mgrid[:height, :width]
    # Deliberately bright/noisy movie pixels surround the opaque value cells.
    # Hardware overwrites only the HUD cells in the inactive movie Plane A;
    # the unused H40 width remains the original movie name-table content.
    image = (150 + (7 * xx + 11 * yy) % 91).astype(np.uint8)
    x, y = origin
    if layout is None:
        layout = read_frameno.hud_layout()
    fields = layout if complete else layout[:1]
    if black_backing:
        for _name, logical_col, digits in layout:
            for digit in range(digits):
                col, row = read_frameno.hud_layout_field_position(
                    layout, logical_col + digit
                )
                image[
                    y + row * read_frameno.CELL:
                    y + (row + 1) * read_frameno.CELL,
                    x + col * read_frameno.CELL:
                    x + (col + 1) * read_frameno.CELL,
                ] = 0
    for name, logical_col, digits in fields:
        text = f"{values[name] & ((1 << (digits * 4)) - 1):0{digits}X}"
        for j, char in enumerate(text):
            col, row = read_frameno.hud_layout_field_position(
                layout, logical_col + j
            )
            _draw_cell(
                image,
                x + col * read_frameno.CELL,
                y + row * read_frameno.CELL,
                GLYPHS[char],
            )
    return Image.fromarray(image, "L")


def check_case(width, values, origin, layout=None):
    image = make_hud(width, values, origin, black_backing=True, layout=layout)
    got = read_frameno.read_hud(image, layout=layout)
    expected_values = dict(values)
    transfer = expected_values.pop("vblank_spill_transfer_ticks")
    expected_values["vblank_spill"] = (transfer >> 12) & 0xF
    expected_values["transfer_ticks"] = transfer & 0x0FFF
    pump_gap = expected_values.pop("pump_gap_apply_backpressure")
    expected_values["pump_gap_ticks"] = pump_gap & 0x0FFF
    expected_values["apply_backpressure"] = int(bool(pump_gap & 0x8000))
    reader = expected_values.pop("reader_ahead_slot")
    expected_values["reader_ahead_frames"] = (reader >> 4) & 0xF
    expected_values["reader_slot_sector"] = reader & 0xF
    for name, expected in expected_values.items():
        if got[name][0] != expected:
            raise SystemExit(
                f"{width}px {name}: read {got[name][0]:X}, expected {expected:X}")
        if got[name][1] < 0.90:
            raise SystemExit(f"{width}px {name}: low confidence {got[name][1]:.3f}")
    frame, confidence = read_frameno.read_frameno(image)
    if frame != values["frame"] or confidence < 0.90:
        raise SystemExit(
            f"{width}px F-only API: got {frame:04X}/{confidence:.3f}, "
            f"expected {values['frame']:04X}")


def main():
    if len(gen_debugfont.ORDER) != 16:
        raise SystemExit(f"DEBUG font has {len(gen_debugfont.ORDER)} glyphs, expected 16")
    for value, rows in enumerate(gen_debugfont.ORDER):
        expected = "".join("##" if value & (1 << bit) else ".."
                           for bit in range(3, -1, -1))
        if rows[0] != expected:
            raise SystemExit(f"glyph {value:X} barcode {rows[0]!r}, expected {expected!r}")
    if read_frameno.HUD_CELLS != 43:
        raise SystemExit(
            f"combined HUD has {read_frameno.HUD_CELLS} cells, expected 43"
        )
    if read_frameno.hud_layout_dimensions(
        read_frameno.HUD_LAYOUT
    ) != (40, 2):
        raise SystemExit("combined HUD must occupy 40x2 cells")
    combined_values = {
        "frame": 0x0A99,
        "palette_segment": 0xC,
        "sector_slip": 0x0,
        "control_desync": 0x0,
        "audio_resync": 0x0,
        "audio_lead_256b": 0x38,
        "cd_wait_count": 0x3,
        "sub_wait_scanlines": 0x63,
        "adpcm_decode_units": 0x42,
        "vblank_spill_transfer_ticks": 0xA23D,
        "cold_runs": 0x87,
        "prgbuf_jitter_peak_kib": 0x0E,
        "flip_vcounter": 0xF2,
        "first_share_exit_vcounter": 0x3E,
        "pass2_delay_q4": 0x88,
        "pump_gap_apply_backpressure": 0x8456,
        "msf_gap_recoveries": 0x2,
        "reader_ahead_slot": 0xC3,
        "transfer_vblanks": 0x4,
        "transfer_end_vcounter": 0xE9,
        "pattern_dma_ready_vcounter": 0xD4,
        "name_table_dma_ready_vcounter": 0xEE,
    }
    check_case(
        320, combined_values, (0, 3),
        layout=read_frameno.HUD_LAYOUT,
    )
    if read_frameno.hud_layout_field_position(
        read_frameno.HUD_LAYOUT, 42
    ) != (2, 1):
        raise SystemExit("combined HUD must wrap three cells to row 1")

    native = np.asarray(make_hud(
        320, dict(combined_values, frame=0, palette_segment=0),
        origin=(0, 3), black_backing=True,
        layout=read_frameno.HUD_LAYOUT))
    if np.all(native[11:19, 3 * read_frameno.CELL:] == 0):
        raise SystemExit("HUD row-1 unused width must remain movie-visible")

    # The longstanding single-purpose API must not depend on later HUD fields.
    only_f = make_hud(
        48, dict(combined_values, frame=0xCAFE), origin=(3, 6), complete=False,
        black_backing=True)
    frame, confidence = read_frameno.read_frameno(only_f)
    if frame != 0xCAFE or confidence < 0.90:
        raise SystemExit(
            f"standalone F API: got {frame:04X}/{confidence:.3f}, expected CAFE")

    print("HUD OCR proof: OK (43 values-only cells wrapped 40+3, unused "
          "row-1 width movie-visible, standalone frame compatible)")


if __name__ == "__main__":
    main()
