#!/usr/bin/env python3
"""Count CRAM (palette-segment) switches in a sim decision log.

Each palette segment in the sim's decision log (`frame_seg`) is one CRAM swap.
Uploads state how many times the palette switches instead of marking those
points as YouTube chapters (see AGENTS.md "YouTube Upload Style"): both the
analysis and the real-playback description carry the count in the spec section.

The count is a property of the encode itself, so it is identical for the
analysis render and for a playback recording that retains the Mega-CD startup.
No recording timestamp, HUD gate, or startup offset is involved.

Usage:
    python tools/cram_switches.py <sim_out_dir>

Prints one line:
    cram_segments=<N> cram_switches=<N-1>
"""
import argparse
import pickle
from pathlib import Path

import numpy as np


def segment_starts(frame_seg):
    """Return the frame index of every palette-segment start (frame 0 included)."""
    fseg = np.asarray(frame_seg)
    n = len(fseg)
    return [0] + [i for i in range(1, n) if fseg[i] != fseg[i - 1]]


def counts(out_dir):
    """Return (segment count, switch count) for a completed sim output directory."""
    with open(Path(out_dir) / "decisions.pkl", "rb") as handle:
        log = pickle.load(handle)
    segments = len(segment_starts(log["frame_seg"]))
    return segments, max(0, segments - 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sim_out_dir")
    args = parser.parse_args()
    segments, switches = counts(args.sim_out_dir)
    print(f"cram_segments={segments} cram_switches={switches}")


if __name__ == "__main__":
    main()
