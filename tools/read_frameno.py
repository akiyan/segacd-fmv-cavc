#!/usr/bin/env python3
"""実機/エミュ録画のデバッグHUD（左上端、H32/H40とも最大2行）から各値を読む。

HUD はカテゴリ文字を描かず、boot/movieplay_ip.s の固定順で値だけを描く:
    H32/H40: xxxx xx xx xx xx xx xx xx xx xx xxxx xx xx
内部キー順は F/P/S/D/R/L/C/W/M/A/U/N/J。F は16進4桁、L は
音声リードの上位byte（256B単位）、P/S/D/R/C/W/M/A/N はlow byteの
16進2桁、U は16進4桁。U はMain pattern転送時間（Mega-CD stopwatchの
30.72 us tick）、N はcold-run数の下位byte、J はfps由来の通常PrgBuf上限を超えた
streamed PrgBuf占有量の再生中最大値（1 KiB単位、端数切り上げ）。
標準H32/H40 DEBUGは Q/V/O/E を追加する。Q はそのframe中の符号付き論理PrgBuf
最小残量を32-byte pattern単位で示す4桁値。0000は真のempty、FFFFは1 pattern不足。
さらにG/K/H/Xを追加し、同じ54桁の論理列をH32は32 cell、H40は40 cellで折り返す。
Gはframe内でSub CDC pump外にいた最大時間を30.72 us stopwatch tick単位で示し、
KはMSF連番gapから再seekした累積回数を示す。Gのbit 15はAPPLY back-pressureが
control sector pumpを拒否したframeを示すB markerである。Hはframe内の物理PrgBuf
最大占有量を32-byte pattern単位で示す。Xは上位byteに完了済みframe slotの先行数、
下位byteに現在slot内のsector位置を格納する。
再生開始前のplayer-only frame -1はF=FFFFで表す。これはOCR頭出し用の
センチネルであり、sim frameでもHUD TSV rowでもない。
各8x8セルの上段バーコードを直接4-bitとして読み、下段の小型hex字形とのNCCで
信頼度を確認する。ネイティブ録画の原点(0,0)は即時判定し、位置がずれた画像だけ
先頭4桁で原点を探索する。

このモジュールの各HUD layoutは boot/movieplay_ip.s のprepare_dbgと一致させること
（HUDレイアウトを変えたら両方直す）。

使い方:
    from read_frameno import read_frameno, read_hud
    n, conf = read_frameno(pil_img)              # 先頭4桁のフレーム番号のみ
    hud = read_hud(pil_img)                       # {'F':(v,conf), 'P':..., 'L':...}
"""
import numpy as np

import gen_debugfont


FRAME_MINUS_ONE = 0xFFFF

_T = {
    value: np.array([[1.0 if c == "#" else 0.0 for c in row]
                     for row in rows])
    for value, rows in enumerate(gen_debugfont.ORDER)
}

# --- HUDレイアウト(boot/movieplay_ip.s の prepare_dbg と一致させる) ---
CELL = 8                 # 1 HUDセル = 8px
HUD_ROW = 0              # inactive Plane A movie table's top row
HUD_FIELD_DIGITS = (     # 値のみ。field間の空けはない
    ("F", 4),
    ("P", 2),
    ("S", 2),
    ("D", 2),
    ("R", 2),
    ("L", 2),
    ("C", 2),
    ("W", 2),
    ("M", 2),
    ("A", 2),
    ("U", 4),
    ("N", 2),
    ("J", 2),
)
HUD_H40_FIELD_DIGITS = HUD_FIELD_DIGITS
# H40 DEBUG builds with HUD_FLIP_FIELDS append one exact signed PrgBuf
# diagnostic, then three flip-phase fields:
# Q = per-frame minimum logical PrgBuf balance in 32-byte patterns. It is a
#     four-digit signed 16-bit value (0000 empty, FFFF one-pattern underflow).
# V = V-counter at the previous accepted flip, O = that flip's interval
# excess over 1024 stopwatch ticks (nominal N2 interval ~1086; clamped FF),
# E = this frame's Pass2 entry delay since the previous flip in 4-tick
# units (clamped FF).
HUD_H40_FLIP_FIELD_DIGITS = HUD_FIELD_DIGITS + (
    ("Q", 4),
    ("V", 2),
    ("O", 2),
    ("E", 2),
)
HUD_H40_POLL_GAP_FIELD_DIGITS = HUD_FIELD_DIGITS + (
    ("G", 4),
    ("K", 2),
    ("O", 2),
    ("E", 2),
)
HUD_COMBINED_FIELD_DIGITS = HUD_H40_FLIP_FIELD_DIGITS + (
    ("G", 4),
    ("K", 2),
    ("H", 4),
    ("X", 4),
)


