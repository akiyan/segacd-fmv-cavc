#!/usr/bin/env python3
"""Summarize matching SIM/HUD data without encoding or capturing footage."""
import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from tmpfs_workspace import lease_managed_path


def distribution(values):
    return dict(min=int(np.min(values)), mean=float(np.mean(values)),
                median=float(np.median(values)), p95=float(np.percentile(values, 95)),
                max=int(np.max(values)))


def summarize(sim, hud):
    with np.load(sim / "stats.npz") as data:
        if float(data["fps"]) != 30:
            raise ValueError("This cadence comparison requires a 30 fps SIM")
        columns = str(data["cols"]).split()
        stats = data["stats"]
        frames = len(stats)
        result = dict(sim=str(sim.resolve()), frames=frames,
                      cold_cap=int(data["max_cold"]),
                      run_cap=int(data["run_cap"]) if "run_cap" in data else None)
        result["timed_distributions"] = {
            key: distribution(stats[1:, columns.index(key)])
            for key in ("want", "miss", "dma_tiles", "dma_runs")}
        result["cold_cap_frames"] = int(np.count_nonzero(
            stats[1:, columns.index("dma_tiles")] == result["cold_cap"]))
        result["selected_frames"] = {
            str(frame): {key: int(stats[frame, columns.index(key)])
                         for key in ("want", "miss", "dma_tiles", "dma_runs")}
            for frame in (2, 1315, 1377, frames - 1) if frame < frames}
    result["hud"] = str(hud.resolve())
    with hud.open() as source:
        rows = list(csv.DictReader(source, delimiter="\t"))
    result["loops"] = []
    for loop in sorted({int(row["loop"]) for row in rows}):
        observed = {int(row["frame"]): row for row in rows if int(row["loop"]) == loop}
        if not all(frame in observed for frame in range(frames)):
            continue
        intervals = {frame: int(observed[frame + 1]["capture_first"])
                     - int(observed[frame]["capture_first"])
                     for frame in range(1, frames - 1)}
        # This Sonic diagnostic uses 30 fps, fixed two-VBlank cadence.
        changes = []
        previous = None
        anchor = int(observed[1]["capture_first"])
        for frame in range(1, frames):
            lag = int(observed[frame]["capture_first"]) - anchor - 2 * (frame - 1)
            if lag != previous:
                changes.append(dict(frame=frame, lag_vblanks=lag))
                previous = lag
        result["loops"].append(dict(
            loop=loop, interval_histogram=dict(Counter(intervals.values())),
            non_two_vblank_intervals=sum(value != 2 for value in intervals.values()),
            late_new_frames=[frame + 1 for frame, value in intervals.items() if value > 2],
            catchup_new_frames=[frame + 1 for frame, value in intervals.items() if value < 2],
            phase_changes=changes,
            counters={key: max(int(row[key]) for row in observed.values())
                      for key in ("sector_slip", "control_desync", "audio_resync")}))
    if not result["loops"]:
        raise ValueError(f"no complete loop in {hud}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline-sim", "candidate-sim", "baseline-hud", "candidate-hud", "json"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    with ExitStack() as stack:
        for path in (args.baseline_sim, args.candidate_sim):
            lease = lease_managed_path(path)
            if lease:
                stack.callback(lease.release)
        report = dict(baseline=summarize(args.baseline_sim, args.baseline_hud),
                      candidate=summarize(args.candidate_sim, args.candidate_hud))
    if report["baseline"]["frames"] != report["candidate"]["frames"]:
        raise ValueError("baseline and candidate frame counts differ")
    args.json.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
