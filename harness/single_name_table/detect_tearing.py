#!/usr/bin/env python3
"""Detect within-frame raster changes in a lossless DEBUG recording."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class HudSpan:
    frame: int
    first: int
    last: int


OUTPUT_COLUMNS = (
    "frame",
    "capture_first",
    "capture_last",
    "sample_count",
    "unique_rasters",
    "outlier_samples",
    "max_changed_pixels",
    "status",
)


def load_spans(path: Path) -> list[HudSpan]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        required = {"loop", "frame", "capture_first", "capture_last"}
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"HUD TSV lacks columns: {sorted(missing)}")
        spans = [
            HudSpan(
                int(row["frame"]),
                int(row["capture_first"]),
                int(row["capture_last"]),
            )
            for row in reader
            if int(row["loop"]) == 0
        ]
    if not spans:
        raise ValueError("HUD TSV has no first-loop movie frames")
    for index, span in enumerate(spans):
        if span.first < 0 or span.last < span.first:
            raise ValueError(f"frame {span.frame}: invalid capture span")
        if index and span.first <= spans[index - 1].last:
            raise ValueError("HUD capture spans overlap or are out of order")
    return spans


def video_geometry(path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    streams = json.loads(result.stdout).get("streams", [])
    if len(streams) != 1:
        raise ValueError("recording must have exactly one selected video stream")
    return int(streams[0]["width"]), int(streams[0]["height"])


def read_exact(stream, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            break
        chunks.extend(chunk)
    return bytes(chunks)


def inspect(
    video: Path, spans: list[HudSpan], *, skip_top_rows: int,
) -> list[dict[str, int | str]]:
    width, height = video_geometry(video)
    if not 0 <= skip_top_rows < height:
        raise ValueError(
            f"--skip-top-rows must be between 0 and {height - 1}")
    frame_bytes = width * height * 3
    crop_offset = width * skip_top_rows * 3
    final_capture = spans[-1].last
    process = subprocess.Popen(
        [
            "ffmpeg", "-v", "error", "-i", str(video), "-map", "0:v:0",
            "-fps_mode", "passthrough", "-frames:v", str(final_capture + 1),
            "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
        ],
        stdout=subprocess.PIPE,
    )
    assert process.stdout is not None
    by_first = {span.first: span for span in spans}
    active: HudSpan | None = None
    samples: list[bytes] = []
    rows: list[dict[str, int | str]] = []
    capture = 0

    def finish(span: HudSpan, rasters: list[bytes]) -> None:
        hashes = [hashlib.blake2b(raster, digest_size=16).digest()
                  for raster in rasters]
        counts = Counter(hashes)
        reference_hash, reference_count = counts.most_common(1)[0]
        reference = rasters[hashes.index(reference_hash)]
        reference_array = np.frombuffer(reference, dtype=np.uint8).reshape(-1, 3)
        max_changed = 0
        for raster, digest in zip(rasters, hashes):
            if digest == reference_hash:
                continue
            array = np.frombuffer(raster, dtype=np.uint8).reshape(-1, 3)
            max_changed = max(
                max_changed,
                int(np.count_nonzero(np.any(array != reference_array, axis=1))),
            )
        unique = len(counts)
        rows.append({
            "frame": span.frame,
            "capture_first": span.first,
            "capture_last": span.last,
            "sample_count": len(rasters),
            "unique_rasters": unique,
            "outlier_samples": len(rasters) - reference_count,
            "max_changed_pixels": max_changed,
            "status": "PASS" if unique == 1 else "TEAR",
        })

    try:
        while capture <= final_capture:
            raw = read_exact(process.stdout, frame_bytes)
            if len(raw) != frame_bytes:
                raise ValueError(
                    f"recording ended at capture {capture}, "
                    f"before HUD capture {final_capture}")
            if capture in by_first:
                active = by_first[capture]
                samples = []
            if active is not None:
                samples.append(raw[crop_offset:])
                if capture == active.last:
                    finish(active, samples)
                    active = None
                    samples = []
            capture += 1
    finally:
        process.stdout.close()
        return_code = process.wait()
    if return_code:
        raise ValueError(f"ffmpeg decoder exited with status {return_code}")
    return rows


def write_tsv(path: Path, rows: list[dict[str, int | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=OUTPUT_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("hud_tsv", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--skip-top-rows", type=int, default=16,
        help="exclude the two DEBUG HUD rows from raster comparison",
    )
    args = parser.parse_args()
    if args.hud_tsv.suffix != ".tsv" or args.output.suffix != ".tsv":
        parser.error("HUD input and detector output must use .tsv")
    if not args.video.is_file() or not args.hud_tsv.is_file():
        parser.error("video and HUD TSV must exist")
    try:
        spans = load_spans(args.hud_tsv)
        rows = inspect(
            args.video, spans, skip_top_rows=args.skip_top_rows)
    except (OSError, subprocess.CalledProcessError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc
    write_tsv(args.output, rows)
    tears = [row for row in rows if row["status"] != "PASS"]
    print(
        f"tearing detector: {len(rows)} movie frames, "
        f"{len(tears)} inconsistent raster groups")
    print(args.output.resolve())
    if tears:
        examples = ", ".join(str(row["frame"]) for row in tears[:12])
        raise SystemExit(f"tearing detected at movie frame(s): {examples}")


if __name__ == "__main__":
    main()
