#!/usr/bin/env python3
"""Replay fixed-cadence BODY delivery against the live APPLY queue."""

from __future__ import annotations

import argparse
import csv
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = REPO_ROOT / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import stream_schedule  # noqa: E402


SECTOR_BYTES = 2048
APPLY_SIZE_BYTES = 34 * 1024
APPLY_GUARD_BYTES = APPLY_SIZE_BYTES - 4 * 1024
DEFAULT_SECTORS_PER_SCANOUT_NUMERATOR = 1001
DEFAULT_SECTORS_PER_SCANOUT_DENOMINATOR = 800


@dataclass(frozen=True)
class HudRow:
    frame: int
    capture_first: int
    sector_slip: int
    apply_backpressure: int


@dataclass(frozen=True)
class ReplayRow:
    frame: int
    physical_sectors: int
    rate_sectors: int
    rate_lead: int
    peak_rate_lead: int
    conservative_ahead_sectors: int
    extra_scanouts: int | None
    extra_cd_sectors: int | None
    observed_ahead_sectors: int | None
    producer_sector_cursor: int
    delivered_control_sectors: int
    consumed_control_bytes: int
    apply_occupancy_bytes: int
    next_sector_kind: str
    predicted_apply_blocked: int
    observed_apply_blocked: int | None
    observed_slip: int | None


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def read_hud(path: Path) -> dict[int, HudRow]:
    result: dict[int, HudRow] = {}
    for raw in _read_tsv(path):
        frame = int(raw["frame"])
        capture = raw.get("capture_first", "").strip()
        blocked = raw.get("apply_backpressure", "").strip()
        if not capture:
            continue
        result[frame] = HudRow(
            frame=frame,
            capture_first=int(capture),
            sector_slip=int(raw["sector_slip"]),
            apply_backpressure=int(blocked) if blocked else 0,
        )
    if not result:
        raise ValueError(f"HUD has no usable rows: {path}")
    return result


def load_schedule(path: Path) -> tuple[dict, dict]:
    with path.open("rb") as handle:
        decisions = pickle.load(handle)  # noqa: S301 - local project artifact
    schedule = decisions.get("stream_schedule")
    if not isinstance(schedule, dict):
        raise ValueError("decisions artifact has no stream_schedule mapping")
    return decisions, schedule


def sector_kinds(
    physical_sectors: np.ndarray,
    control_sectors: np.ndarray,
    payload_sectors: np.ndarray,
) -> np.ndarray:
    """Return the exact control/payload/pad order written to BODY.DAT."""

    if not (
        physical_sectors.shape
        == control_sectors.shape
        == payload_sectors.shape
    ):
        raise ValueError("BODY sector traces must have equal shapes")
    if np.any(control_sectors + payload_sectors > physical_sectors):
        raise ValueError("useful BODY sectors exceed physical slot length")
    kinds: list[str] = []
    for physical, control, payload in zip(
        physical_sectors, control_sectors, payload_sectors
    ):
        kinds.extend(["control"] * int(control))
        kinds.extend(["payload"] * int(payload))
        kinds.extend(["pad"] * int(physical - control - payload))
    return np.asarray(kinds, dtype="<U7")


