#!/usr/bin/env python3
"""Replay only the issue-64 WordBuf planner from frozen sim decisions."""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import pack_stream  # noqa: E402
import pattern_supply  # noqa: E402
import wordbuf_ring  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with args.decisions.open("rb") as source:
        log = pickle.load(source)
    pack_stream.configure_from_log(log)
    (
        per,
        prefetch_per,
        transfer_orders,
        _n_load,
        n_updates,
        _pal_writes,
        patterns,
        _tearing,
    ) = pack_stream.resolve(log, int(log["vram_tiles"]))
    layout = pattern_supply.word_ram_layout(
        len(per), pack_stream.C_CELLS, int(log["max_cold"]))
    current = pattern_supply.plan_supply(
        log,
        per,
        patterns,
        prefetch_per=prefetch_per,
        transfer_orders=transfer_orders,
        wr0_patterns=layout.wr0_patterns,
        wr1_patterns=layout.wr1_patterns,
    )
    plan = wordbuf_ring.plan(
        per=per,
        prefetch_per=prefetch_per,
        transfer_orders=transfer_orders,
        current_plan=current,
        n_updates=n_updates,
        update_lists=np.asarray(log["shadow_updates"]["selected"], bool),
        fps=float(log["fps"]),
        cells=pack_stream.C_CELLS,
        audio_frame_bytes=pack_stream.AUDIO_CONTROL,
        prg_capacity_patterns=int(log["prg_buf_kb"]) * 1024 // 32,
        word_capacities=(layout.wr0_patterns, layout.wr1_patterns),
        baseline_occupancy=np.asarray(
            log["stream_schedule"]["ring_occupancy"], np.int64),
    )
    print(f"feasible\t{int(plan.feasible)}")
    print(f"failure\t{plan.failure}")
    print(
        "boot_patterns\t"
        f"{plan.boot_patterns[0]}\t{plan.boot_patterns[1]}")
    print(
        "boot_end_frames\t"
        f"{plan.boot_end_frames[0]}\t{plan.boot_end_frames[1]}")
    print(
        "selected_refill_patterns\t"
        f"{plan.selected_refill_patterns[0]}\t"
        f"{plan.selected_refill_patterns[1]}")
    print(
        "word_stage_sectors\t"
        f"{int(plan.word_stage_sectors[::2].sum())}\t"
        f"{int(plan.word_stage_sectors[1::2].sum())}")
    staged_frames = np.flatnonzero(plan.word_stage_sectors)
    print(
        "word_stage_frame_range\t"
        + (
            f"{int(staged_frames[0])}\t{int(staged_frames[-1])}"
            if staged_frames.size else "-1\t-1"
        ))
    print(
        "prg_min\t"
        f"{int(plan.prg_occupancy[1:plan.evaluation_end_frame].min())}")
    print(
        "word_min\t"
        f"{int(plan.word_occupancy[1:, 0].min())}\t"
        f"{int(plan.word_occupancy[1:, 1].min())}")
    print(
        "runs\t"
        f"{plan.current_runs}\t{plan.source_merged_runs}\t{plan.model_runs}")


if __name__ == "__main__":
    main()
