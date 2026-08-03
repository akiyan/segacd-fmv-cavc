#!/usr/bin/env python3
"""Measure expanded edge-dither fringes in matching master and DEBUG captures."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import output_dither  # noqa: E402


TSV_COLUMNS = (
    "frame",
    "fringe_pixels",
    "no_expansion_deviation_pixels",
    "expanded_deviation_pixels",
    "removed_deviation_pixels",
    "no_expansion_toggle_pixels",
    "expanded_toggle_pixels",
    "removed_toggle_pixels",
    "recording_changed_pixels",
    "old_recording_abs_luma_error_sum",
    "new_recording_abs_luma_error_sum",
    "new_recording_closer_pixels",
    "old_recording_closer_pixels",
    "equal_recording_error_pixels",
    "best_improvement",
    "best_x",
    "best_y",
    "old_capture_frame",
    "new_capture_frame",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master_dir", type=Path)
    parser.add_argument("--old-recording", type=Path, required=True)
    parser.add_argument("--old-hud-tsv", type=Path, required=True)
    parser.add_argument("--new-recording", type=Path, required=True)
    parser.add_argument("--new-hud-tsv", type=Path, required=True)
    parser.add_argument("--end-frame", type=int)
    parser.add_argument("--crop-top", type=int, default=16)
    parser.add_argument("--tsv", type=Path, required=True)
    return parser.parse_args()


def load_capture_frames(path: Path) -> list[int]:
    with path.open(encoding="utf-8", newline="") as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    if not rows:
        raise ValueError(f"HUD TSV has no rows: {path}")
    frames = [int(row["frame"]) for row in rows]
    if frames != list(range(len(rows))):
        raise ValueError(f"HUD frame axis is not contiguous: {path}")
    return [
        (int(row["capture_first"]) + int(row["capture_last"])) // 2
        for row in rows
    ]


def probe_geometry(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def read_exact(stream, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            break
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def decoder(path: Path) -> subprocess.Popen:
    return subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def luma(image: np.ndarray) -> np.ndarray:
    rgb = image.astype(np.uint16, copy=False)
    return ((77 * rgb[..., 0] + 150 * rgb[..., 1]
             + 29 * rgb[..., 2] + 128) >> 8).astype(np.int16)


def nearest_rgb333(image: np.ndarray) -> np.ndarray:
    scaled = image.astype(np.float32) * (7.0 / 255.0)
    base = np.floor(scaled)
    return np.clip(
        base + ((scaled - base) > 0.5), 0, 7).astype(np.uint8)


def unexpanded_edge_rgb333(image: np.ndarray) -> np.ndarray:
    """Reproduce edge attenuation before the one-pixel fringe expansion."""
    height, width, _channels = image.shape
    scaled = image.astype(np.float32) * (7.0 / 255.0)
    base = np.floor(scaled)
    amount = output_dither.edge_dither_amount(
        output_dither.local_luma_range(image))
    bayer = output_dither.bayer_thresholds(height, width)
    threshold = 0.5 + (bayer - 0.5) * amount
    return np.clip(
        base + ((scaled - base) > threshold[..., None]), 0, 7
    ).astype(np.uint8)


def analyze_frame(
        frame: int,
        master_path: Path,
        old_capture: np.ndarray,
        new_capture: np.ndarray,
        old_capture_frame: int,
        new_capture_frame: int,
        crop_top: int,
        previous: tuple[np.ndarray, np.ndarray] | None,
) -> tuple[dict[str, int], tuple[np.ndarray, np.ndarray]]:
    master = np.asarray(Image.open(master_path).convert("RGB"), dtype=np.uint8)
    if master.shape != old_capture.shape or master.shape != new_capture.shape:
        raise ValueError(
            f"frame {frame}: master and recording geometry differ")

    local_range = output_dither.local_luma_range(master)
    expanded_range = output_dither.expand_edge_range(local_range)
    fringe = expanded_range > local_range
    no_expansion = unexpanded_edge_rgb333(master)
    expanded = output_dither.edge_attenuated_bayer_rgb333(master)
    nearest = nearest_rgb333(master)
    no_expansion_deviation = fringe & np.any(no_expansion != nearest, axis=2)
    expanded_deviation = fringe & np.any(expanded != nearest, axis=2)
    changed = np.any(no_expansion != expanded, axis=2)

    valid = np.zeros(fringe.shape, dtype=bool)
    valid[crop_top:] = True
    fringe &= valid
    no_expansion_deviation &= valid
    expanded_deviation &= valid
    changed &= valid

    if previous is None:
        no_expansion_toggle = np.zeros_like(valid)
        expanded_toggle = np.zeros_like(valid)
    else:
        previous_no_expansion, previous_expanded = previous
        no_expansion_toggle = no_expansion_deviation ^ previous_no_expansion
        expanded_toggle = expanded_deviation ^ previous_expanded

    target = ((nearest.astype(np.uint16) * 255 + 3) // 7).astype(np.uint8)
    target_luma = luma(target)
    old_error = np.abs(luma(old_capture) - target_luma)
    new_error = np.abs(luma(new_capture) - target_luma)
    changed_old_error = old_error[changed]
    changed_new_error = new_error[changed]
    improvement = old_error.astype(np.int16) - new_error.astype(np.int16)
    if np.any(changed):
        ranked = np.where(changed, improvement, -32768)
        best_flat = int(np.argmax(ranked))
        best_y, best_x = np.unravel_index(best_flat, ranked.shape)
        best_improvement = int(ranked[best_y, best_x])
    else:
        best_x = best_y = -1
        best_improvement = 0

    row = {
        "frame": frame,
        "fringe_pixels": int(np.count_nonzero(fringe)),
        "no_expansion_deviation_pixels": int(
            np.count_nonzero(no_expansion_deviation)),
        "expanded_deviation_pixels": int(
            np.count_nonzero(expanded_deviation)),
        "removed_deviation_pixels": int(np.count_nonzero(
            no_expansion_deviation & ~expanded_deviation)),
        "no_expansion_toggle_pixels": int(
            np.count_nonzero(no_expansion_toggle)),
        "expanded_toggle_pixels": int(np.count_nonzero(expanded_toggle)),
        "removed_toggle_pixels": int(np.count_nonzero(
            no_expansion_toggle & ~expanded_toggle)),
        "recording_changed_pixels": int(np.count_nonzero(changed)),
        "old_recording_abs_luma_error_sum": int(changed_old_error.sum()),
        "new_recording_abs_luma_error_sum": int(changed_new_error.sum()),
        "new_recording_closer_pixels": int(np.count_nonzero(
            changed_new_error < changed_old_error)),
        "old_recording_closer_pixels": int(np.count_nonzero(
            changed_old_error < changed_new_error)),
        "equal_recording_error_pixels": int(np.count_nonzero(
            changed_old_error == changed_new_error)),
        "best_improvement": best_improvement,
        "best_x": int(best_x),
        "best_y": int(best_y),
        "old_capture_frame": old_capture_frame,
        "new_capture_frame": new_capture_frame,
    }
    return row, (no_expansion_deviation, expanded_deviation)


def percent_reduction(before: int, after: int) -> float:
    if before == 0:
        return 0.0
    return 100.0 * (before - after) / before


def main() -> None:
    args = parse_args()
    inputs = (
        args.master_dir,
        args.old_recording,
        args.old_hud_tsv,
        args.new_recording,
        args.new_hud_tsv,
    )
    for path in inputs:
        if not path.exists():
            raise SystemExit(f"input does not exist: {path}")

    master_paths = sorted(args.master_dir.glob("*.png"))
    old_capture_frames = load_capture_frames(args.old_hud_tsv)
    new_capture_frames = load_capture_frames(args.new_hud_tsv)
    frame_count = min(
        len(master_paths), len(old_capture_frames), len(new_capture_frames))
    if args.end_frame is not None:
        if args.end_frame <= 0:
            raise SystemExit("--end-frame must be positive")
        frame_count = min(frame_count, args.end_frame)
    if frame_count == 0:
        raise SystemExit("no matching frames")
    if args.crop_top < 0:
        raise SystemExit("--crop-top must be non-negative")

    old_geometry = probe_geometry(args.old_recording)
    new_geometry = probe_geometry(args.new_recording)
    if old_geometry != new_geometry:
        raise SystemExit(
            f"recording geometry differs: {old_geometry} != {new_geometry}")
    width, height = old_geometry
    if args.crop_top >= height:
        raise SystemExit("--crop-top must leave at least one raster line")
    frame_bytes = width * height * 3

    old_targets = {
        capture: frame
        for frame, capture in enumerate(old_capture_frames[:frame_count])
    }
    new_targets = {
        capture: frame
        for frame, capture in enumerate(new_capture_frames[:frame_count])
    }
    max_capture = max(max(old_targets), max(new_targets))
    old_process = decoder(args.old_recording)
    new_process = decoder(args.new_recording)
    assert old_process.stdout is not None and new_process.stdout is not None
    pending_old: dict[int, np.ndarray] = {}
    pending_new: dict[int, np.ndarray] = {}
    rows: list[dict[str, int]] = []
    previous = None
    next_frame = 0

    try:
        for capture in range(max_capture + 1):
            old_bytes = read_exact(old_process.stdout, frame_bytes)
            new_bytes = read_exact(new_process.stdout, frame_bytes)
            if len(old_bytes) != frame_bytes or len(new_bytes) != frame_bytes:
                raise ValueError(f"recording ended at capture frame {capture}")
            if capture in old_targets:
                pending_old[old_targets[capture]] = np.frombuffer(
                    old_bytes, dtype=np.uint8).reshape(height, width, 3).copy()
            if capture in new_targets:
                pending_new[new_targets[capture]] = np.frombuffer(
                    new_bytes, dtype=np.uint8).reshape(height, width, 3).copy()
            while next_frame in pending_old and next_frame in pending_new:
                row, previous = analyze_frame(
                    next_frame,
                    master_paths[next_frame],
                    pending_old.pop(next_frame),
                    pending_new.pop(next_frame),
                    old_capture_frames[next_frame],
                    new_capture_frames[next_frame],
                    args.crop_top,
                    previous,
                )
                rows.append(row)
                next_frame += 1
    finally:
        for process in (old_process, new_process):
            if process.stdout is not None:
                process.stdout.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    if len(rows) != frame_count:
        raise SystemExit(f"analyzed {len(rows)}/{frame_count} matching frames")
    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output, fieldnames=TSV_COLUMNS, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    totals = {
        column: sum(row[column] for row in rows)
        for column in TSV_COLUMNS
        if column not in {
            "frame", "best_improvement", "best_x", "best_y",
            "old_capture_frame", "new_capture_frame",
        }
    }
    changed = totals["recording_changed_pixels"]
    old_error = totals["old_recording_abs_luma_error_sum"]
    new_error = totals["new_recording_abs_luma_error_sum"]
    print(f"frames={frame_count} crop_top={args.crop_top}")
    print(
        "fringe nearest-rounding deviations: "
        f"no-expansion={totals['no_expansion_deviation_pixels']} "
        f"expanded={totals['expanded_deviation_pixels']} "
        f"reduction={percent_reduction(totals['no_expansion_deviation_pixels'], totals['expanded_deviation_pixels']):.2f}%")
    print(
        "consecutive-frame deviation toggles: "
        f"no-expansion={totals['no_expansion_toggle_pixels']} "
        f"expanded={totals['expanded_toggle_pixels']} "
        f"reduction={percent_reduction(totals['no_expansion_toggle_pixels'], totals['expanded_toggle_pixels']):.2f}%")
    print(
        "recording luma error at corrected fringe pixels: "
        f"old={old_error / max(changed, 1):.3f} "
        f"new={new_error / max(changed, 1):.3f} "
        f"reduction={percent_reduction(old_error, new_error):.2f}% "
        f"pixels={changed}")
    print(
        "recording pixel comparison: "
        f"new-closer={totals['new_recording_closer_pixels']} "
        f"old-closer={totals['old_recording_closer_pixels']} "
        f"equal={totals['equal_recording_error_pixels']}")
    print(args.tsv.resolve())


if __name__ == "__main__":
    main()
