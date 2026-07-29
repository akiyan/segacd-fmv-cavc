#!/usr/bin/env python3
"""Correlate modeled PrgBuf low water with playback slip transitions."""

from __future__ import annotations

import argparse
import csv
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PATTERN_BYTES = 32
DEFAULT_LOW_PATTERNS = 256


@dataclass(frozen=True)
class TimelineRow:
    frame: int
    model_patterns: int


@dataclass(frozen=True)
class HudRow:
    frame: int
    sector_slip: int
    audio_resync: int
    capture_first: int | None = None
    pump_gap_ticks: int | None = None
    apply_backpressure: int | None = None
    msf_gap_recoveries: int | None = None
    transport_retry_recoveries: int | None = None


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
        sector_slip = int(row["sector_slip"])
        msf_gap_recoveries = _optional_int(row, "msf_gap_recoveries")
        result[frame] = HudRow(
            frame=frame,
            sector_slip=sector_slip,
            audio_resync=int(row["audio_resync"]),
            capture_first=_optional_int(row, "capture_first"),
            pump_gap_ticks=_optional_int(row, "pump_gap_ticks"),
            apply_backpressure=_optional_int(row, "apply_backpressure"),
            msf_gap_recoveries=msf_gap_recoveries,
            transport_retry_recoveries=(
                (sector_slip - msf_gap_recoveries) & 0xF
                if msf_gap_recoveries is not None else None
            ),
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


def apply_block_frames(hud: dict[int, HudRow]) -> list[int]:
    return [
        frame
        for frame in sorted(hud)
        if hud[frame].apply_backpressure
    ]


def prior_frame(frames: list[int], target: int) -> int | None:
    return next((frame for frame in reversed(frames) if frame <= target), None)


def interval_extra_scanouts(
    hud: dict[int, HudRow],
    start: int,
    end: int,
    normal_vblanks: int | None,
) -> int | None:
    if normal_vblanks is None:
        return None
    extra = 0
    for frame in range(start, end + 1):
        current = hud.get(frame)
        following = hud.get(frame + 1)
        if (
            current is None
            or following is None
            or current.capture_first is None
            or following.capture_first is None
        ):
            continue
        extra += max(
            0,
            following.capture_first
            - current.capture_first
            - normal_vblanks,
        )
    return extra


def write_ranges(
    path: Path,
    ranges: list[list[TimelineRow]],
    hud: dict[int, HudRow],
    slips: list[int],
    resyncs: list[int],
    normal_vblanks: int | None = None,
) -> None:
    fields = [
        "start_frame",
        "end_frame",
        "frame_count",
        "model_min_patterns",
        "model_min_kib",
        "extra_scanouts",
        "first_sector_slip_frame_at_or_after_start",
        "sector_slip_distance_from_end_frames",
        "first_audio_resync_frame_at_or_after_start",
        "audio_resync_distance_from_end_frames",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for interval in ranges:
            start = interval[0].frame
            end = interval[-1].frame
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
                    "extra_scanouts": _fmt_optional(
                        interval_extra_scanouts(
                            hud, start, end, normal_vblanks
                        )
                    ),
                    "first_sector_slip_frame_at_or_after_start": _fmt_optional(
                        next_slip
                    ),
                    "sector_slip_distance_from_end_frames": _fmt_optional(
                        next_slip - end if next_slip is not None else None
                    ),
                    "first_audio_resync_frame_at_or_after_start": _fmt_optional(
                        next_resync
                    ),
                    "audio_resync_distance_from_end_frames": _fmt_optional(
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
        "pump_gap_ticks",
        "apply_backpressure",
        "msf_gap_recoveries",
        "transport_retry_recoveries",
        "prior_apply_block_frame",
        "distance_from_prior_apply_block_frames",
    ]
    blocked = apply_block_frames(hud)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        for event, frames in (
            ("sector_slip", slips),
            ("audio_resync", resyncs),
        ):
            for frame in frames:
                row = hud[frame]
                model_patterns = model.get(frame)
                prior_block = prior_frame(blocked, frame)
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
                        "pump_gap_ticks": _fmt_optional(row.pump_gap_ticks),
                        "apply_backpressure": _fmt_optional(
                            row.apply_backpressure
                        ),
                        "msf_gap_recoveries": _fmt_optional(
                            row.msf_gap_recoveries
                        ),
                        "transport_retry_recoveries": _fmt_optional(
                            row.transport_retry_recoveries
                        ),
                        "prior_apply_block_frame": _fmt_optional(prior_block),
                        "distance_from_prior_apply_block_frames": _fmt_optional(
                            frame - prior_block
                            if prior_block is not None else None
                        ),
                    }
                )


