#!/usr/bin/env python3
"""Compare matching rendered windows with source frames, preserving frame alignment."""

import argparse
import csv
from contextlib import ExitStack
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import tmpfs_workspace


def main(resources):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--montage", type=Path, required=True)
    parser.add_argument("--frames", required=True, help="comma-separated montage frames")
    args = parser.parse_args()
    old_manifest = json.loads((args.baseline / "windows.json").read_text())
    new_manifest = json.loads((args.current / "windows.json").read_text())
    lease = tmpfs_workspace.lease_managed_path(Path(new_manifest["sim"]))
    if lease is not None:
        resources.callback(lease.release)
    if old_manifest["frames"] != new_manifest["frames"]:
        raise ValueError("comparison windows differ")
    # FFmpeg's extracted files start at 00001; decisions/previews start at 0.
    # Index the sorted source sequence rather than constructing a filename.
    sources = sorted((Path(new_manifest["sim"]) / "raw").glob("*.png"))
    if len(sources) != new_manifest["total_frames"]:
        raise ValueError("source sequence differs from the completed simulation")
    rows = []
    selected = [int(value) for value in args.frames.split(",")]
    snapshots = {}
    for frame in new_manifest["frames"]:
        images = [Image.open(sources[frame]).convert("RGB")]
        images += [Image.open(path / "preview" / f"{frame:05d}.png").convert("RGB")
                   for path in (args.baseline, args.current)]
        source, old, new = [np.asarray(image, np.int16) for image in images]
        if source.shape != old.shape or source.shape != new.shape:
            raise ValueError(f"raster mismatch at frame {frame}")
        rows.append(dict(frame=frame, source_file=sources[frame].name,
                         baseline_source_mae=float(np.abs(old-source).mean()),
                         current_source_mae=float(np.abs(new-source).mean()),
                         change_mae=float(np.abs(new-old).mean()),
                         source_mean=float(source.mean()),
                         baseline_mean=float(old.mean()), current_mean=float(new.mean())))
        if frame in selected:
            snapshots[frame] = [image.copy() for image in images]
    with args.tsv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, tuple(rows[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    if any(frame not in snapshots for frame in selected):
        raise ValueError("montage frame is outside the rendered windows")
    width, height = snapshots[selected[0]][0].size
    sheet = Image.new("RGB", (width * 3, (height + 28) * len(selected)), "white")
    draw = ImageDraw.Draw(sheet)
    for row, frame in enumerate(selected):
        for column, (label, image) in enumerate(zip(
                ("Source", "Baseline", "Progressive fade"), snapshots[frame], strict=True)):
            x, y = column * width, row * (height + 28)
            draw.text((x + 4, y + 5), f"f{frame}  {label}", fill="black")
            sheet.paste(image, (x, y + 28))
    sheet.save(args.montage)
    summary = dict(frames=len(rows),
                   baseline_source_mae=float(np.mean([r["baseline_source_mae"] for r in rows])),
                   current_source_mae=float(np.mean([r["current_source_mae"] for r in rows])),
                   max_change_frame=max(rows, key=lambda row: row["change_mae"]),
                   baseline_sim=old_manifest["sim"], current_sim=new_manifest["sim"],
                   note="Window MAE is diagnostic, not a perceptual quality verdict.")
    args.tsv.with_suffix(".json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary))


if __name__ == "__main__":
    with ExitStack() as resources:
        main(resources)
