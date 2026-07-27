#!/usr/bin/env python3
"""Measure the issue-64 gate from frozen simulation decision logs."""

from __future__ import annotations

import argparse
import csv
import pickle
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import pack_stream  # noqa: E402
import pattern_supply  # noqa: E402


PATTERN_BYTES = 32


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case",
        action="append",
        nargs=2,
        metavar=("LABEL", "DECISIONS"),
        required=True,
        help="label and decisions.pkl path; repeat for multiple cases",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".tsv":
        parser.error("--output must use the .tsv extension")
    return args


def percentile(values: np.ndarray, quantile: float) -> int:
    if not values.size:
        return 0
    return int(np.quantile(values, quantile, method="nearest"))


def source_boundary_run_cost(log: dict) -> tuple[int, int, int, int]:
    """Return actual and merged-source runs after an independent replay."""

    pack_stream.configure_from_log(log)
    (
        per,
        prefetch_per,
        transfer_orders,
        _n_load,
        _n_upd,
        _pal_w,
        patterns,
        _tearing,
    ) = pack_stream.resolve(log, int(log["vram_tiles"]))
    layout = pattern_supply.word_ram_layout(
        len(per),
        pack_stream.C_CELLS,
        int(log["max_cold"]),
    )
    plan = pattern_supply.plan_supply(
        log,
        per,
        patterns,
        prefetch_per=prefetch_per,
        transfer_orders=transfer_orders,
        wr0_patterns=layout.wr0_patterns,
        wr1_patterns=layout.wr1_patterns,
    )

    actual_total = 0
    merged_total = 0
    affected_frames = 0
    maximum_extra = 0
    for (
        (_cells, entries, colds),
        sources,
        prefetch,
        dic_indices,
        transfer_order,
    ) in zip(
        per,
        plan.sources,
        prefetch_per,
        plan.dic_indices,
        transfer_orders,
        strict=True,
    ):
        actual = len(pack_stream.sourced_transfer_runs(
            entries,
            colds,
            sources,
            prefetch,
            dic_indices,
            transfer_order,
        ))
        merged_sources = tuple(
            pattern_supply.SOURCE_PRG
            if source == pattern_supply.SOURCE_WR
            else source
            for source in sources
        )
        merged = len(pack_stream.sourced_transfer_runs(
            entries,
            colds,
            merged_sources,
            prefetch,
            dic_indices,
            transfer_order,
        ))
        if actual < merged:
            raise AssertionError("merging Prg and Word sources increased runs")
        extra = actual - merged
        actual_total += actual
        merged_total += merged
        affected_frames += int(extra > 0)
        maximum_extra = max(maximum_extra, extra)
    return actual_total, merged_total, affected_frames, maximum_extra


def measure(label: str, path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise SystemExit(f"decision log does not exist: {path}")
    log = pickle.loads(resolved.read_bytes())
    schedule = log["stream_schedule"]
    transfers = log["pattern_transfers"]
    supply = log["pattern_supply"]

    occupancy = np.asarray(schedule["ring_occupancy"], np.int64)
    before_consume = np.asarray(
        schedule["ring_occupancy_before_consume"], np.int64)
    prg = np.asarray(transfers["prg"], np.int64)
    wr0 = np.asarray(transfers["wr0"], np.int64)
    wr1 = np.asarray(transfers["wr1"], np.int64)
    word = wr0 + wr1
    runs = np.asarray(transfers["runs"], np.int64)
    timed_prg = prg[1:]
    timed_runs = runs[1:]

    normal_patterns = int(log["prg_buf_kb"]) * 1024 // PATTERN_BYTES
    physical_patterns = (
        int(log["prg_physical_ring_kb"]) * 1024 // PATTERN_BYTES)
    (
        actual_runs,
        merged_runs,
        split_frames,
        split_maximum,
    ) = source_boundary_run_cost(log)
    if actual_runs != int(runs.sum()):
        raise AssertionError(
            f"replayed run total {actual_runs} != frozen {int(runs.sum())}")

    capacities = supply["capacities"]
    return {
        "label": label,
        "decisions": str(resolved),
        "profile": str(log["config"]["profile"]["path"]),
        "frames": len(log["frames"]),
        "cold_cap": int(log["max_cold"]),
        "prg_normal_patterns": normal_patterns,
        "prg_normal_kib": int(log["prg_buf_kb"]),
        "prg_physical_patterns": physical_patterns,
        "prg_physical_kib": int(log["prg_physical_ring_kb"]),
        "ring_peak_patterns": int(before_consume.max(initial=0)),
        "ring_peak_kib": float(
            before_consume.max(initial=0) * PATTERN_BYTES / 1024),
        "normal_ceiling_frames": int(
            np.count_nonzero(before_consume >= normal_patterns)),
        "physical_over_frames": int(
            np.count_nonzero(before_consume > physical_patterns)),
        "ring_min_evaluation_patterns": int(
            schedule["ring_min_evaluation"]),
        "ring_min_evaluation_kib": float(
            int(schedule["ring_min_evaluation"]) * PATTERN_BYTES / 1024),
        "ring_min_full_patterns": int(schedule["ring_min_full"]),
        "ring_min_full_kib": float(
            int(schedule["ring_min_full"]) * PATTERN_BYTES / 1024),
        "underflow_frames": int(np.count_nonzero(occupancy < 0)),
        "evaluation_end_frame": int(schedule["evaluation_end_frame"]),
        "prg_cold_total": int(prg.sum()),
        "prg_cold_mean": float(timed_prg.mean()) if timed_prg.size else 0.0,
        "prg_cold_p50": percentile(timed_prg, 0.50),
        "prg_cold_p90": percentile(timed_prg, 0.90),
        "prg_cold_p95": percentile(timed_prg, 0.95),
        "prg_cold_p99": percentile(timed_prg, 0.99),
        "prg_cold_max": int(timed_prg.max(initial=0)),
        "wr0_cold_total": int(wr0.sum()),
        "wr0_capacity": int(capacities["wr0"]),
        "wr1_cold_total": int(wr1.sum()),
        "wr1_capacity": int(capacities["wr1"]),
        "mixed_prg_word_frames": int(
            np.count_nonzero((prg > 0) & (word > 0))),
        "run_total": int(runs.sum()),
        "run_mean": float(timed_runs.mean()) if timed_runs.size else 0.0,
        "run_p50": percentile(timed_runs, 0.50),
        "run_p90": percentile(timed_runs, 0.90),
        "run_p95": percentile(timed_runs, 0.95),
        "run_p99": percentile(timed_runs, 0.99),
        "run_max": int(timed_runs.max(initial=0)),
        "source_split_extra_runs": actual_runs - merged_runs,
        "source_split_affected_frames": split_frames,
        "source_split_maximum_extra": split_maximum,
    }


def main() -> None:
    args = parse_args()
    rows = [
        measure(label, Path(path))
        for label, path in args.case
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(rows[0]),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"TSV: {args.output}")


if __name__ == "__main__":
    main()
