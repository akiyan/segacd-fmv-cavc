#!/usr/bin/env python3
"""Count every CRAM replacement in a sim decision log.

Palette-segment boundaries and automatic inline fade controls both replace all
64 CRAM words. The initial palette is state 1; every later replacement starts
the next state.
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


def switch_frames(frame_seg, frame_types=None):
    """Return every post-frame-0 CRAM replacement frame exactly once."""

    fseg = np.asarray(frame_seg)
    if fseg.ndim != 1:
        raise ValueError("frame_seg must be one-dimensional")
    if frame_types is None:
        types = np.zeros(len(fseg), np.uint8)
    else:
        types = np.asarray(frame_types)
        if types.shape != fseg.shape:
            raise ValueError("frame types must match frame_seg")
    if not len(fseg):
        return []
    changed = np.zeros(len(fseg), bool)
    changed[1:] = fseg[1:] != fseg[:-1]
    changed |= types != 0
    changed[0] = False
    return np.flatnonzero(changed).astype(int).tolist()


def counts(out_dir):
    """Return (segment count, switch count) for a completed sim output directory."""
    with open(Path(out_dir) / "decisions.pkl", "rb") as handle:
        log = pickle.load(handle)
    fade = log.get("fade") or {}
    switches = len(switch_frames(
        log["frame_seg"], fade.get("frame_types")))
    return switches + 1, switches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sim_out_dir")
    args = parser.parse_args()
    segments, switches = counts(args.sim_out_dir)
    print(f"cram_segments={segments} cram_switches={switches}")


if __name__ == "__main__":
    main()
