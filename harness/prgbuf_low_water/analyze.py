#!/usr/bin/env python3
"""Correlate modeled/live PrgBuf low water with playback slip transitions."""

from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PATTERN_BYTES = 32
DEFAULT_LOW_PATTERNS = 256
DEFAULT_RING_PATTERNS = 13568


@dataclass(frozen=True)
class TimelineRow:
    frame: int
    model_patterns: int


@dataclass(frozen=True)
class HudRow:
    frame: int
    slip: int
    resync: int
    live_min_patterns: int | None
    underflow_patterns: int | None


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_timeline(path: Path, evaluation_end_frame: int | None) -> list[TimelineRow]:
    result = []
    for row in _read_tsv(path):
        frame = int(row["frame"])
        if evaluation_end_frame is not None and frame > evaluation_end_frame:
            continue
        result.append(TimelineRow(frame, int(row["status_prg"])))
    if not result:
        raise ValueError(f"timeline has no evaluated rows: {path}")
    return result


def _optional_int(row: dict[str, str], name: str) -> int | None:
    value = row.get(name, "").strip()
    return int(value) if value else None


def read_hud(path: Path, evaluation_end_frame: int | None) -> dict[int, HudRow]:
    result: dict[int, HudRow] = {}
    for row in _read_tsv(path):
        frame = int(row["frame"])
        if evaluation_end_frame is not None and frame > evaluation_end_frame:
            continue
        result[frame] = HudRow(
            frame=frame,
            slip=int(row["slip"]),
            resync=int(row["resync"]),
            live_min_patterns=_optional_int(row, "prgbuf_min_patterns_signed"),
            underflow_patterns=_optional_int(row, "prgbuf_underflow_patterns"),
        )
    if not result:
        raise ValueError(f"HUD has no evaluated rows: {path}")
    return result


def contiguous_ranges(rows: Iterable[TimelineRow], threshold: int) -> list[list[TimelineRow]]:
    ranges: list[list[TimelineRow]] = []
    current: list[TimelineRow] = []
    for row in rows:
        if row.model_patterns <= threshold:
            if current and row.frame != current[-1].frame + 1:
                ranges.append(current)
                current = []
            current.append(row)
        elif current:
            ranges.append(current)
            current = []
    if current:
        ranges.append(current)
    return ranges


def contiguous_live_ranges(
    hud: dict[int, HudRow], threshold: int
) -> list[list[HudRow]]:
    ranges: list[list[HudRow]] = []
    current: list[HudRow] = []
    for frame in sorted(hud):
        row = hud[frame]
        if (
            frame > 0
            and row.live_min_patterns is not None
            and row.live_min_patterns <= threshold
        ):
            if current and frame != current[-1].frame + 1:
                ranges.append(current)
                current = []
            current.append(row)
        elif current:
            ranges.append(current)
            current = []
    if current:
        ranges.append(current)
    return ranges


def transition_frames(hud: dict[int, HudRow], field: str) -> list[int]:
    frames = sorted(hud)
    result = []
    previous = 0
    for frame in frames:
        value = getattr(hud[frame], field)
        if value > previous:
            result.append(frame)
        previous = value
    return result


def _first_at_or_after(frames: list[int], start: int) -> int | None:
    return next((frame for frame in frames if frame >= start), None)


def _fmt_optional(value: int | float | None) -> str:
    return "" if value is None else str(value)