def _make_layout(field_digits):
    col = 0
    fields = []
    for name, digits in field_digits:
        fields.append((name, col, digits))
        col += digits
    return tuple(fields), col


HUD_LAYOUT, HUD_CELLS = _make_layout(HUD_FIELD_DIGITS)
HUD_FIELDS = tuple(name for name, _col, _digits in HUD_LAYOUT)
HUD_H40_LAYOUT, HUD_H40_CELLS = _make_layout(HUD_H40_FIELD_DIGITS)
HUD_H40_FIELDS = tuple(name for name, _col, _digits in HUD_H40_LAYOUT)
HUD_H40_FLIP_LAYOUT, HUD_H40_FLIP_CELLS = _make_layout(HUD_H40_FLIP_FIELD_DIGITS)
HUD_H40_FLIP_FIELDS = tuple(name for name, _col, _digits in HUD_H40_FLIP_LAYOUT)
HUD_H40_POLL_GAP_LAYOUT, HUD_H40_POLL_GAP_CELLS = _make_layout(
    HUD_H40_POLL_GAP_FIELD_DIGITS
)
HUD_H40_POLL_GAP_FIELDS = tuple(
    name for name, _col, _digits in HUD_H40_POLL_GAP_LAYOUT
)
HUD_H32_COMBINED_LAYOUT, HUD_H32_COMBINED_CELLS = _make_layout(
    HUD_COMBINED_FIELD_DIGITS
)
HUD_H32_COMBINED_FIELDS = tuple(
    name for name, _col, _digits in HUD_H32_COMBINED_LAYOUT
)
HUD_H40_COMBINED_LAYOUT, HUD_H40_COMBINED_CELLS = _make_layout(
    HUD_COMBINED_FIELD_DIGITS
)
HUD_H40_COMBINED_FIELDS = tuple(
    name for name, _col, _digits in HUD_H40_COMBINED_LAYOUT
)
HUD_H32_COMBINED_ROW_CELLS = 32
HUD_H40_COMBINED_ROW_CELLS = 40
H40_NATIVE_WIDTH = 320


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
    """Return the legacy common H32/H40 layout from captured frame width.

    H32 and H40 deliberately use the same 30-cell layout. Separate layout
    objects remain for callers that retain native-mode metadata.
    """
    return HUD_H40_LAYOUT if width >= H40_NATIVE_WIDTH else HUD_LAYOUT


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
    """PIL Image または grayscale ndarray -> (frame_no, confidence)。F(先頭値)のみ。"""
    gray = _gray(img)
    x0, y, fconf = _find_origin(gray, 4 * CELL)
    val, minsc = _read_hex(gray, x0, y)
    return val, min(fconf, minsc)


def read_hud(img, layout=None):
    """Read the values-only HUD, optionally using an explicit native layout.

    Current native H32/H40 frames default to their 54-cell combined layouts.
    Pass an explicit legacy layout when reading an older recording.
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
    out = {}
    for name, logical_col, digits in layout:
        val, minsc = _read_layout_hex(
            gray, x0, y, layout, logical_col, digits
        )
        out[name] = (val, round(min(fconf, minsc), 3))
    return out


if __name__ == "__main__":
    import sys
    from PIL import Image
    for p in sys.argv[1:]:
        image = Image.open(p)
        hud = read_hud(image)
        layout = hud_layout_for_width(image.width)
        fields = tuple(name for name, _col, _digits in layout)
        widths = {name: digits for name, _col, digits in layout}
        parts = " ".join(
            "%s=%0*X(%.2f)" % (k, widths[k], hud[k][0], hud[k][1])
            for k in fields)
        print("%s -> %s" % (p, parts))
