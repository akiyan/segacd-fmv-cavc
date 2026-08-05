#!/usr/bin/env python3
"""Run the automatic scroll detector over an extracted frame directory."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

import scroll_frames


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("frames", type=Path, help="ordered PNG frame directory")
    parser.add_argument("--first-frame", type=int, default=0)
    parser.add_argument("--backend", choices=("auto", "cpu", "gpu"), default="auto")
    parser.add_argument("--tsv", type=Path, required=True)
    args = parser.parse_args()

    paths = sorted(args.frames.glob("*.png"))
    if len(paths) < 2:
        raise SystemExit(f"need at least two PNG frames in {args.frames}")
    rows, segments = scroll_frames.detect_segments(
        paths, first_frame=args.first_frame, backend=args.backend)
    accepted = {
        frame
        for segment in segments
        for frame in range(segment.start, segment.end + 1)
    }
    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(
            "frame\taxis\tdelta\tsupport\tresidual\tzero_residual\tgain\t"
            "runner_up_margin\tvalid_blocks\tpair_accepted\tsegment_accepted\tcut\n")
        for row in rows:
            handle.write(
                f"{row.frame}\t{row.axis}\t{row.delta}\t{row.support:.6f}\t"
                f"{row.residual:.6f}\t{row.zero_residual:.6f}\t{row.gain:.6f}\t"
                f"{row.runner_up_margin:.6f}\t{row.valid_blocks}\t"
                f"{int(row.accepted)}\t{int(row.frame in accepted)}\t{int(row.cut)}\n")
    for segment in segments:
        print(
            f"segment frames={segment.start}..{segment.end} axis={segment.axis} "
            f"displacement={segment.displacement} support={segment.support:.3f} "
            f"gain={segment.gain:.2f} multiframe={segment.multiframe_support:.3f}")
    print(f"wrote {args.tsv}")


if __name__ == "__main__":
    main()
