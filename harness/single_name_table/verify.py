#!/usr/bin/env python3
"""Prove old double-NT and new single-NT display states are identical."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(TOOLS))

from harness.pipeline_speedup.verify_main_fastpaths import (  # noqa: E402
    read_stream,
    update_reference,
)
import player_constants  # noqa: E402


NT_PITCH = 64
NT_ROWS = 28
NT_WORDS = NT_PITCH * NT_ROWS


@dataclass(frozen=True)
class Case:
    name: str
    header: Path
    body: Path


def parse_case(values: list[str]) -> Case:
    name, header, body = values
    return Case(name, Path(header), Path(body))


def old_double_nt_frame(
    tables: list[list[int]], back: int, shadow: list[int], *,
    cols: int, rows: int, col0: int, row0: int,
) -> int:
    """Model the removed full logical-grid CPU blit followed by reg2 flip."""
    table = tables[back]
    for row in range(rows):
        src = row * cols
        dst = (row0 + row) * NT_PITCH + col0
        table[dst:dst + cols] = shadow[src:src + cols]
    return back


def new_single_nt_frame(
    table: list[int], shadow: list[int], *,
    cols: int, rows: int, col0: int, row0: int,
) -> int:
    """Model the exact 64-pitch Main-RAM stage and its one visible-table DMA."""
    band_words = (rows - 1) * NT_PITCH + cols
    stage = [0] * band_words
    for row in range(rows):
        src = row * cols
        dst = row * NT_PITCH
        stage[dst:dst + cols] = shadow[src:src + cols]
    destination = row0 * NT_PITCH + col0
    table[destination:destination + band_words] = stage
    return band_words


def verify_case(case: Case) -> tuple[int, int]:
    if not case.header.is_file() or not case.body.is_file():
        raise AssertionError(f"{case.name}: missing HEADER.DAT or BODY.DAT")
    stream = read_stream(case.header, case.body)
    constants = player_constants.parse_header_sector(
        case.header.read_bytes()[:player_constants.SECTOR])
    if (stream.cols, stream.rows) != (constants.tcols, constants.trows):
        raise AssertionError(f"{case.name}: stream/header geometry differs")

    shadow = [0] * stream.cells
    old_tables = [[0] * NT_WORDS, [0] * NT_WORDS]
    old_front = 1
    new_table = [0] * NT_WORDS
    expected_band = (stream.rows - 1) * NT_PITCH + stream.cols

    for block in stream.controls:
        update_reference(shadow, block, stream.cells)
        old_back = old_front ^ 1
        old_front = old_double_nt_frame(
            old_tables,
            old_back,
            shadow,
            cols=stream.cols,
            rows=stream.rows,
            col0=constants.col0,
            row0=constants.row0,
        )
        band_words = new_single_nt_frame(
            new_table,
            shadow,
            cols=stream.cols,
            rows=stream.rows,
            col0=constants.col0,
            row0=constants.row0,
        )
        if band_words != expected_band:
            raise AssertionError(
                f"{case.name}: frame {block.seq} band {band_words} != "
                f"{expected_band}")
        if old_tables[old_front] != new_table:
            mismatch = next(
                index for index, pair in enumerate(
                    zip(old_tables[old_front], new_table))
                if pair[0] != pair[1]
            )
            raise AssertionError(
                f"{case.name}: frame {block.seq} differs at NT word {mismatch}")

    return len(stream.controls), expected_band


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case", action="append", nargs=3, metavar=("NAME", "HEADER", "BODY"),
        required=True,
    )
    args = parser.parse_args()
    total_frames = 0
    for raw_case in args.case:
        case = parse_case(raw_case)
        frames, band_words = verify_case(case)
        total_frames += frames
        print(
            f"{case.name}: {frames} frames, "
            f"{band_words}-word single-NT band: IDENTICAL")
    print(f"single name-table equivalence: OK ({total_frames} frames)")


if __name__ == "__main__":
    main()
