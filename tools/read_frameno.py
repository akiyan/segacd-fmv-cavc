#!/usr/bin/env python3
"""Read descriptive fields from native DEBUG playback HUD recordings.

The standard layout has 43 digits. H32 wraps after 32 digits; H40 wraps after
40 digits. Small cumulative counters use one digit. The four-digit pattern-transfer
word packs ``vblank_spill`` in its high nibble and ``transfer_ticks`` in its
low 12 bits. The pump-gap word packs ``apply_backpressure`` in bit 15 and
``pump_gap_ticks`` in its low 12 bits. The reader byte stores
``reader_ahead_frames`` and ``reader_slot_sector`` as one nibble each.

Player-only frame -1 is displayed as ``frame=FFFF`` before playback. It is an OCR
anchor, not a sim frame or HUD TSV row. Each 8x8 cell's top-row barcode is
decoded directly as four bits; normalized cross-correlation against the small
hex glyph below it supplies confidence. Native origin (0,0) is checked first,
and only displaced captures need a four-digit frame-field scan.

Keep every layout here synchronized with ``prepare_dbg`` in
``boot/movieplay_ip.s``.

Usage:
    from read_frameno import read_frameno, read_hud
    n, conf = read_frameno(pil_img)              # leading frame field only
    hud = read_hud(pil_img)   # {'frame':(v,conf), 'palette_segment':..., ...}
"""
import numpy as np

import gen_debugfont


FRAME_MINUS_ONE = 0xFFFF

_T = {
    value: np.array([[1.0 if c == "#" else 0.0 for c in row]
                     for row in rows])
    for value, rows in enumerate(gen_debugfont.ORDER)
}

# --- HUD layout (must match prepare_dbg in boot/movieplay_ip.s) ---
CELL = 8                 # one HUD cell = 8 px
HUD_ROW = 0              # inactive Plane A movie table's top row
HUD_FIELD_DIGITS = (     # physical value cells; no separators
    ("frame", 4),
    ("palette_segment", 1),
    ("sector_slip", 1),
    ("control_desync", 1),
    ("audio_resync", 1),
    ("audio_lead_256b", 2),
    ("cd_wait_count", 1),
    ("sub_wait_scanlines", 2),
    ("adpcm_decode_units", 2),
    ("vblank_spill_transfer_ticks", 4),
    ("cold_runs", 2),
    ("prgbuf_jitter_peak_kib", 2),
    ("flip_vcounter", 2),
    ("first_share_exit_vcounter", 2),
    ("pass2_delay_q4", 2),
    ("pump_gap_apply_backpressure", 4),
    ("msf_gap_recoveries", 1),
    ("reader_ahead_slot", 2),
    ("transfer_vblanks", 1),
    ("transfer_end_vcounter", 2),
    ("pattern_dma_ready_vcounter", 2),
    ("name_table_dma_ready_vcounter", 2),
)
HUD_COMBINED_FIELD_DIGITS = HUD_FIELD_DIGITS

_PACKED_FIELDS = {
    "vblank_spill_transfer_ticks": (
        ("vblank_spill", lambda value: (value >> 12) & 0xF),
        ("transfer_ticks", lambda value: value & 0x0FFF),
    ),
    "pump_gap_apply_backpressure": (
        ("pump_gap_ticks", lambda value: value & 0x0FFF),
        ("apply_backpressure", lambda value: int(bool(value & 0x8000))),
    ),
    "reader_ahead_slot": (
        ("reader_ahead_frames", lambda value: (value >> 4) & 0xF),
        ("reader_slot_sector", lambda value: value & 0xF),
    ),
}


def _make_layout(field_digits):
    col = 0
    fields = []
    for name, digits in field_digits:
        fields.append((name, col, digits))
        col += digits
    return tuple(fields), col


