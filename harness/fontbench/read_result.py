#!/usr/bin/env python3
"""OCR the fontbench result screen from a native 256x224 recording or frame.

Decodes the fixed hex rows drawn by boot/fontbench_ip.s using the exact
boot/hexfont.bin glyph bitmaps as templates (binarized 8x8 match), so the
readout is byte-exact rather than approximate. Prints a TSV of field names,
hex values, and derived per-pattern costs.

Usage:
  tools/python.sh harness/fontbench/read_result.py tmp/FONTBENCH/record/fontbench.mkv
  tools/python.sh harness/fontbench/read_result.py frame.png
"""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[2]

# Row layout mirrors boot/fontbench_ip.s (name-table row, label, field).
FIELDS = [
    (2, "0", "MAGIC"),
    (4, "1", "FONT_TICKS"),
    (6, "2", "LUT_TICKS"),
    (8, "3", "COPY_TICKS"),
    (10, "4", "VERIFY_MISMATCH_WORDS"),
    (12, "5", "FIRST_MISMATCH_WORD_INDEX"),
    (14, "6", "FONT_WORD_AT_MISMATCH"),
    (16, "7", "LUT_WORD_AT_MISMATCH"),
    (18, "8", "FONT_OUTPUT_CHECKSUM"),
    (20, "9", "LUT_OUTPUT_CHECKSUM"),
]
VALUE_COL = 4
LABEL_COL = 2

TICK_US = 30.72
PATTERNS_TOTAL = 8 * 2048  # REPS * PATTERNS in boot/fontbench_sp.s
SUB_MHZ = 12.5


def load_templates() -> np.ndarray:
    """boot/hexfont.bin -> (16, 8, 8) boolean glyph bitmaps."""
    raw = (REPO / "boot" / "hexfont.bin").read_bytes()
    if len(raw) != 512:
        raise SystemExit("hexfont.bin is not 512 bytes; run make to regenerate")
    glyphs = np.zeros((16, 8, 8), dtype=bool)
    for g in range(16):
        tile = raw[g * 32:(g + 1) * 32]
        for y in range(8):
            row = tile[y * 4:(y + 1) * 4]
            for x in range(8):
                nib = (row[x // 2] >> (4 if x % 2 == 0 else 0)) & 0xF
                glyphs[g, y, x] = nib != 0
    return glyphs


def last_frame(path: Path) -> np.ndarray:
    """Return the final video frame (or the image itself) as an RGB array."""
    if path.suffix.lower() in (".png", ".bmp", ".jpg", ".jpeg"):
        return np.asarray(Image.open(path).convert("RGB"))
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True)
    # The video stream can end well before the container duration (audio runs
    # longer), so seek conservatively and let the last decoded frame win.
    start = max(0.0, float(probe.stdout.strip()) - 10.0)
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "frame.png"
        # Decode the tail and overwrite the same image so the final frame wins
        # (-sseof can land past the last video packet on FFV1/MKV).
        subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{start:.2f}", "-i", str(path),
             "-update", "1", "-y", str(out)],
            check=True)
        return np.asarray(Image.open(out).convert("RGB"))


def read_glyph(frame: np.ndarray, row: int, col: int,
               templates: np.ndarray) -> int:
    cell = frame[row * 8:(row + 1) * 8, col * 8:(col + 1) * 8]
    if cell.shape[:2] != (8, 8):
        raise SystemExit(f"cell ({row},{col}) out of frame {frame.shape}")
    # Glyph pixels are colour 1 = white 0xEEE on a coloured backdrop.
    on = cell.min(axis=2) > 140
    scores = [(int(np.sum(on == t)), g) for g, t in enumerate(templates)]
    score, glyph = max(scores)
    if score < 60:  # allow tiny edge noise only; 64 = exact
        raise SystemExit(
            f"cell ({row},{col}) does not match any hex glyph "
            f"(best {glyph:X} with {score}/64)")
    return glyph


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input", type=Path, help="native 256x224 MKV or frame image")
    args = ap.parse_args()

    frame = last_frame(args.input)
    if frame.shape[0] < 224 or frame.shape[1] < 256:
        raise SystemExit(f"expected a native >=256x224 frame, got {frame.shape}")
    templates = load_templates()

    values = {}
    print("field\thex\tdecimal")
    for row, label, name in FIELDS:
        got_label = read_glyph(frame, row, LABEL_COL, templates)
        if got_label != int(label, 16):
            raise SystemExit(f"row {row}: label {got_label:X}, expected {label}")
        v = 0
        for i in range(4):
            v = (v << 4) | read_glyph(frame, row, VALUE_COL + i, templates)
        values[name] = v
        print(f"{name}\t{v:04X}\t{v}")

    if values["MAGIC"] != 0xFB01:
        raise SystemExit("MAGIC mismatch: not a fontbench result screen")
    print()
    print("variant\tticks\ttotal_ms\tus_per_pattern\tcycles_per_pattern")
    for name in ("FONT_TICKS", "LUT_TICKS", "COPY_TICKS"):
        t = values[name]
        us = t * TICK_US / PATTERNS_TOTAL
        print(f"{name.removesuffix('_TICKS')}\t{t}\t"
              f"{t * TICK_US / 1000:.1f}\t{us:.2f}\t{us * SUB_MHZ:.0f}")
    ok = (values["VERIFY_MISMATCH_WORDS"] == 0
          and values["FIRST_MISMATCH_WORD_INDEX"] == 0xFFFF
          and values["FONT_OUTPUT_CHECKSUM"] == values["LUT_OUTPUT_CHECKSUM"])
    print()
    print(f"verify\t{'PASS' if ok else 'FAIL'}")
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
