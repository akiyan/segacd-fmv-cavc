#!/usr/bin/env python3
"""Extract frame-aligned VDP transfer diagnostics from a GPGX LOGVDP run."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Iterable, Iterator, TextIO


DMA_RE = re.compile(
    r"DMA type (\d+) \((\d+) access/line\)"
    r"\((\d+) cycles left\)-> (\d+) access "
    r"\((\d+) remaining\) \(([0-9A-Fa-f]+)\)"
)
VRAM_RE = re.compile(
    r"\[(\d+)\((\d+)\)\]\[(\d+)\((\d+)\)\] "
    r"VRAM 0x[0-9A-Fa-f]+ write -> 0x[0-9A-Fa-f]+ "
    r"\(([0-9A-Fa-f]+)\)"
)

OUTPUT_COLUMNS = (
    "frame",
    "pattern_dma_commands",
    "pattern_dma_updates",
    "pattern_dma_blank_words",
    "pattern_dma_active_words",
    "pattern_cpu_blank_words",
    "pattern_cpu_active_words",
    "pattern_cpu_boundary_words",
    "name_table_dma_blank_words",
    "name_table_dma_active_words",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("compact_log", type=Path)
    parser.add_argument("--full-log-gz", type=Path, required=True)
    parser.add_argument("--hud-tsv", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.full_log_gz.suffix != ".gz":
        parser.error("--full-log-gz must name a .gz file")
    if args.hud_tsv.suffix != ".tsv":
        parser.error("--hud-tsv must name a .tsv file")
    if args.output.suffix != ".tsv":
        parser.error("--output must name a .tsv file")
    return args


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def log_lines(path: Path) -> Iterator[str]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as source:
            yield from source
    else:
        with path.open("r", encoding="utf-8", errors="replace") as source:
            yield from source


def pc16(text: str) -> int:
    return int(text, 16) & 0xFFFF


def dma_events(lines: Iterable[str]) -> list[tuple[int, int, int, int, int, int]]:
    events = []
    for line in lines:
        match = DMA_RE.search(line)
        if not match:
            continue
        dma_type, rate, cycles_left, capacity, remaining = (
            int(value) for value in match.groups()[:5]
        )
        events.append((
            dma_type,
            rate,
            cycles_left,
            capacity,
            remaining,
            pc16(match.group(6)),
        ))
    return events


def infer_dma_pcs(
    events: list[tuple[int, int, int, int, int, int]],
    frame_count: int,
) -> tuple[int, int, int]:
    """Infer the fixed name-table and ordinary pattern DMA call sites."""
    nt_counts = Counter(
        pc for dma_type, _rate, _left, _capacity, remaining, pc in events
        if dma_type == 1 and remaining == 1792
    )
    nt_candidates = [
        (pc, count) for pc, count in nt_counts.items() if count >= frame_count
    ]
    nt_candidates.sort(key=lambda item: item[1], reverse=True)
    if (
        not nt_candidates
        or (
            len(nt_candidates) > 1
            and nt_candidates[0][1] == nt_candidates[1][1]
        )
    ):
        rendered = ", ".join(
            f"0x{pc:04X}:{count}" for pc, count in nt_counts.most_common(8)
        )
        raise ValueError(
            "could not identify at least one 1792-word name-table DMA per "
            "HUD frame; "
            f"candidates were {rendered or 'none'}"
        )
    nt_pc = nt_candidates[0][0]

    pattern_counts = Counter(
        pc for dma_type, _rate, _left, _capacity, _remaining, pc in events
        if dma_type == 1 and pc != nt_pc
    )
    if not pattern_counts:
        raise ValueError("LOGVDP trace contains no pattern DMA candidate")
    pattern_pc, _count = pattern_counts.most_common(1)[0]

    nt_rates = Counter(
        rate for dma_type, rate, _left, _capacity, remaining, pc in events
        if dma_type == 1 and pc == nt_pc and remaining == 1792
    )
    blank_rate, _count = nt_rates.most_common(1)[0]
    return pattern_pc, nt_pc, blank_rate


def empty_rows(frame_count: int) -> list[dict[str, int]]:
    return [
        {column: (frame if column == "frame" else 0) for column in OUTPUT_COLUMNS}
        for frame in range(frame_count)
    ]


def extract_dma_rows(
    events: list[tuple[int, int, int, int, int, int]],
    frame_count: int,
    pattern_pc: int,
    nt_pc: int,
    blank_rate: int,
) -> list[dict[str, int]]:
    rows = empty_rows(frame_count)
    next_frame = 0
    pattern_open = False
    nt_open = False
    nt_frame: int | None = None

    for dma_type, rate, _left, capacity, remaining, pc in events:
        if next_frame >= frame_count and not nt_open:
            break
        if dma_type != 1:
            continue
        if pc == nt_pc:
            if not nt_open:
                if remaining != 1792:
                    raise ValueError(
                        "name-table DMA continuation appeared without its start"
                    )
                if next_frame >= frame_count:
                    raise ValueError("LOGVDP trace has more movie frames than HUD TSV")
                nt_frame = next_frame
                next_frame += 1
            assert nt_frame is not None
            actual = min(capacity, remaining)
            key = (
                "name_table_dma_blank_words"
                if rate == blank_rate
                else "name_table_dma_active_words"
            )
            rows[nt_frame][key] += actual
            nt_open = remaining > capacity
            continue

        if pc != pattern_pc:
            continue
        if next_frame >= frame_count:
            raise ValueError("pattern DMA appeared after the final HUD frame")
        row = rows[next_frame]
        if not pattern_open:
            row["pattern_dma_commands"] += 1
        row["pattern_dma_updates"] += 1
        actual = min(capacity, remaining)
        key = (
            "pattern_dma_blank_words"
            if rate == blank_rate
            else "pattern_dma_active_words"
        )
        row[key] += actual
        pattern_open = remaining > capacity

    if next_frame != frame_count:
        raise ValueError(
            f"LOGVDP trace has {next_frame} name-table frames; "
            f"HUD TSV has {frame_count}"
        )
    if pattern_open or nt_open:
        raise ValueError("LOGVDP trace ends during a DMA command")
    return rows


def extract_cpu_rows(
    lines: Iterable[str],
    rows: list[dict[str, int]],
    pattern_pc: int,
    nt_pc: int,
) -> None:
    """Count non-DMA VRAM writes between the inferred movie-frame markers.

    The fixed H40 player sends the full name table by DMA. Between two such
    markers, every other VRAM data-port write is therefore either a short
    pattern run or the one-word repair after a Word-RAM DMA. Generated DMA
    writes carry the DMA call-site PC and are excluded.
    """
    frame_count = len(rows)
    next_frame = 0
    generated_pcs = {pattern_pc, nt_pc}
    for line in lines:
        dma_match = DMA_RE.search(line)
        if dma_match:
            dma_type = int(dma_match.group(1))
            remaining = int(dma_match.group(5))
            pc = pc16(dma_match.group(6))
            if dma_type == 1 and pc == nt_pc and remaining == 1792:
                next_frame += 1
                if next_frame >= frame_count:
                    break
            continue
        if "VRAM " not in line:
            continue
        match = VRAM_RE.search(line)
        if not match:
            continue
        effective_vcounter = int(match.group(2))
        pc = pc16(match.group(5))
        if pc in generated_pcs or next_frame >= frame_count:
            continue
        if 224 <= effective_vcounter <= 260:
            phase = "blank"
        elif 0 <= effective_vcounter <= 222:
            phase = "active"
        else:
            # LOGVDP can represent the VBlank edge as effective line 223 or
            # the scanout wrap as 261. Preserve those words separately rather
            # than silently choosing one side of the boundary.
            phase = "boundary"
        rows[next_frame][f"pattern_cpu_{phase}_words"] += 1


def load_hud(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        fields = set(reader.fieldnames or ())
        required = {"loop", "frame"}
        missing = required - fields
        if missing:
            raise ValueError(f"HUD TSV lacks columns: {sorted(missing)}")
        rows = [row for row in reader if int(row["loop"]) == 0]
    frames = [int(row["frame"]) for row in rows]
    if frames != list(range(len(rows))):
        raise ValueError("first-loop HUD frames must be contiguous and start at zero")
    return rows


def validate_frame_axis(
    rows: list[dict[str, int]],
    hud_rows: list[dict[str, str]],
) -> None:
    if len(rows) != len(hud_rows):
        raise ValueError("DMA rows and HUD rows have different frame counts")


def write_tsv(path: Path, rows: list[dict[str, int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output,
            fieldnames=OUTPUT_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def maximums(rows: list[dict[str, int]]) -> dict[str, int]:
    return {
        column: max((row[column] for row in rows[1:]), default=0)
        for column in OUTPUT_COLUMNS
        if column != "frame"
    }


def main() -> None:
    args = parse_args()
    compact_log = args.compact_log.resolve()
    full_log = args.full_log_gz.resolve()
    hud_tsv = args.hud_tsv.resolve()
    output = args.output.resolve()
    for path in (compact_log, full_log, hud_tsv):
        if not path.is_file():
            raise SystemExit(f"input does not exist: {path}")

    try:
        hud_rows = load_hud(hud_tsv)
        events = dma_events(log_lines(compact_log))
        pattern_pc, nt_pc, blank_rate = infer_dma_pcs(events, len(hud_rows))
        rows = extract_dma_rows(
            events,
            len(hud_rows),
            pattern_pc,
            nt_pc,
            blank_rate,
        )
        extract_cpu_rows(log_lines(full_log), rows, pattern_pc, nt_pc)
        validate_frame_axis(rows, hud_rows)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    write_tsv(output, rows)
    receipt = {
        "schema_version": 2,
        "kind": "gpgx-logvdp-frame-transfer",
        "compact_log": str(compact_log),
        "compact_log_sha256": digest(compact_log),
        "full_log_gz": str(full_log),
        "full_log_gz_sha256": digest(full_log),
        "hud_tsv": str(hud_tsv),
        "hud_tsv_sha256": digest(hud_tsv),
        "output_tsv": str(output),
        "output_tsv_sha256": digest(output),
        "frames": len(rows),
        "pattern_dma_pc": f"0x{pattern_pc:04X}",
        "name_table_dma_pc": f"0x{nt_pc:04X}",
        "blank_dma_rate_words_per_line": blank_rate,
        "cpu_blank_vcounter_range": [224, 260],
        "cpu_active_vcounter_range": [0, 222],
        "cpu_boundary_vcounters": [223, 261],
        "hud_frame_axis_verified": True,
        "maxima": maximums(rows),
    }
    receipt_path = Path(str(output) + ".json")
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(output)
    print(receipt_path)


if __name__ == "__main__":
    main()
