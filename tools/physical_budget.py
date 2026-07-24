"""Construct encoder limits from the physical BODY and PrgBuf geometry.

The image encoder must not first create an unconstrained workload and ask the
packer whether it happened to fit.  This module fixes a conservative control
sector route before image decisions, then projects predicted Prg demand onto
the payload that can cross that route with the real prebuffer capacity.

The first implementation deliberately uses one run descriptor per possible
cold pattern.  It does not reclaim locality savings.  That keeps the identity
slot pipeline monotone: final updates, runs, and Prg loads may only be smaller
than the already-proven envelope.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

import stream_schedule
import upgrade_planner


@dataclass(frozen=True)
class PhysicalBudgetPlan:
    """A construction envelope that later encoder stages may only shrink."""

    desired_prg_patterns: np.ndarray
    prg_pattern_limits: np.ndarray
    shortfall_patterns: np.ndarray
    reserve_patterns: np.ndarray
    control_block_limits: np.ndarray
    control_sectors: np.ndarray
    payload_sector_capacity: np.ndarray
    deadline_payload_supply_patterns: np.ndarray
    schedule: dict


def _frame_vector(
        value: int | Sequence[int] | np.ndarray,
        frame_count: int,
        *,
        name: str,
) -> np.ndarray:
    if np.isscalar(value):
        result = np.full(frame_count, int(value), np.int64)
    else:
        result = np.asarray(value, np.int64)
        if result.shape != (frame_count,):
            raise ValueError(f"{name} must be scalar or match the frame count")
        result = result.copy()
    if np.any(result < 0):
        raise ValueError(f"{name} must be non-negative")
    if frame_count:
        result[0] = 0
    return result


def build_plan(
        desired_prg_patterns,
        *,
        fps,
        cells: int,
        audio_frame_bytes: int,
        max_updates: int | Sequence[int] | np.ndarray,
        max_runs: int | Sequence[int] | np.ndarray,
        ring_capacity_patterns: int,
        prebuffer_capacity_patterns: int,
        frame_sectors: int,
        fill: bool = True,
) -> PhysicalBudgetPlan:
    """Return per-frame Prg limits whose complete envelope is schedulable.

    ``max_updates`` and ``max_runs`` describe control-data limits, not expected
    averages.  The returned control sectors are frozen as physical capacity;
    a shorter final control stream is padded rather than allowed to move a
    sector boundary into the payload route.

    Payload delivered in BODY slot ``i-1`` is credited to frame ``i``.  The
    balanced reserve planner therefore works directly in 32-byte patterns with
    the same one-frame readiness margin as :func:`schedule_payload_ring`.
    """
    desired = np.asarray(desired_prg_patterns, np.int64)
    if desired.ndim != 1:
        raise ValueError("desired Prg patterns must be one-dimensional")
    if np.any(desired < 0):
        raise ValueError("desired Prg patterns must be non-negative")
    frame_count = len(desired)
    updates = _frame_vector(
        max_updates, frame_count, name="maximum updates")
    runs = _frame_vector(max_runs, frame_count, name="maximum runs")
    desired = desired.copy()
    if frame_count:
        desired[0] = 0

    control_limits = stream_schedule.control_block_lengths(
        updates,
        runs,
        cells=int(cells),
        audio_frame_bytes=int(audio_frame_bytes),
    )
    if frame_count:
        control_limits[0] = 0
    control_sectors = stream_schedule.control_sector_schedule(control_limits)
    if np.any(control_sectors > int(frame_sectors)):
        frame = int(np.flatnonzero(
            control_sectors > int(frame_sectors))[0])
        raise stream_schedule.ScheduleError(
            f"physical control envelope exceeds slot {frame}: "
            f"{int(control_sectors[frame])} > {int(frame_sectors)} sectors",
            kind="control_envelope",
            details={
                "failure_frame": frame,
                "control_sectors": int(control_sectors[frame]),
                "frame_sectors": int(frame_sectors),
            },
        )

    payload_capacity = np.maximum(
        int(frame_sectors) - control_sectors, 0)
    # Frame zero is in HEADER.DAT.  The strict player proof requires frame i
    # payload to have arrived no later than slot i-1.
    deadline_supply = np.zeros(frame_count, np.int64)
    if frame_count > 2:
        deadline_supply[2:] = (
            payload_capacity[1:-1]
            * stream_schedule.PATTERNS_PER_SECTOR)

    prebuffer_patterns = (
        int(prebuffer_capacity_patterns)
        // stream_schedule.PATTERNS_PER_SECTOR
        * stream_schedule.PATTERNS_PER_SECTOR)
    if prebuffer_patterns <= 0:
        raise ValueError("prebuffer capacity must contain a complete sector")
    if int(ring_capacity_patterns) < prebuffer_patterns:
        raise ValueError(
            "physical ring capacity is smaller than the prebuffer")

    balanced = upgrade_planner.build_balanced_reserve_plan(
        desired,
        deadline_supply,
        prebuffer_patterns,
    )
    limits = np.asarray(balanced.planned_demand, np.int64)
    schedule = stream_schedule.schedule_payload_ring(
        limits,
        control_limits,
        fps=fps,
        ring_capacity_patterns=int(ring_capacity_patterns),
        prebuffer_capacity_patterns=int(prebuffer_capacity_patterns),
        frame_sectors=int(frame_sectors),
        fill=bool(fill),
        control_sector_envelope=control_sectors,
    )
    if not schedule["feasible"]:
        raise AssertionError(
            "physical budget planner produced an infeasible envelope")

    return PhysicalBudgetPlan(
        desired_prg_patterns=desired,
        prg_pattern_limits=limits,
        shortfall_patterns=np.asarray(balanced.shortfall, np.int64),
        reserve_patterns=np.asarray(balanced.reserve, np.int64),
        control_block_limits=control_limits,
        control_sectors=control_sectors,
        payload_sector_capacity=payload_capacity,
        deadline_payload_supply_patterns=deadline_supply,
        schedule=schedule,
    )
