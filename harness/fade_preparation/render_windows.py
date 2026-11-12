#!/usr/bin/env python3
"""Render selected windows from completed decisions using the canonical display reader."""

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import resource_tokens
import tmpfs_workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sim", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--range", action="append", required=True, dest="ranges",
                        help="half-open frame interval START:END; repeatable")
    args = parser.parse_args()
    frames = set()
    for interval in args.ranges:
        start, end = map(int, interval.split(":"))
        if start < 0 or end <= start:
            parser.error("each range needs 0 <= START < END")
        frames.update(range(start, end))
    source = args.sim.resolve()
    output = args.output.resolve()
    if source == output or source in output.parents:
        parser.error("write diagnostics outside the completed source artifact")
    lease = tmpfs_workspace.lease_managed_path(source)
    try:
        # Import the production reader in its documented manual-output mode.
        # Only the destination is redirected after its immutable inputs load.
        os.environ.pop("CBRSIM_CONFIG", None)
        os.environ["CBRSIM_OUT"] = str(source)
        sys.argv = [str(Path(__file__))]
        with resource_tokens.acquire_tokens("cpu", count=1):
            import render_analysis as reader
            if max(frames) >= reader.NF:
                raise ValueError("requested window exceeds the completed movie")
            reader.SIM = str(output)
            reader.materialize_analysis_panels(sorted(frames))
            (output / "windows.json").write_text(json.dumps({
                "sim": str(source), "frames": sorted(frames),
                "display_reader": "tools/render_analysis.py:materialize_analysis_panels",
                "total_frames": reader.NF,
            }, indent=2) + "\n", encoding="utf-8")
    finally:
        if lease is not None:
            lease.release()


if __name__ == "__main__":
    main()
