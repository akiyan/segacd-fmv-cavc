#!/usr/bin/env python3
"""Locate the first movie frame where a DEBUG recording diverges from the sim.

Replays the sim decision log into per-frame display images (same replay as the
analysis preview panels), extracts each sampled movie frame from the lossless
recording via its HUD-TSV capture index, and reports a per-frame cell-mean
error. The HUD text rows are excluded. This measures divergence between the
recording and the sim's own expected display, so encoder approximation (Miss,
Flbk) does not count as divergence.

usage:
  tools/python.sh harness/fmv24_divergence/scan_divergence.py \
    DECISIONS.pkl HUD.tsv LOSSLESS.mkv --frames 16 80 144 ...
  (or --step 64 to sample every 64th frame)
"""
from __future__ import annotations

import argparse
import csv
import pickle
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

HUD_ROWS_PX = 16


def load_capture_index(hud_tsv: Path) -> dict[int, int]:
    table: dict[int, int] = {}
    with hud_tsv.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if int(row["loop"]) != 0:
                continue
            frame = int(row["frame"])
            first = int(row["capture_first"])
            last = int(row["capture_last"])
            table.setdefault(frame, (first + last) // 2)
    return table


def replay_targets(decisions: dict, wanted: set[int]) -> dict[int, np.ndarray]:
    tcols, trows, cells, _tile = decisions["geom"]
    height, width = trows * 8, tcols * 8
    frame_seg = np.asarray(decisions["frame_seg"])
    seg_pals = np.asarray(decisions["seg_pals"])
    display_idx = np.zeros((cells, 64), np.uint8)
    display_pal = np.zeros(cells, np.uint8)
    out: dict[int, np.ndarray] = {}
    for frame, updates in enumerate(decisions["frames"]):
        for cell, palette, key in updates:
            display_idx[int(cell)] = np.frombuffer(key, np.uint8)
            display_pal[int(cell)] = int(palette)
        if frame not in wanted:
            continue
        full_palette = np.zeros((4, 16, 3), np.uint8)
        full_palette[:, 1:] = seg_pals[int(frame_seg[frame])]
        cell_rgb = (
            full_palette[display_pal[:, None], display_idx] * 36
        ).reshape(cells, 8, 8, 3).astype(np.uint8)
        image = (
            cell_rgb.reshape(trows, tcols, 8, 8, 3)
            .transpose(0, 2, 1, 3, 4)
            .reshape(height, width, 3)
        )
        out[frame] = image
    return out


def extract_capture(mkv: Path, index: int, out_png: Path) -> np.ndarray:
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-i", str(mkv),
            "-vf", f"select=eq(n\\,{index})", "-fps_mode", "passthrough",
            "-frames:v", "1", "-y", str(out_png),
        ],
        check=True,
    )
    return np.asarray(Image.open(out_png).convert("RGB"))


def _cell_means(img: np.ndarray) -> np.ndarray:
    h, w, _ = img.shape
    return img.reshape(h // 8, 8, w // 8, 8, 3).mean(axis=(1, 3))


def cell_mean_error(sim: np.ndarray, rec: np.ndarray) -> tuple[float, int]:
    """Return (mean cell error, count of cells with error above 40)."""
    height, width, _ = sim.shape
    if rec.shape[0] < height or rec.shape[1] < width:
        raise SystemExit(
            f"recording raster {rec.shape} smaller than sim {sim.shape}")
    top = (rec.shape[0] - height) // 2
    left = (rec.shape[1] - width) // 2
    rec = rec[top:top + height, left:left + width]
    per_cell = np.abs(
        _cell_means(sim[HUD_ROWS_PX:]).astype(np.float64)
        - _cell_means(rec[HUD_ROWS_PX:]).astype(np.float64)
    ).mean(axis=2)
    return float(per_cell.mean()), int((per_cell > 40).sum())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decisions", type=Path)
    parser.add_argument("hud_tsv", type=Path)
    parser.add_argument("lossless", type=Path)
    parser.add_argument("--frames", type=int, nargs="*", default=None)
    parser.add_argument("--step", type=int, default=64)
    parser.add_argument("--start", type=int, default=8)
    args = parser.parse_args()

    decisions = pickle.load(args.decisions.open("rb"))
    captures = load_capture_index(args.hud_tsv)
    total = len(decisions["frames"])
    frames = (
        sorted(set(args.frames)) if args.frames
        else list(range(args.start, total, args.step))
    )
    frames = [frame for frame in frames if frame in captures and frame > 0]
    # Compare each capture against sim frames N-1..N+1 and keep the best
    # match, so one-frame temporal misalignment does not count as divergence.
    neighbours = {
        neighbour
        for frame in frames
        for neighbour in (frame - 1, frame, frame + 1)
        if 0 < neighbour < total
    }
    sim_frames = replay_targets(decisions, neighbours)
    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "cap.png"
        print("frame\tcapture\tbest_err\tbad_cells\tbest_neighbour")
        for frame in frames:
            rec = extract_capture(args.lossless, captures[frame], png)
            best = None
            for neighbour in (frame - 1, frame, frame + 1):
                if neighbour not in sim_frames:
                    continue
                err, bad = cell_mean_error(sim_frames[neighbour], rec)
                if best is None or err < best[0]:
                    best = (err, bad, neighbour)
            print(
                f"{frame}\t{captures[frame]}\t{best[0]:.2f}\t{best[1]}"
                f"\t{best[2]}",
                flush=True)


if __name__ == "__main__":
    main()