def describe(
    timeline: list[TimelineRow],
    hud: dict[int, HudRow],
    ranges: list[list[TimelineRow]],
    slips: list[int],
    resyncs: list[int],
    low_patterns: int,
    normal_vblanks: int | None = None,
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
        extra_scanouts = interval_extra_scanouts(
            hud,
            interval[0].frame,
            interval[-1].frame,
            normal_vblanks,
        )
        print(
            f"  f{interval[0].frame}..f{interval[-1].frame}: "
            f"{len(interval)} frames, min={min(row.model_patterns for row in interval)} patterns, "
            "next sector_slip="
            f"{next_slip if next_slip is not None else '-'}, "
            "extra scanouts="
            f"{_fmt_optional(extra_scanouts) or '-'}"
        )
    print(
        "counter transitions: "
        f"sector_slip={len(slips)} audio_resync={len(resyncs)}"
    )

    poll_gaps = [
        row.pump_gap_ticks
        for row in hud.values()
        if row.frame > 0 and row.pump_gap_ticks is not None
    ]
    if poll_gaps:
        print(
            "pump_gap_ticks: "
            f"min={min(poll_gaps)} mean={statistics.fmean(poll_gaps):.3f} "
            f"median={statistics.median(poll_gaps):g} max={max(poll_gaps)} ticks"
        )
    blocked = apply_block_frames(hud)
    if blocked:
        print(
            f"APPLY back-pressure: {len(blocked)} frame(s), "
            f"first=f{blocked[0]}, last=f{blocked[-1]}"
        )
        immediate = []
        for slip in slips:
            previous = prior_frame(blocked, slip)
            if previous is not None and slip - previous == 1:
                immediate.append((previous, slip))
        print(
            "APPLY back-pressure immediately precedes sector_slip: "
            f"{len(immediate)} transition frame(s)"
        )
        for block, slip in immediate:
            print(f"  apply frame {block} -> sector_slip frame {slip}")
    msf_counts = [
        row.msf_gap_recoveries
        for row in hud.values()
        if row.msf_gap_recoveries is not None
    ]
    trn_counts = [
        row.transport_retry_recoveries
        for row in hud.values()
        if row.transport_retry_recoveries is not None
    ]
    if msf_counts:
        print(
            "sector-slip cause counters: "
            f"MSF gap recoveries={max(msf_counts)}, "
            f"transport retry recoveries={max(trn_counts, default=0)}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("timeline_tsv", type=Path)
    parser.add_argument("hud_tsv", type=Path)
    parser.add_argument("--ranges-tsv", type=Path, required=True)
    parser.add_argument("--events-tsv", type=Path, required=True)
    parser.add_argument("--low-patterns", type=int, default=DEFAULT_LOW_PATTERNS)
    parser.add_argument("--evaluation-end-frame", type=int)
    parser.add_argument(
        "--normal-vblanks",
        type=int,
        help="expected capture scanouts per content frame (for example 2 at 30 fps)",
    )
    args = parser.parse_args()
    if args.normal_vblanks is not None and args.normal_vblanks < 1:
        parser.error("--normal-vblanks must be at least 1")
    return args


def main() -> None:
    args = parse_args()
    timeline = read_timeline(args.timeline_tsv, args.evaluation_end_frame)
    hud = read_hud(args.hud_tsv, args.evaluation_end_frame)
    ranges = contiguous_ranges(timeline, args.low_patterns)
    slips = transition_frames(hud, "sector_slip")
    resyncs = transition_frames(hud, "audio_resync")
    write_ranges(
        args.ranges_tsv,
        ranges,
        hud,
        slips,
        resyncs,
        args.normal_vblanks,
    )
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
        args.normal_vblanks,
    )


if __name__ == "__main__":
    main()
