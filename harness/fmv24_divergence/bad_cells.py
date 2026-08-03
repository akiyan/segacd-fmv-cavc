#!/usr/bin/env python3
"""Classify which cells diverge at one frame: freshly updated vs stale.

For frame N, list cells whose recording content differs from the sim display,
and for each, when that cell was last updated (frame and source category from
the per-frame update list). Distinguishes wrong-pattern-payload corruption
(bad cells are recently loaded) from name-table corruption (bad cells were not
recently touched).
"""
from __future__ import annotations

import argparse
import pickle
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image

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
    args = parser.parse_args()

    decisions = pickle.load(args.decisions.open("rb"))
    tcols, trows, cells, _tile = decisions["geom"]
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
    bad = np.argwhere(per_cell > 40)

    last_update = {}
    for frame in range(args.frame + 1):
        for cell, _pal, _key in decisions["frames"][frame]:
            last_update[int(cell)] = frame

    ages = Counter()
    print(f"bad cells at frame {args.frame}: {len(bad)}")
    for row, col in bad:
        cell = (int(row) + hud_rows) * tcols + int(col)
        updated = last_update.get(cell)
        age = args.frame - updated if updated is not None else None
        ages[age if age is None or age < 8 else "8+"] += 1
        print(f"  cell={cell} (r{int(row)+hud_rows},c{int(col)}) "
              f"err={per_cell[row, col]:.0f} last_update=f{updated} age={age}")
    print("age histogram:", dict(sorted(
        ages.items(), key=lambda item: (str(item[0])))))


if __name__ == "__main__":
    main()
