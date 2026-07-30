#!/usr/bin/env python3
"""Summarize the Main-CPU critical path before pattern-transfer readiness."""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from harness.pipeline_speedup.verify_main_fastpaths import (  # noqa: E402
    ControlBlock,
    read_stream,
)
from tools import shadow_updates  # noqa: E402


MAIN_CLOCK_HZ = 7_670_454
CPU_CYCLES_PER_SCANLINE = 488.0
GA_STOPWATCH_TICK_US = 30.72
VISIBLE_SCANLINES = 0xE0
MISSED_HEAD_PRESSURE = 0x100
NT_STAGE_PITCH = 64

# MC68000 User's Manual nominal timings. Platform wait states remain outside
# this instruction-cycle model, just as they do in tools/shadow_updates.py.
MOVE_L_POSTINC_POSTINC = 20
MOVE_W_POSTINC_POSTINC = 12
LEA_DISP = 8
LEA_ABS_LONG = 12
MOVE_W_IMMEDIATE_DN = 8
DBRA_CONTINUE = 10
DBRA_EXPIRED = 14
BRA_W = 10

# Standard specialized H40 DEBUG path from the pass2-entry stopwatch read at
# bf_dma through the pattern_dma_ready_vcounter store. This includes the
# stopwatch quantization/store, DEBUG counter clears, final-blank reserve
# lookup, O_LOADS cursor setup, and ready V-counter sample. The ordinary
# no-palette-switch branch is used; a due switch adds only six nominal cycles.
PASS2_SAMPLE_MATH = 16 + 8 + 10 + 8 + 10 + 16
DEBUG_COUNTER_RESET = 4 + 2 * 20 + 6 * 20
FINAL_RESERVE_LOOKUP = 8 + 16 + 16 + 8 + 10 + 16
PATTERN_PATH_SETUP = 20 + 16 + 12 + 20 + 12
READY_SAMPLE = 4 + 4 + 16 + 22 + 16


@dataclass(frozen=True)
class Summary:
    metric: str
    subset: str
    samples: int
    minimum: float
    p50: float
    p90: float
    p95: float
    p99: float
    maximum: float
    mean: float
    unit: str


def scanline_us() -> float:
    return CPU_CYCLES_PER_SCANLINE / MAIN_CLOCK_HZ * 1_000_000.0


def cycles_to_scanlines(cycles: np.ndarray | float | int) -> np.ndarray:
    return np.asarray(cycles, dtype=np.float64) / CPU_CYCLES_PER_SCANLINE


def nt_stage_copy_cycles(cols: int, rows: int) -> int:
    """Return nominal cycles for the current H40 shadow-to-NT-stage copy."""

    if not 0 < cols <= NT_STAGE_PITCH:
        raise ValueError(f"cols must stay in 1..{NT_STAGE_PITCH}, got {cols}")
    if rows <= 0:
        raise ValueError(f"rows must be positive, got {rows}")
    longwords, tail_words = divmod(cols, 2)
    per_row = (
        longwords * MOVE_L_POSTINC_POSTINC
        + tail_words * MOVE_W_POSTINC_POSTINC
        + LEA_DISP
    )
    row_loop = (rows - 1) * DBRA_CONTINUE + DBRA_EXPIRED
    setup_and_exit = (
        2 * LEA_ABS_LONG
        + MOVE_W_IMMEDIATE_DN
        + BRA_W
    )
    return setup_and_exit + rows * per_row + row_loop


def pass2_to_ready_cycles() -> int:
    """Return nominal cycles from the pass2 timestamp through ready sampling."""

    return (
        PASS2_SAMPLE_MATH
        + DEBUG_COUNTER_RESET
        + FINAL_RESERVE_LOOKUP
        + PATTERN_PATH_SETUP
        + READY_SAMPLE
    )