HUD_H32_COMBINED_LAYOUT, HUD_H32_COMBINED_CELLS = _make_layout(
    HUD_COMBINED_FIELD_DIGITS
)
HUD_H40_COMBINED_LAYOUT, HUD_H40_COMBINED_CELLS = _make_layout(
    HUD_COMBINED_FIELD_DIGITS
)
HUD_LAYOUT = HUD_H32_COMBINED_LAYOUT
HUD_CELLS = HUD_H32_COMBINED_CELLS
HUD_H40_LAYOUT = HUD_H40_COMBINED_LAYOUT
HUD_H40_CELLS = HUD_H40_COMBINED_CELLS
HUD_H32_COMBINED_ROW_CELLS = 32
HUD_H40_COMBINED_ROW_CELLS = 40
H40_NATIVE_WIDTH = 320


def hud_fields_for_layout(layout):
    """Return unpacked descriptive fields in their physical display order."""
    fields = []
    for name, _col, _digits in layout:
        fields.extend(
            unpacked_name for unpacked_name, _decode
            in _PACKED_FIELDS.get(name, ((name, None),))
        )
    return tuple(fields)


HUD_FIELDS = hud_fields_for_layout(HUD_LAYOUT)
HUD_H40_FIELDS = hud_fields_for_layout(HUD_H40_LAYOUT)
HUD_H32_COMBINED_FIELDS = HUD_FIELDS
HUD_H40_COMBINED_FIELDS = HUD_H40_FIELDS


def hud_layout_field_position(layout, logical_col):
    """Return the physical cell column and row for one logical HUD digit."""
    row_cells = None
    if layout is HUD_H32_COMBINED_LAYOUT:
        row_cells = HUD_H32_COMBINED_ROW_CELLS
    elif layout is HUD_H40_COMBINED_LAYOUT:
        row_cells = HUD_H40_COMBINED_ROW_CELLS
    if row_cells is not None:
        return logical_col % row_cells, logical_col // row_cells
    return logical_col, 0


def hud_layout_dimensions(layout):
    """Return the physical width and height of a HUD layout in cells."""
    width = 0
    height = 1
    for _name, logical_col, digits in layout:
        for digit in range(digits):
            col, row = hud_layout_field_position(layout, logical_col + digit)
            width = max(width, col + 1)
            height = max(height, row + 1)
    return width, height


def hud_common_layout_for_width(width):
    """Return the current standard layout from captured frame width."""
    return hud_layout_for_width(width)


def hud_layout_for_width(width):
    """Return the current standard combined layout for a native recording."""
    if width >= H40_NATIVE_WIDTH:
        return HUD_H40_COMBINED_LAYOUT
    return HUD_H32_COMBINED_LAYOUT


def _ncc(a, b):
    a = a - a.mean(); b = b - b.mean()
    d = np.sqrt((a * a).sum() * (b * b).sum())
    return float((a * b).sum() / d) if d > 1e-6 else -1.0


def _read_barcode(cell):
    """Decode the four two-pixel bars in row 0 and return value/confidence."""
    cell = cell.astype(float)
    low = float(np.percentile(cell, 10))
    high = float(np.percentile(cell, 90))
    span = high - low
    if span < 1.0:
        return 0, -1.0
    threshold = (low + high) * 0.5
    groups = cell[0, :8].reshape(4, 2).mean(axis=1)
    value = 0
    for group in groups:
        value = (value << 1) | int(group > threshold)
    margin = float(np.min(np.abs(groups - threshold)) / (span * 0.5))
    return value, min(1.0, margin)


def _read_cell(cell):
    value, barcode_conf = _read_barcode(cell)
    glyph_conf = _ncc(cell.astype(float), _T[value])
    return value, min(barcode_conf, glyph_conf)


def _gray(img):
    if hasattr(img, "convert"):
        return np.asarray(img.convert("L"))
    g = np.asarray(img)
    return g.mean(axis=2) if g.ndim == 3 else g


