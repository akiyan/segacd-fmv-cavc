#!/usr/bin/env python3
"""Compare STL4 and MOSAIC-GM on evenly sampled real master frames."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from time import perf_counter

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from output_dither import BAYER, MODES, quantize_rgb333  # noqa: E402
from palette_algorithms import build_mosaic_palettes, score_palettes  # noqa: E402
from quantize_global4_tiles import build_palettes, tile_blocks  # noqa: E402


def load_tiles(master_dir: Path, count: int, output_dither: str):
    frames = sorted(master_dir.glob("*.png"))
    if not frames:
        raise SystemExit(f"no PNG frames under {master_dir}")
    selected = np.unique(np.linspace(0, len(frames) - 1, min(count, len(frames)), dtype=int))
    return np.concatenate([
        tile_blocks(quantize_rgb333(
            np.asarray(Image.open(frames[index]).convert("RGB")),
            output_dither))
        for index in selected
    ]), len(selected), len(frames)


def compare(
        label: str,
        master_dir: Path,
        frame_count: int,
        output_dither: str,
):
    tiles, sampled, total = load_tiles(
        master_dir, frame_count, output_dither)
    start = perf_counter()
    stl = build_palettes(tiles, n_pal=4)
    stl_s = perf_counter() - start
    stl_score = score_palettes(tiles, stl)

    start = perf_counter()
    mosaic, mosaic_stats = build_mosaic_palettes(tiles, return_stats=True)
    mosaic_s = perf_counter() - start
    mosaic_score = score_palettes(
        tiles, mosaic[:mosaic_stats["active_lines"]],
        core_colors=mosaic_stats["core_colors"],
    )

    print(f"\n{label}: sampled={sampled}/{total} tiles={len(tiles)}")
    print(
        f"  STL4      time={stl_s:.3f}s pixel={stl_score.summary()['pixel_error_per_pixel']:.6f} "
        f"map={stl_score.summary()['mapping_noise_per_pixel']:.6f} "
        f"lines={','.join(f'{value:.3f}' for value in stl_score.line_fraction)}"
    )
    print(
        f"  MOSAIC-GM time={mosaic_s:.3f}s pixel={mosaic_score.summary()['pixel_error_per_pixel']:.6f} "
        f"map={mosaic_score.summary()['mapping_noise_per_pixel']:.6f} "
        f"active={mosaic_stats['active_lines']} core={mosaic_stats['core_colors']} "
        f"lines={','.join(f'{value:.3f}' for value in mosaic_score.line_fraction)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=60)
    parser.add_argument(
        "--output-dither", choices=MODES, default=BAYER)
    parser.add_argument(
        "--case", action="append", nargs=2, metavar=("LABEL", "MASTER_DIR"),
        required=True,
        help="case label and master-frame directory; may be repeated",
    )
    args = parser.parse_args()
    for label, path in args.case:
        compare(label, Path(path), args.frames, args.output_dither)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