def update_cells(block: ControlBlock, total_cells: int) -> list[int]:
    cells: list[int] = []
    for cell in range(total_cells):
        if block.bitmap[cell >> 3] & (1 << (cell & 7)):
            cells.append(cell)
    if len(cells) != len(block.entries):
        raise AssertionError(
            f"frame {block.seq}: bitmap has {len(cells)} updates, "
            f"entries have {len(block.entries)}"
        )
    return cells


def shadow_update_cycles(block: ControlBlock, total_cells: int) -> int:
    if not block.entries:
        return 0
    if block.use_list:
        return shadow_updates.update_list_cycles(len(block.entries))
    return shadow_updates.legacy_bitmap_cycles(
        update_cells(block, total_cells),
        total_cells,
    )


def ready_pressure(raw_vcounter: int) -> int:
    if not 0 <= raw_vcounter <= 0xFF:
        raise ValueError(f"V-counter outside 00..FF: {raw_vcounter}")
    return (
        raw_vcounter
        if raw_vcounter <= VISIBLE_SCANLINES
        else MISSED_HEAD_PRESSURE
    )


def summarize(
    metric: str,
    subset: str,
    values: np.ndarray,
    unit: str = "scanlines",
) -> Summary:
    measured = np.asarray(values, dtype=np.float64)
    if measured.ndim != 1 or not measured.size:
        raise ValueError(f"{metric}/{subset} has no one-dimensional samples")
    percentiles = np.percentile(measured, (50, 90, 95, 99))
    return Summary(
        metric=metric,
        subset=subset,
        samples=int(measured.size),
        minimum=float(measured.min()),
        p50=float(percentiles[0]),
        p90=float(percentiles[1]),
        p95=float(percentiles[2]),
        p99=float(percentiles[3]),
        maximum=float(measured.max()),
        mean=float(measured.mean()),
        unit=unit,
    )


def read_hud(path: Path, expected_frames: int) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if len(rows) != expected_frames:
        raise SystemExit(
            f"HUD has {len(rows)} rows, packed stream has {expected_frames} frames"
        )
    for expected, row in enumerate(rows):
        if int(row["frame"], 10) != expected:
            raise SystemExit(
                f"HUD row {expected} carries frame {row['frame']!r}"
            )
    return rows