def lead_trace(
    physical_sectors: np.ndarray, rate_sectors: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """Return current and sticky peak sector debt at every movie frame."""

    if physical_sectors.shape != rate_sectors.shape:
        raise ValueError("physical and rate-sector traces differ")
    lead = np.cumsum(
        physical_sectors - rate_sectors, dtype=np.int64
    )
    if np.any(lead < 0):
        raise ValueError("physical schedule runs below its rate padding")
    return lead, np.maximum.accumulate(lead)


def first_positive_frame(values: np.ndarray) -> int | None:
    positive = np.flatnonzero(values > 0)
    return int(positive[0]) if positive.size else None


def cumulative_extra_scanouts(
    hud: dict[int, HudRow],
    *,
    anchor_frame: int,
    normal_scanouts: int,
) -> dict[int, int]:
    """Measure irreversible display delay from one known on-time frame."""

    if normal_scanouts <= 0:
        raise ValueError("normal scanouts must be positive")
    if anchor_frame not in hud:
        raise ValueError(f"HUD has no anchor frame {anchor_frame}")
    anchor_capture = hud[anchor_frame].capture_first
    result = {}
    for frame, row in hud.items():
        if frame < anchor_frame:
            continue
        expected = anchor_capture + (frame - anchor_frame) * normal_scanouts
        result[frame] = row.capture_first - expected
    return result


def control_prefix(kinds: np.ndarray) -> np.ndarray:
    """Count complete control sectors before every BODY sector cursor."""

    result = np.zeros(len(kinds) + 1, np.int64)
    result[1:] = np.cumsum(kinds == "control", dtype=np.int64)
    return result


def apply_state(
    *,
    frame: int,
    ahead_sectors: int,
    slot_end_cursors: np.ndarray,
    kinds: np.ndarray,
    control_sector_prefix: np.ndarray,
    consumed_control_bytes: np.ndarray,
    guard_bytes: int = APPLY_GUARD_BYTES,
) -> tuple[int, int, int, str, int]:
    """Return producer cursor and APPLY state after consuming one frame."""

    producer_cursor = min(
        len(kinds),
        int(slot_end_cursors[frame]) + max(0, int(ahead_sectors)),
    )
    delivered_control = int(control_sector_prefix[producer_cursor])
    occupancy = (
        delivered_control * SECTOR_BYTES
        - int(consumed_control_bytes[frame])
    )
    next_kind = (
        str(kinds[producer_cursor])
        if producer_cursor < len(kinds)
        else "end"
    )
    blocked = int(
        occupancy >= int(guard_bytes) and next_kind == "control"
    )
    return (
        producer_cursor,
        delivered_control,
        occupancy,
        next_kind,
        blocked,
    )


def advance_apply_producer(
    *,
    producer_cursor: int,
    target_cursor: int,
    delivered_control_sectors: int,
    consumed_control_bytes: int,
    kinds: np.ndarray,
    guard_bytes: int = APPLY_GUARD_BYTES,
) -> tuple[int, int, int, str, int]:
    """Advance a persistent producer until its target or the APPLY guard."""

    cursor = int(producer_cursor)
    target = min(len(kinds), max(cursor, int(target_cursor)))
    delivered = int(delivered_control_sectors)
    blocked = 0
    while cursor < target:
        kind = str(kinds[cursor])
        occupancy = delivered * SECTOR_BYTES - int(consumed_control_bytes)
        if kind == "control" and occupancy >= int(guard_bytes):
            blocked = 1
            break
        if kind == "control":
            delivered += 1
        cursor += 1
    occupancy = delivered * SECTOR_BYTES - int(consumed_control_bytes)
    next_kind = str(kinds[cursor]) if cursor < len(kinds) else "end"
    return cursor, delivered, occupancy, next_kind, blocked


def build_replay(
    *,
    block_lengths: np.ndarray,
    control_sectors: np.ndarray,
    payload_sectors: np.ndarray,
    physical_sectors: np.ndarray,
    rate_sectors: np.ndarray,
    hud: dict[int, HudRow] | None = None,
    anchor_frame: int | None = None,
    normal_scanouts: int = 2,
    sectors_per_scanout_numerator: int = (
        DEFAULT_SECTORS_PER_SCANOUT_NUMERATOR
    ),
    sectors_per_scanout_denominator: int = (
        DEFAULT_SECTORS_PER_SCANOUT_DENOMINATOR
    ),
    use_observed_delay: bool = False,
) -> list[ReplayRow]:
    """Replay schedule-only or HUD-measured producer lead into APPLY."""

    arrays = (
        block_lengths,
        control_sectors,
        payload_sectors,
        physical_sectors,
        rate_sectors,
    )
    if any(item.ndim != 1 for item in arrays):
        raise ValueError("schedule traces must be one-dimensional")
    if len({len(item) for item in arrays}) != 1:
        raise ValueError("schedule traces must have equal lengths")
    if sectors_per_scanout_numerator <= 0:
        raise ValueError("sectors per scanout numerator must be positive")
    if sectors_per_scanout_denominator <= 0:
        raise ValueError("sectors per scanout denominator must be positive")

    lead, peak = lead_trace(physical_sectors, rate_sectors)
    conservative_ahead = peak - lead
    kinds = sector_kinds(
        physical_sectors, control_sectors, payload_sectors
    )
    slot_end = np.cumsum(physical_sectors, dtype=np.int64)
    timed_blocks = block_lengths.copy()
    if len(timed_blocks):
        timed_blocks[0] = 0
    consumed = np.cumsum(timed_blocks, dtype=np.int64)

    extra_scanouts: dict[int, int] = {}
    if hud is not None:
        if anchor_frame is None:
            first_positive = first_positive_frame(lead)
            anchor_frame = max(0, (first_positive or 1) - 1)
        extra_scanouts = cumulative_extra_scanouts(
            hud,
            anchor_frame=anchor_frame,
            normal_scanouts=normal_scanouts,
        )

    result = []
    producer_cursor = 0
    delivered_control = 0
    for frame in range(len(block_lengths)):
        observed_extra = extra_scanouts.get(frame)
        observed_cd = (
            max(
                0,
                observed_extra * sectors_per_scanout_numerator
                // sectors_per_scanout_denominator,
            )
            if observed_extra is not None
            else None
        )
        observed_ahead = (
            max(0, observed_cd - int(lead[frame]))
            if observed_cd is not None
            else None
        )
        ahead = (
            observed_ahead
            if use_observed_delay and observed_ahead is not None
            else int(conservative_ahead[frame])
        )
        target_cursor = min(
            len(kinds),
            int(slot_end[frame]) + max(0, int(ahead)),
        )
        (
            producer_cursor,
            delivered_control,
            occupancy,
            next_kind,
            predicted_blocked,
        ) = advance_apply_producer(
            producer_cursor=producer_cursor,
            target_cursor=target_cursor,
            delivered_control_sectors=delivered_control,
            consumed_control_bytes=int(consumed[frame]),
            kinds=kinds,
        )
        # HUD capture is quantized to whole emulator scanouts, while CDC_STAT
        # can expose the next sector anywhere inside that interval. Treat a
        # guarded control sector already at the cursor as pending even when
        # the integer target lands exactly on its boundary. Recovery after the
        # first S changes phase and is outside this pre-failure replay.
        predicted_blocked = int(
            predicted_blocked
            or (
                occupancy >= APPLY_GUARD_BYTES
                and next_kind == "control"
            )
        )
        hud_row = hud.get(frame) if hud is not None else None
        result.append(
            ReplayRow(
                frame=frame,
                physical_sectors=int(physical_sectors[frame]),
                rate_sectors=int(rate_sectors[frame]),
                rate_lead=int(lead[frame]),
                peak_rate_lead=int(peak[frame]),
                conservative_ahead_sectors=int(
                    conservative_ahead[frame]
                ),
                extra_scanouts=observed_extra,
                extra_cd_sectors=observed_cd,
                observed_ahead_sectors=observed_ahead,
                producer_sector_cursor=producer_cursor,
                delivered_control_sectors=delivered_control,
                consumed_control_bytes=int(consumed[frame]),
                apply_occupancy_bytes=occupancy,
                next_sector_kind=next_kind,
                predicted_apply_blocked=predicted_blocked,
                observed_apply_blocked=(
                    hud_row.apply_backpressure
                    if hud_row is not None
                    else None
                ),
                observed_slip=(
                    hud_row.sector_slip if hud_row is not None else None
                ),
            )
        )
    return result


def write_replay(path: Path, rows: list[ReplayRow]) -> None:
    fields = list(ReplayRow.__dataclass_fields__)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: (
                        "" if getattr(row, field) is None
                        else getattr(row, field)
                    )
                    for field in fields
                }
            )