def _calib_origin(gray, required_width=4 * CELL):
    """先頭4桁のhex glyph列を左上窓で探し、その (x, y) を原点として返す。
    HUD は左上端(col0,row0)。"""
    best, bx, by = -2.0, 0, HUD_ROW * CELL
    h, w = gray.shape[:2]
    max_x = max(0, w - required_width)
    for y in range(0, min(17, h - 7)):
        for x in range(0, min(16, max_x) + 1):
            scores = []
            for digit in range(4):
                cell = gray[y:y + 8, x + digit * CELL:x + (digit + 1) * CELL].astype(float)
                _value, score = _read_cell(cell)
                scores.append(score)
            s = min(scores)
            if s > best:
                best, bx, by = s, x, y
    return bx, by, best


def _read_hex(gray, x0, y, digits=4):
    """(x0, y) から指定桁の16進を読む。x0 は先頭桁の左端。-> (値, 最小NCC)。"""
    val, minsc = 0, 2.0
    for j in range(digits):
        x = x0 + j * CELL
        cell = gray[y:y + 8, x:x + 8].astype(float)
        bv, best = _read_cell(cell)
        val = val * 16 + bv
        minsc = min(minsc, best)
    return val, minsc


def _read_layout_hex(gray, x0, y, layout, logical_col, digits):
    """Read a field whose digits may wrap onto the next physical HUD row."""
    val, minsc = 0, 2.0
    for digit in range(digits):
        col, row = hud_layout_field_position(layout, logical_col + digit)
        x = x0 + col * CELL
        yy = y + row * CELL
        cell = gray[yy:yy + CELL, x:x + CELL].astype(float)
        bv, best = _read_cell(cell)
        val = val * 16 + bv
        minsc = min(minsc, best)
    return val, minsc


def _find_origin(gray, required_width):
    """Use the native (0,0) HUD directly; fall back to the movable-image scan."""
    if gray.shape[0] >= CELL and gray.shape[1] >= required_width:
        _value, score = _read_hex(gray, 0, 0, 4)
        if score >= 0.80:
            return 0, 0, score
    return _calib_origin(gray, required_width)


def read_frameno(img):
    """PIL Image または grayscale ndarray -> (frame_no, confidence)。"""
    gray = _gray(img)
    x0, y, fconf = _find_origin(gray, 4 * CELL)
    val, minsc = _read_hex(gray, x0, y)
    return val, min(fconf, minsc)


def read_hud(img, layout=None):
    """Read the values-only HUD, optionally using an explicit native layout.

    Current native H32/H40 frames default to their 43-cell standard layouts.
    """
    gray = _gray(img)
    if layout is None:
        layout = hud_layout_for_width(gray.shape[1])
    width_cells, height_cells = hud_layout_dimensions(layout)
    x0, y, fconf = _find_origin(gray, width_cells * CELL)
    if y + height_cells * CELL > gray.shape[0]:
        raise ValueError(
            f"HUD image is too short for {height_cells} rows: "
            f"{gray.shape[0]} pixels"
        )
    physical = {}
    for name, logical_col, digits in layout:
        val, minsc = _read_layout_hex(
            gray, x0, y, layout, logical_col, digits
        )
        physical[name] = (val, round(min(fconf, minsc), 3))
    out = {}
    for name, _logical_col, _digits in layout:
        value, confidence = physical[name]
        packed = _PACKED_FIELDS.get(name)
        if packed is None:
            out[name] = (value, confidence)
            continue
        for unpacked_name, decode in packed:
            out[unpacked_name] = (decode(value), confidence)
    return out


if __name__ == "__main__":
    import sys
    from PIL import Image
    for p in sys.argv[1:]:
        image = Image.open(p)
        hud = read_hud(image)
        layout = hud_layout_for_width(image.width)
        fields = hud_fields_for_layout(layout)
        parts = " ".join(
            "%s=%X(%.2f)" % (k, hud[k][0], hud[k][1])
            for k in fields)
        print("%s -> %s" % (p, parts))