def build_summaries(
    header: Path,
    body: Path,
    hud_tsv: Path,
) -> list[Summary]:
    stream = read_stream(header, body)
    if stream.cols != 40:
        raise SystemExit(
            f"PT pre-work analyzer currently requires H40, got {stream.cols} columns"
        )
    hud = read_hud(hud_tsv, len(stream.controls))

    frame_index = np.arange(len(hud), dtype=np.int64)
    cold_runs = np.asarray([int(row["cold_runs"], 10) for row in hud])
    pt_mask = (frame_index > 0) & (cold_runs > 0)
    if not np.any(pt_mask):
        raise SystemExit("HUD contains no timed frame with a pattern run")

    update_count = np.asarray(
        [len(block.entries) for block in stream.controls],
        dtype=np.float64,
    )
    list_mask = np.asarray(
        [block.use_list for block in stream.controls],
        dtype=np.bool_,
    )
    shadow_cycles = np.asarray(
        [
            shadow_update_cycles(block, stream.cells)
            for block in stream.controls
        ],
        dtype=np.float64,
    )
    shadow_lines = cycles_to_scanlines(shadow_cycles)
    nt_lines_value = float(
        cycles_to_scanlines(nt_stage_copy_cycles(stream.cols, stream.rows))
    )
    nt_lines = np.full(len(hud), nt_lines_value, dtype=np.float64)
    name_work_lines = shadow_lines + nt_lines

    sub_wait_lines = np.asarray(
        [int(row["sub_wait_scanlines"], 10) for row in hud],
        dtype=np.float64,
    )
    pass2_q4 = np.asarray(
        [int(row["pass2_delay_q4"], 10) for row in hud],
        dtype=np.float64,
    )
    pass2_lines = (
        pass2_q4 * 4.0 * GA_STOPWATCH_TICK_US / scanline_us()
    )
    pass2_to_ready_lines_value = float(
        cycles_to_scanlines(pass2_to_ready_cycles())
    )
    pass2_to_ready_lines = np.full(
        len(hud),
        pass2_to_ready_lines_value,
        dtype=np.float64,
    )
    previous_flip_to_ready_lines = pass2_lines + pass2_to_ready_lines
    residual_lines = (
        pass2_lines - sub_wait_lines - shadow_lines - nt_lines
    )
    pressure = np.asarray(
        [
            ready_pressure(int(row["pattern_dma_ready_vcounter"], 16))
            for row in hud
        ],
        dtype=np.float64,
    )
    margin = np.maximum(
        VISIBLE_SCANLINES
        - np.minimum(pressure, VISIBLE_SCANLINES),
        0,
    )

    summaries = [
        summarize("updates", "all PT frames", update_count[pt_mask], "cells"),
        summarize(
            "sub_wait_measured",
            "all PT frames",
            sub_wait_lines[pt_mask],
        ),
        summarize(
            "shadow_update_nominal",
            "all PT frames",
            shadow_lines[pt_mask],
        ),
    ]
    for use_list, label in ((False, "bitmap PT frames"), (True, "list PT frames")):
        selected = pt_mask & (list_mask == use_list)
        if np.any(selected):
            summaries.append(
                summarize(
                    "shadow_update_nominal",
                    label,
                    shadow_lines[selected],
                )
            )
    summaries.extend(
        [
            summarize(
                "nt_stage_copy_nominal",
                "all PT frames",
                nt_lines[pt_mask],
            ),
            summarize(
                "shadow_plus_nt_stage_nominal",
                "all PT frames",
                name_work_lines[pt_mask],
            ),
            summarize(
                "pass2_entry_observed",
                "all PT frames",
                pass2_lines[pt_mask],
            ),
            summarize(
                "pass2_to_ready_nominal",
                "all PT frames",
                pass2_to_ready_lines[pt_mask],
            ),
            summarize(
                "previous_flip_to_ready_estimated",
                "all PT frames",
                previous_flip_to_ready_lines[pt_mask],
            ),
            summarize(
                "unmodelled_fixed_and_quantization",
                "all PT frames",
                residual_lines[pt_mask],
            ),
            summarize(
                "pattern_ready_pressure",
                "all PT frames",
                pressure[pt_mask],
            ),
            summarize(
                "pattern_ready_margin",
                "all PT frames",
                margin[pt_mask],
            ),
        ]
    )
    return summaries


def render_tsv(summaries: list[Summary]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output, delimiter="\t", lineterminator="\n")
    writer.writerow(
        (
            "metric",
            "subset",
            "samples",
            "min",
            "p50",
            "p90",
            "p95",
            "p99",
            "max",
            "mean",
            "unit",
        )
    )
    for item in summaries:
        writer.writerow(
            (
                item.metric,
                item.subset,
                item.samples,
                f"{item.minimum:.3f}",
                f"{item.p50:.3f}",
                f"{item.p90:.3f}",
                f"{item.p95:.3f}",
                f"{item.p99:.3f}",
                f"{item.maximum:.3f}",
                f"{item.mean:.3f}",
                item.unit,
            )
        )
    return output.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize H40 Main-CPU work before the first pattern-transfer "
            "VBlank wait."
        )
    )
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--hud-tsv", type=Path, required=True)
    parser.add_argument("--output-tsv", type=Path)
    args = parser.parse_args()

    text = render_tsv(build_summaries(args.header, args.body, args.hud_tsv))
    if args.output_tsv is None:
        sys.stdout.write(text)
        return
    if args.output_tsv.suffix != ".tsv":
        parser.error("--output-tsv must end in .tsv")
    args.output_tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.output_tsv.open("w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    print(args.output_tsv)


if __name__ == "__main__":
    main()