def first_matching_frame(
    rows: list[ReplayRow], field: str
) -> int | None:
    return next(
        (
            row.frame
            for row in rows
            if getattr(row, field)
        ),
        None,
    )


def first_slip_transition(rows: list[ReplayRow]) -> int | None:
    previous = 0
    for row in rows:
        if row.observed_slip is None:
            continue
        if row.observed_slip != previous:
            return row.frame
        previous = row.observed_slip
    return None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Replay physical BODY rate debt and optional HUD cadence "
            "against the Sub APPLY guard"
        )
    )
    parser.add_argument("decisions", type=Path)
    parser.add_argument("--hud-tsv", type=Path)
    parser.add_argument("--output-tsv", type=Path, required=True)
    parser.add_argument("--anchor-frame", type=int)
    parser.add_argument("--normal-scanouts", type=int)
    parser.add_argument(
        "--schedule-only",
        action="store_true",
        help="use conservative peak-minus-current sector debt",
    )
    args = parser.parse_args()

    decisions, schedule = load_schedule(args.decisions)
    block_lengths = np.asarray(schedule["block_lengths"], np.int64)
    control_sectors = np.asarray(schedule["control_sectors"], np.int64)
    payload_sectors = np.asarray(schedule["payload_sectors"], np.int64)
    physical_bytes = np.asarray(
        schedule["body_physical_bytes"], np.int64
    )
    if np.any(physical_bytes % SECTOR_BYTES):
        raise ValueError("BODY physical byte trace is not sector-aligned")
    physical_sectors = physical_bytes // SECTOR_BYTES
    fps = decisions["fps_str"]
    rate_sectors = stream_schedule.rate_deltas(
        len(block_lengths), fps
    )
    hud = read_hud(args.hud_tsv) if args.hud_tsv else None
    normal_scanouts = (
        args.normal_scanouts
        if args.normal_scanouts is not None
        else max(1, round(60.0 / float(decisions["fps"])))
    )
    rows = build_replay(
        block_lengths=block_lengths,
        control_sectors=control_sectors,
        payload_sectors=payload_sectors,
        physical_sectors=physical_sectors,
        rate_sectors=rate_sectors,
        hud=hud,
        anchor_frame=args.anchor_frame,
        normal_scanouts=normal_scanouts,
        use_observed_delay=bool(hud is not None and not args.schedule_only),
    )
    write_replay(args.output_tsv, rows)

    lead_peak = max(row.peak_rate_lead for row in rows)
    predicted = first_matching_frame(
        rows, "predicted_apply_blocked"
    )
    observed = first_matching_frame(
        rows, "observed_apply_blocked"
    )
    first_slip = first_slip_transition(rows)
    maximum_occupancy = max(row.apply_occupancy_bytes for row in rows)
    print(
        "APPLY replay: "
        f"rate_lead_peak={lead_peak} sectors "
        f"apply_peak={maximum_occupancy}B "
        f"predicted_B={predicted} "
        f"observed_B={observed} "
        f"first_S={first_slip}"
    )
    print(f"wrote {args.output_tsv}")


if __name__ == "__main__":
    main()
