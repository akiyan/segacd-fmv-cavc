#!/usr/bin/env python3
"""Report the Main CPU time the in-game player leaves idle, from a VDP trace.

Needs a capture of the diagnostic Main module (make ingame-disc
INGAME_PROFILE=1). At every VBlank hook entry that module writes, to VSRAM
0x40/0x42, the scanlines Main spent in its playback wait loops during the
interval that just ended: first the VBlank lines (after its hook returned),
then the active-display lines. An interval runs from one hook entry to the
next (262 lines: 38 VBlank, 224 active).

The report covers timed playback only: from frame 1's publication to the
last frame's. A movie frame is the interval run from its publication to the
next one (four intervals at 15 fps when on time). Counts are lines seen by a
V-counter poll in the wait loops, accurate to about one line per wait entry.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "harness/blastem"))
from event_stream import iter_events

HOST_REG10 = 0x5F            # boot/ingame_host_ip.s
LOG_ADDRESS = 0x40           # boot/ingame_ip.s, IDLE_PROFILE


def plays(trace, nt):
    """Yield (intervals, publications) per play: intervals[i] = (blank, active)
    idle lines of interval i, publications = interval index of each one."""
    first_entry = nt + 1     # BlastEm logs each VRAM word low byte first
    movie_reg4 = nt >> 13
    host = False
    play = None
    log = bytearray(6)
    for event in iter_events(trace):
        if event.kind == "REGISTER":
            if event.address == 10 and event.data[0] == HOST_REG10:
                host = True
            elif event.address == 4 and host:
                if event.data[0] == movie_reg4 and play is None:
                    play = {"intervals": [], "published": [], "complete": False}
                elif event.data[0] != movie_reg4 and play is not None:
                    play["complete"] = True
                    yield play
                    play = None
            continue
        if play is None:
            continue
        if event.kind == "VSRAM" and LOG_ADDRESS <= event.address < LOG_ADDRESS + 6:
            offset = event.address - LOG_ADDRESS
            log[offset:offset + len(event.data)] = event.data
            if offset + len(event.data) >= 4 and offset < 4:
                # Both words of the ended interval have arrived.
                blank, active = int.from_bytes(log[0:2], "big"), int.from_bytes(log[2:4], "big")
                play["intervals"].append((blank, active))
        elif event.kind == "VRAM" and event.address == first_entry:
            # This publication is first displayed in the interval that the
            # next hook entry closes.
            play["published"].append(len(play["intervals"]))
    if play is not None:
        yield play


def stats(values):
    values = np.asarray(values, dtype=float)
    return {"min": int(values.min()), "p5": round(float(np.percentile(values, 5)), 1),
            "median": round(float(np.median(values)), 1), "mean": round(float(values.mean()), 1),
            "max": int(values.max()), "count": int(values.size)}


def summarize(play, frame_offset):
    intervals = np.asarray(play["intervals"], dtype=int)
    published = play["published"]
    if len(published) < 3:
        raise ValueError("the play has too few publications")
    # Intervals from frame 1's first display to the last frame's.
    start, end = published[1], published[-1]
    timed = intervals[start:end]
    per_frame = []
    for frame, (a, b) in enumerate(zip(published[1:], published[2:]), 1):
        part = intervals[a:b]
        per_frame.append((frame, len(part), int(part[:, 0].sum()), int(part[:, 1].sum())))
    frames = np.asarray([row[1:] for row in per_frame])
    worst = sorted(per_frame, key=lambda row: (row[2] + row[3]) / row[1])[:5]
    order = np.argsort(timed.sum(axis=1), kind="stable")[:5]
    frame_of = np.searchsorted(np.asarray(published), np.arange(start, end), side="right") - 1
    return {
        "complete": play["complete"],
        "frames_published": len(published),
        "per_vblank_interval": {
            "vblank_lines_idle_of_38": stats(timed[:, 0]),
            "active_lines_idle_of_224": stats(timed[:, 1]),
            "total_lines_idle_of_262": stats(timed.sum(axis=1)),
        },
        "per_movie_frame": {
            "intervals": stats(frames[:, 0]),
            "vblank_lines_idle": stats(frames[:, 1]),
            "active_lines_idle": stats(frames[:, 2]),
            "total_lines_idle": stats(frames[:, 1] + frames[:, 2]),
            "total_lines_idle_per_interval": stats((frames[:, 1] + frames[:, 2]) / frames[:, 0]),
        },
        "worst_intervals": [
            {"frame": int(frame_of[i]) + frame_offset, "vblank_idle": int(timed[i, 0]),
             "active_idle": int(timed[i, 1])} for i in order],
        "worst_frames": [
            {"frame": frame + frame_offset, "intervals": n, "vblank_idle": b, "active_idle": a,
             "idle_per_interval": round((a + b) / n, 1)}
            for frame, n, b, a in worst],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", type=Path, help="BlastEm BLSTEL VDP event log")
    parser.add_argument("--nt", type=lambda v: int(v, 0), default=0xC000)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = [summarize(play, 0) for play in plays(args.trace, args.nt)
              if len(play["published"]) >= 3]
    text = json.dumps(report, indent=1)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    raise SystemExit(main())
