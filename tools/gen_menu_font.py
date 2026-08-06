#!/usr/bin/env python3
"""Convert SGDK's 96-glyph ASCII sheet to Genesis 4bpp menu tiles."""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image


# SGDK's 16x6 sheet has 96 entries: ASCII 0x20 through 0x7F.  The final
# 0x7F tile is harmlessly blank for menu text but keeps the sheet's geometry
# and tile indices exact.
GLYPHS = "".join(chr(value) for value in range(32, 128))


def generate(font_path: Path) -> bytes:
    sheet = Image.open(font_path)
    if sheet.size != (128, 48):
        raise ValueError(
            f"SGDK default font must be 128x48, got {sheet.size} from {font_path}")
    out = bytearray()
    for char in GLYPHS:
        index = ord(char) - 32
        sx = (index % 16) * 8
        sy = (index // 16) * 8
        for y in range(8):
            pixels = [int(bool(sheet.getpixel((sx + x, sy + y))))
                      for x in range(8)]
            for x in range(0, 8, 2):
                out.append((pixels[x] << 4) | pixels[x + 1])
    return bytes(out)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("font", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    data = generate(args.font)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(data)
    print(f"menu font: {args.output} = {len(GLYPHS)} tiles * 32 = {len(data)} bytes")


if __name__ == "__main__":
    main()