def write_ranges(
    path: Path,
    ranges: list[list[TimelineRow]],
    hud: dict[int, HudRow],
    slips: list[int],
    resyncs: list[int],
) -> None:
    fields = [
        "start_frame",
        "end_frame",
        "frame_count",
        "model_min_patterns",
        "model_min_kib",
        "live_min_patterns",
        "live_peak_underflow_patterns",
        "first_slip_frame_at_or_after_start",
        "slip_distance_from_end_frames",
        "first_resync_frame_at_or_after_start",
        "resync_distance_from_end_frames",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for interval in ranges:
            start = interval[0].frame
            end = interval[-1].frame
            observed = [hud[frame] for frame in range(start, end + 1) if frame in hud]
            live_values = [
                row.live_min_patterns
                for row in observed
                if row.live_min_patterns is not None
            ]
            underflows = [
                row.underflow_patterns
                for row in observed
                if row.underflow_patterns is not None
            ]
            next_slip = _first_at_or_after(slips, start)
            next_resync = _first_at_or_after(resyncs, start)
            minimum = min(row.model_patterns for row in interval)
            writer.writerow(
                {
                    "start_frame": start,
                    "end_frame": end,
                    "frame_count": len(interval),
                    "model_min_patterns": minimum,
                    "model_min_kib": f"{minimum * PATTERN_BYTES / 1024:.3f}",
                    "live_min_patterns": _fmt_optional(min(live_values) if live_values else None),
                    "live_peak_underflow_patterns": _fmt_optional(
                        max(underflows) if underflows else None
                    ),
                    "first_slip_frame_at_or_after_start": _fmt_optional(next_slip),
                    "slip_distance_from_end_frames": _fmt_optional(
                        next_slip - end if next_slip is not None else None
                    ),
                    "first_resync_frame_at_or_after_start": _fmt_optional(next_resync),
                    "resync_distance_from_end_frames": _fmt_optional(
                        next_resync - end if next_resync is not None else None
                    ),
                }
            )


def write_events(
    path: Path,
    timeline: list[TimelineRow],
    hud: dict[int, HudRow],
    slips: list[int],
    resyncs: list[int],
    low_patterns: int,
) -> None:
    model = {row.frame: row.model_patterns for row in timeline}
    fields = [
        "event",
        "frame",
        "counter_value",
        "model_patterns",
        "model_kib",
        "model_at_or_below_low_water",
        "live_min_patterns",
        "live_underflow_patterns",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for event, frames in (("slip", slips), ("resync", resyncs)):
            for frame in frames:
                row = hud[frame]
                model_patterns = model.get(frame)
                writer.writerow(
                    {
                        "event": event,
                        "frame": frame,
                        "counter_value": getattr(row, event),
                        "model_patterns": _fmt_optional(model_patterns),
                        "model_kib": (
                            f"{model_patterns * PATTERN_BYTES / 1024:.3f}"
                            if model_patterns is not None
                            else ""
                        ),
                        "model_at_or_below_low_water": (
                            int(model_patterns <= low_patterns)
                            if model_patterns is not None
                            else ""
                        ),
                        "live_min_patterns": _fmt_optional(row.live_min_patterns),
                        "live_underflow_patterns": _fmt_optional(row.underflow_patterns),
                    }
                )


def describe(
    timeline: list[TimelineRow],
    hud: dict[int, HudRow],
    ranges: list[list[TimelineRow]],
    slips: list[int],
    resyncs: list[int],
    low_patterns: int,
    ring_patterns: int,
) -> None:
    model_values = [row.model_patterns for row in timeline]
    print(
        "modeled PrgBuf: "
        f"min={min(model_values)} patterns "
        f"({min(model_values) * PATTERN_BYTES / 1024:.3f} KiB), "
        f"median={statistics.median(model_values):g}, max={max(model_values)}"
    )
    print(
        f"low water <= {low_patterns} patterns "
        f"({low_patterns * PATTERN_BYTES / 1024:.3f} KiB): {len(ranges)} range(s)"
    )
    for interval in ranges:
        next_slip = _first_at_or_after(slips, interval[0].frame)
        print(
            f"  f{interval[0].frame}..f{interval[-1].frame}: "
            f"{len(interval)} frames, min={min(row.model_patterns for row in interval)} patterns, "
            f"next S={next_slip if next_slip is not None else '-'}"
        )
    print(f"counter transitions: S={len(slips)} R={len(resyncs)}")

    live = [
        row.live_min_patterns
        for row in hud.values()
        if row.frame > 0 and row.live_min_patterns is not None
    ]
    if not live:
        print("live Q: unavailable in this HUD TSV")
        return
    live_min = min(live)
    debt = max(-live_min, 0)
    print(f"live Q: minimum={live_min} patterns, peak underflow={debt} patterns")
    live_ranges = contiguous_live_ranges(hud, low_patterns)
    print(
        f"live Q <= {low_patterns} patterns "
        f"({low_patterns * PATTERN_BYTES / 1024:.3f} KiB): "
        f"{len(live_ranges)} range(s)"
    )
    for interval in live_ranges:
        next_slip = _first_at_or_after(slips, interval[0].frame)
        distance = (
            next_slip - interval[-1].frame if next_slip is not None else None
        )
        print(
            f"  f{interval[0].frame}..f{interval[-1].frame}: "
            f"{len(interval)} frames, "
            f"min={min(row.live_min_patterns for row in interval if row.live_min_patterns is not None)} "
            f"patterns, next S={next_slip if next_slip is not None else '-'}, "
            f"distance from end={distance if distance is not None else '-'} frames"
        )
    if debt:
        modulo_alias = live_min % ring_patterns
        print(
            "underflow modulo alias: "
            f"{live_min} logical patterns appears as {modulo_alias} / {ring_patterns} "
            f"patterns ({modulo_alias * PATTERN_BYTES / 1024:.3f} KiB)"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("timeline_tsv", type=Path)
    parser.add_argument("hud_tsv", type=Path)
    parser.add_argument("--ranges-tsv", type=Path, required=True)
    parser.add_argument("--events-tsv", type=Path, required=True)
    parser.add_argument("--low-patterns", type=int, default=DEFAULT_LOW_PATTERNS)
    parser.add_argument("--ring-patterns", type=int, default=DEFAULT_RING_PATTERNS)
    parser.add_argument("--evaluation-end-frame", type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    timeline = read_timeline(args.timeline_tsv, args.evaluation_end_frame)
    hud = read_hud(args.hud_tsv, args.evaluation_end_frame)
    ranges = contiguous_ranges(timeline, args.low_patterns)
    slips = transition_frames(hud, "slip")
    resyncs = transition_frames(hud, "resync")
    write_ranges(args.ranges_tsv, ranges, hud, slips, resyncs)
    write_events(
        args.events_tsv,
        timeline,
        hud,
        slips,
        resyncs,
        args.low_patterns,
    )
    describe(
        timeline,
        hud,
        ranges,
        slips,
        resyncs,
        args.low_patterns,
        args.ring_patterns,
    )


if __name__ == "__main__":
    main()
