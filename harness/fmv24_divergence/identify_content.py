#!/usr/bin/env python3
"""Identify WHAT a diverged cell actually shows.

For each bad cell at frame N, match its recorded 8x8 content against every
pattern the sim applied in frames N-K..N+K (rendered through the segment
palette), and report whose pattern it really is. Distinguishes placement skew
(content meant for another cell this frame), source-pointer lead (content of a
future frame), and stale/garbage staging.
"""
from __future__ import annotations

import argparse
import pickle
import tempfile
from pathlib import Path

import numpy as np

from scan_divergence import (
    HUD_ROWS_PX, load_capture_index, replay_targets, extract_capture,
    _cell_means,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decisions", type=Path)
    parser.add_argument("hud_tsv", type=Path)
    parser.add_argument("lossless", type=Path)
    parser.add_argument("frame", type=int)
    parser.add_argument("--window", type=int, default=12)
    args = parser.parse_args()

    decisions = pickle.load(args.decisions.open("rb"))
    tcols, trows, cells, _tile = decisions["geom"]
    frame_seg = np.asarray(decisions["frame_seg"])
    seg_pals = np.asarray(decisions["seg_pals"])
    captures = load_capture_index(args.hud_tsv)
    sim = replay_targets(decisions, {args.frame})[args.frame]
    with tempfile.TemporaryDirectory() as tmp:
        rec = extract_capture(
            args.lossless, captures[args.frame], Path(tmp) / "cap.png")
    height, width, _ = sim.shape
    top = (rec.shape[0] - height) // 2
    left = (rec.shape[1] - width) // 2
    rec = rec[top:top + height, left:left + width]
    per_cell = np.abs(
        _cell_means(sim[HUD_ROWS_PX:]).astype(np.float64)
        - _cell_means(rec[HUD_ROWS_PX:]).astype(np.float64)
    ).mean(axis=2)
    hud_rows = HUD_ROWS_PX // 8
    bad = [
        (int(r) + hud_rows, int(c))
        for r, c in np.argwhere(per_cell > 40)
    ]

    seg = int(frame_seg[args.frame])
    full_palette = np.zeros((4, 16, 3), np.uint8)
    full_palette[:, 1:] = seg_pals[seg]

    library = []  # (frame, cell, rgb 8x8x3)
    lo = max(1, args.frame - args.window)
    hi = min(len(decisions["frames"]) - 1, args.frame + args.window)
    for frame in range(lo, hi + 1):
        for cell, palette, key in decisions["frames"][frame]:
            indices = np.frombuffer(key, np.uint8)
            rgb = (full_palette[int(palette)][indices] * 36).reshape(8, 8, 3)
            library.append((frame, int(cell), rgb.astype(np.int16)))

    rec_cells = rec.reshape(height // 8, 8, width // 8, 8, 3)
    print(f"bad cells at frame {args.frame}: {len(bad)} "
          f"(library {len(library)} patterns, frames {lo}..{hi})")
    for row, col in bad:
        cell = row * tcols + col
        content = rec_cells[row, :, col].astype(np.int16)
        scored = sorted(
            (
                (float(np.abs(content - rgb).mean()), frame, src_cell)
                for frame, src_cell, rgb in library
            ),
        )[:3]
        best_err, best_frame, best_cell = scored[0]
        relation = (
            "SELF-LATER" if best_cell == cell and best_frame != args.frame
            else "same-frame-other-cell" if best_frame == args.frame
            else f"frame{best_frame - args.frame:+d}-cell{best_cell}"
        )
        print(
            f"  cell={cell} (r{row},c{col}) best={relation} "
            f"err={best_err:.1f} "
            f"alts={[(f, c, round(e, 1)) for e, f, c in scored[1:]]}")


if __name__ == "__main__":
    main()
