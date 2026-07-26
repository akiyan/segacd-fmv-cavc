"""Construct encoder limits from the physical BODY and PrgBuf geometry.

The image encoder must not first create an unconstrained workload and ask the
packer whether it happened to fit.  This module fixes a conservative control
sector route before image decisions, then projects predicted Prg demand onto
the payload that can cross that route with the real prebuffer capacity.

The joint planner derives a per-frame cold/run ceiling from the Prg payload
that can actually be delivered plus the planned boot-preloaded sources, then
repeats that inexpensive array calculation to a fixed point.  The image
encoder obeys both resulting ceilings.  Final updates, runs, and Prg loads may
therefore only shrink the already-proven envelope while useful payload
replaces former pad.
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
    cold_pattern_limits: np.ndarray
    control_block_limits: np.ndarray
    control_sectors: np.ndarray
    payload_sector_capacity: np.ndarray
    deadline_payload_supply_patterns: np.ndarray
    schedule: dict
    planning_passes: int = 1


@dataclass(frozen=True)
class SharedSectorFrameLimit:
    """Limits known before one frame's image decisions are committed."""

    prg_patterns: int
    cold_patterns: int
    control_block_bytes: int
    cumulative_prg_patterns: int
    cumulative_control_bytes: int
    cumulative_useful_sectors: int


@dataclass(frozen=True)
class SharedSectorPlan:
    """Frozen trace from the one-pass shared control/payload sector planner."""

    desired_prg_patterns: np.ndarray
    prg_pattern_limits: np.ndarray
    shortfall_patterns: np.ndarray
    cold_pattern_limits: np.ndarray
    control_block_limits: np.ndarray
    cumulative_prg_pattern_limits: np.ndarray
    cumulative_control_byte_limits: np.ndarray
    cumulative_useful_sector_capacity: np.ndarray
    realized_prg_patterns: np.ndarray
    realized_cold_patterns: np.ndarray
    realized_control_block_bytes: np.ndarray
    planning_passes: int = 1


def timed_body_trace(values, *, name: str = "BODY trace") -> np.ndarray:
    """Return a timed-stream trace with boot-only frame 0 normalized to zero."""

    trace = np.asarray(values, np.int64)
    if trace.ndim != 1:
        raise ValueError(f"{name} must be one-dimensional")
    if np.any(trace < 0):
        raise ValueError(f"{name} must be non-negative")
    trace = trace.copy()
    if len(trace):
        trace[0] = 0
    return trace


def verify_shared_sector_prefix(
        prg_patterns,
        control_block_bytes,
        *,
        prebuffer_capacity_patterns: int,
        frame_sectors: int,
        fps=None,
) -> dict:
    """Prove every timed deadline fits route and cumulative CD-1x capacity.

    Control and Prg payload are independent continuous streams, so each
    cumulative byte count is rounded to whole sectors independently.  At the
    end of BODY slot ``i`` the control stream must cover frames through ``i``
    and the payload stream must cover Prg consumption through ``i + 1``.
    Route entries cap useful sectors per slot.  When ``fps`` is supplied, the
    same prefix must also fit the sectors that a physical CD-1x drive has had
    time to deliver.  A later light slot cannot erase display time already
    lost to an earlier overfull slot.
    """
    prg = timed_body_trace(prg_patterns, name="Prg trace")
    control = timed_body_trace(
        control_block_bytes, name="control trace")
    if control.shape != prg.shape:
        raise ValueError(
            "Prg and control traces must be equal-length vectors")
    if int(frame_sectors) <= 0:
        raise ValueError("frame sector capacity must be positive")
    prebuffer = (
        int(prebuffer_capacity_patterns)
        // stream_schedule.PATTERNS_PER_SECTOR
        * stream_schedule.PATTERNS_PER_SECTOR)
    if prebuffer <= 0:
        raise ValueError("prebuffer must contain a complete sector")

    cumulative_prg = np.cumsum(prg, dtype=np.int64)
    cumulative_control = np.cumsum(control, dtype=np.int64)
    payload_deadline = np.empty(len(prg), np.int64)
    if len(prg):
        payload_deadline[:-1] = cumulative_prg[1:]
        payload_deadline[-1] = cumulative_prg[-1]
    payload_body_patterns = np.maximum(
        payload_deadline - prebuffer, 0)
    payload_sectors = (
        payload_body_patterns + stream_schedule.PATTERNS_PER_SECTOR - 1
    ) // stream_schedule.PATTERNS_PER_SECTOR
    control_sectors = (
        cumulative_control + stream_schedule.SECTOR_BYTES - 1
    ) // stream_schedule.SECTOR_BYTES
    route_capacity = (
        np.arange(len(prg), dtype=np.int64) * int(frame_sectors))
    if fps is None:
        cadence_capacity = route_capacity.copy()
    else:
        cadence_capacity = np.cumsum(
            stream_schedule.rate_deltas(len(prg), fps),
            dtype=np.int64,
        )
    capacity = np.minimum(route_capacity, cadence_capacity)
    margin = capacity - control_sectors - payload_sectors
    bad = np.flatnonzero((np.arange(len(prg)) > 0) & (margin < 0))
    if bad.size:
        frame = int(bad[0])
        raise stream_schedule.ScheduleError(
            f"shared BODY prefix exceeds slot {frame}: "
            f"control={int(control_sectors[frame])} sectors, "
            f"payload={int(payload_sectors[frame])} sectors, "
            f"capacity={int(capacity[frame])} sectors",
            kind="shared_sector_prefix",
            details={
                "failure_frame": frame,
                "control_sectors": int(control_sectors[frame]),
                "payload_sectors": int(payload_sectors[frame]),
                "capacity_sectors": int(capacity[frame]),
                "route_capacity_sectors": int(route_capacity[frame]),
                "cadence_capacity_sectors": int(
                    cadence_capacity[frame]),
            },
        )
    return {
        "cumulative_prg_patterns": cumulative_prg,
        "cumulative_control_bytes": cumulative_control,
        "deadline_payload_sectors": payload_sectors,
        "deadline_control_sectors": control_sectors,
        "cumulative_useful_sector_capacity": capacity,
        "cumulative_route_sector_capacity": route_capacity,
        "cumulative_cadence_sector_capacity": cadence_capacity,
        "margin_sectors": margin,
    }


class SharedSectorPlanner:
    """Allocate control and Prg capacity online from one physical sector pool.

    A frame's Prg deadline depends only on control bytes already finalized by
    the preceding frame.  Conversely, the current frame's control deadline
    can be bounded using the current Prg ceiling.  This lets the encoder return
    exact run-descriptor savings to the *next* frame before that frame makes
    image decisions, without a movie retry or a pack-time capacity surprise.
    """

    def __init__(
            self, frame_count: int, *,
            max_prg_patterns: int,
            max_cold_patterns: int,
            prebuffer_capacity_patterns: int,
            frame_sectors: int,
            fps=None,
            ring_capacity_patterns: int | None = None,
            maximum_control_block_bytes=None,
            fill: bool = True):
        count = int(frame_count)
        if count <= 0:
            raise ValueError("shared sector planner needs at least one frame")
        if int(max_prg_patterns) < 0 or int(max_cold_patterns) < 0:
            raise ValueError("shared sector limits must be non-negative")
        if int(frame_sectors) <= 0:
            raise ValueError("frame sector capacity must be positive")
        self.frame_count = count
        self.max_prg_patterns = int(max_prg_patterns)
        self.max_cold_patterns = int(max_cold_patterns)
        self.prebuffer_patterns = (
            int(prebuffer_capacity_patterns)
            // stream_schedule.PATTERNS_PER_SECTOR
            * stream_schedule.PATTERNS_PER_SECTOR)
        if self.prebuffer_patterns <= 0:
            raise ValueError("prebuffer must contain a complete sector")
        self.frame_sectors = int(frame_sectors)
        self.fps = fps
        self.ring_capacity_patterns = (
            None if ring_capacity_patterns is None
            else int(ring_capacity_patterns))
        if self.ring_capacity_patterns is not None and self.fps is None:
            raise ValueError(
                "fps is required when ring capacity is supplied")
        if (self.ring_capacity_patterns is not None
                and self.ring_capacity_patterns < self.prebuffer_patterns):
            raise ValueError(
                "ring capacity is smaller than the prebuffer")
        route_capacity = (
            np.arange(count, dtype=np.int64) * self.frame_sectors)
        if self.fps is None:
            cadence_capacity = route_capacity
        else:
            cadence_capacity = np.cumsum(
                stream_schedule.rate_deltas(count, self.fps),
                dtype=np.int64,
            )
        self.useful_sector_capacity = np.minimum(
            route_capacity, cadence_capacity)
        if maximum_control_block_bytes is None:
            self.maximum_control = None
        else:
            self.maximum_control = _frame_vector(
                maximum_control_block_bytes,
                count,
                name="maximum control block bytes",
            )
        self.fill = bool(fill)
        self._next_frame = 0
        self._cumulative_prg = 0
        self._cumulative_control = 0
        self._open_limit: SharedSectorFrameLimit | None = None
        self.prg_limits = np.zeros(count, np.int64)
        self.cold_limits = np.zeros(count, np.int64)
        self.control_limits = np.zeros(count, np.int64)
        self.cumulative_prg_limits = np.zeros(count, np.int64)
        self.cumulative_control_limits = np.zeros(count, np.int64)
        self.realized_prg = np.zeros(count, np.int64)
        self.realized_cold = np.zeros(count, np.int64)
        self.realized_control = np.zeros(count, np.int64)

    def _control_limit_for_prg(
            self, frame: int, prg_patterns: int) -> int:
        maximum_prg = self._cumulative_prg + int(prg_patterns)
        payload_sectors = (
            max(0, maximum_prg - self.prebuffer_patterns)
            + stream_schedule.PATTERNS_PER_SECTOR - 1
        ) // stream_schedule.PATTERNS_PER_SECTOR
        current_capacity = int(self.useful_sector_capacity[frame])
        cumulative_control_sectors = max(
            0, current_capacity - payload_sectors)
        cumulative_control_limit = (
            cumulative_control_sectors * stream_schedule.SECTOR_BYTES)
        return max(
            0, cumulative_control_limit - self._cumulative_control)

    def _candidate_schedule(
            self, frame: int, prg_patterns: int,
            control_block_bytes: int) -> dict | None:
        if self.ring_capacity_patterns is None:
            return None
        candidate_prg = self.realized_prg[:frame + 1].copy()
        candidate_control = self.realized_control[:frame + 1].copy()
        candidate_prg[frame] = int(prg_patterns)
        candidate_control[frame] = int(control_block_bytes)
        try:
            return stream_schedule.schedule_payload_ring(
                candidate_prg,
                candidate_control,
                fps=self.fps,
                ring_capacity_patterns=self.ring_capacity_patterns,
                prebuffer_capacity_patterns=self.prebuffer_patterns,
                frame_sectors=self.frame_sectors,
                fill=self.fill,
                control_sector_envelope=None,
            )
        except stream_schedule.ScheduleError:
            return None

    def _forward_ring_candidate_fits(
            self, frame: int, prg_patterns: int,
            control_block_limit: int) -> bool:
        if self.ring_capacity_patterns is None:
            return True
        worst_control = int(control_block_limit)
        if self.maximum_control is not None:
            worst_control = min(
                worst_control, int(self.maximum_control[frame]))
        schedule = self._candidate_schedule(
            frame, prg_patterns, worst_control)
        if schedule is None:
            return False
        return bool(
            schedule["feasible"]
            and schedule["over"] == 0
            and schedule["under"] == 0
            and schedule["ready_min"] >= 0
            and schedule["ctrl_min"] >= 0
            and schedule["ring_peak"] <= self.ring_capacity_patterns
            and schedule["rate_lead_peak"] == 0
        )

    def begin_frame(self, frame: int) -> SharedSectorFrameLimit:
        frame = int(frame)
        if frame != self._next_frame or self._open_limit is not None:
            raise ValueError(
                f"shared sector planner expected frame {self._next_frame}, "
                f"got {frame}")
        if frame == 0:
            limit = SharedSectorFrameLimit(0, 0, 0, 0, 0, 0)
        else:
            previous_capacity = int(
                self.useful_sector_capacity[frame - 1])
            previous_control_sectors = (
                self._cumulative_control + stream_schedule.SECTOR_BYTES - 1
            ) // stream_schedule.SECTOR_BYTES
            payload_capacity = max(
                0, previous_capacity - previous_control_sectors)
            cumulative_prg_limit = (
                self.prebuffer_patterns
                + payload_capacity * stream_schedule.PATTERNS_PER_SECTOR)
            prg_limit = min(
                self.max_prg_patterns,
                max(0, cumulative_prg_limit - self._cumulative_prg),
            )

            if self.ring_capacity_patterns is not None and prg_limit:
                low = 0
                high = int(prg_limit)
                while low < high:
                    trial = (low + high + 1) // 2
                    trial_control_limit = self._control_limit_for_prg(
                        frame, trial)
                    if self._forward_ring_candidate_fits(
                            frame, trial, trial_control_limit):
                        low = trial
                    else:
                        high = trial - 1
                prg_limit = low

            control_limit = self._control_limit_for_prg(
                frame, prg_limit)
            if self.maximum_control is not None:
                control_limit = min(
                    control_limit, int(self.maximum_control[frame]))
            cumulative_control_limit = (
                self._cumulative_control + control_limit)
            current_capacity = int(
                self.useful_sector_capacity[frame])
            limit = SharedSectorFrameLimit(
                int(prg_limit),
                int(self.max_cold_patterns),
                int(control_limit),
                int(cumulative_prg_limit),
                int(cumulative_control_limit),
                int(current_capacity),
            )
        self.prg_limits[frame] = limit.prg_patterns
        self.cold_limits[frame] = limit.cold_patterns
        self.control_limits[frame] = limit.control_block_bytes
        self.cumulative_prg_limits[frame] = limit.cumulative_prg_patterns
        self.cumulative_control_limits[frame] = (
            limit.cumulative_control_bytes)
        self._open_limit = limit
        return limit

    def commit_frame(
            self, frame: int, *,
            prg_patterns: int,
            cold_patterns: int,
            control_block_bytes: int) -> None:
        frame = int(frame)
        if frame != self._next_frame or self._open_limit is None:
            raise ValueError(
                f"shared sector planner has no open frame {frame}")
        limit = self._open_limit
        prg = int(prg_patterns)
        cold = int(cold_patterns)
        control = int(control_block_bytes)
        if prg < 0 or cold < 0 or control < 0:
            raise ValueError("realized shared sector work must be non-negative")
        if frame == 0:
            prg = cold = control = 0
        if prg > limit.prg_patterns:
            raise stream_schedule.ScheduleError(
                f"frame {frame} Prg work {prg} exceeds shared-sector "
                f"limit {limit.prg_patterns}",
                kind="shared_sector_prg",
                details={"failure_frame": frame},
            )
        if cold > limit.cold_patterns:
            raise stream_schedule.ScheduleError(
                f"frame {frame} cold work {cold} exceeds shared-sector "
                f"limit {limit.cold_patterns}",
                kind="shared_sector_cold",
                details={"failure_frame": frame},
            )
        if control > limit.control_block_bytes:
            raise stream_schedule.ScheduleError(
                f"frame {frame} control block {control}B exceeds "
                f"shared-sector limit {limit.control_block_bytes}B",
                kind="shared_sector_control",
                details={"failure_frame": frame},
            )
        exact_schedule = self._candidate_schedule(frame, prg, control)
        if (
                self.ring_capacity_patterns is not None
                and (
                    exact_schedule is None
                    or not exact_schedule["feasible"]
                )):
            raise stream_schedule.ScheduleError(
                f"frame {frame} exact shared-sector route exceeds "
                "fixed-cadence CD time",
                kind="shared_sector_cadence",
                details={
                    "failure_frame": frame,
                    "rate_lead_peak": int(
                        exact_schedule["rate_lead_peak"]
                        if exact_schedule is not None else -1),
                    "rate_lead_end": int(
                        exact_schedule["rate_lead_end"]
                        if exact_schedule is not None else -1),
                },
            )
        self.realized_prg[frame] = prg
        self.realized_cold[frame] = cold
        self.realized_control[frame] = control
        self._cumulative_prg += prg
        self._cumulative_control += control
        verify_shared_sector_prefix(
            self.realized_prg[:frame + 1],
            self.realized_control[:frame + 1],
            prebuffer_capacity_patterns=self.prebuffer_patterns,
            frame_sectors=self.frame_sectors,
            fps=self.fps,
        )
        self._open_limit = None
        self._next_frame += 1

    def finish(self, desired_prg_patterns) -> SharedSectorPlan:
        if self._open_limit is not None or self._next_frame != self.frame_count:
            raise ValueError("shared sector planner is not complete")
        desired = np.asarray(desired_prg_patterns, np.int64)
        if desired.shape != (self.frame_count,):
            raise ValueError("desired Prg trace length differs")
        if np.any(desired < 0):
            raise ValueError("desired Prg trace must be non-negative")
        desired = desired.copy()
        desired[0] = 0
        verify_shared_sector_prefix(
            self.realized_prg,
            self.realized_control,
            prebuffer_capacity_patterns=self.prebuffer_patterns,
            frame_sectors=self.frame_sectors,
            fps=self.fps,
        )
        return SharedSectorPlan(
            desired_prg_patterns=desired,
            prg_pattern_limits=self.prg_limits.copy(),
            shortfall_patterns=np.maximum(
                desired - self.prg_limits, 0),
            cold_pattern_limits=self.cold_limits.copy(),
            control_block_limits=self.control_limits.copy(),
            cumulative_prg_pattern_limits=(
                self.cumulative_prg_limits.copy()),
            cumulative_control_byte_limits=(
                self.cumulative_control_limits.copy()),
            cumulative_useful_sector_capacity=(
                self.useful_sector_capacity.copy()),
            realized_prg_patterns=self.realized_prg.copy(),
            realized_cold_patterns=self.realized_cold.copy(),
            realized_control_block_bytes=self.realized_control.copy(),
        )


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
        cold_pattern_limits=runs,
        control_block_limits=control_limits,
        control_sectors=control_sectors,
        payload_sector_capacity=payload_capacity,
        deadline_payload_supply_patterns=deadline_supply,
        schedule=schedule,
    )


def build_joint_plan(
    desired_prg_patterns,
    *,
    max_preloaded_patterns,
    fps,
    cells: int,
    audio_frame_bytes: int,
    max_updates: int | Sequence[int] | np.ndarray,
    max_cold: int | Sequence[int] | np.ndarray,
    ring_capacity_patterns: int,
    prebuffer_capacity_patterns: int,
    frame_sectors: int,
    fill: bool = True,
    max_passes: int = 32,
) -> PhysicalBudgetPlan:
    """Jointly derive cold/run and Prg payload limits before image decisions.

    Every source-aware run contains at least one cold pattern. Once the image
    encoder is constrained to ``cold_pattern_limits``, that same vector is a
    strict run-count bound even with identity physical slots. A frame needs no
    more cold patterns than its accepted Prg payload plus the predicted
    WordBuf/DicBuf credits without making those sources compete. Rebuilding
    the sector envelope from that bound returns former descriptor reservation
    to payload while keeping every later stage monotone.

    A sector-rounding cycle is resolved conservatively by retaining the
    elementwise maximum of the cycle. Increasing a run ceiling cannot increase
    accepted payload, so one final raise makes that fallback self-consistent.
    """
    desired = np.asarray(desired_prg_patterns, np.int64)
    if desired.ndim != 1:
        raise ValueError("desired Prg patterns must be one-dimensional")
    frame_count = len(desired)
    preload = _frame_vector(
        max_preloaded_patterns,
        frame_count,
        name="maximum preloaded patterns",
    )
    cold_ceiling = _frame_vector(
        max_cold,
        frame_count,
        name="maximum cold patterns",
    )
    if max_passes <= 0:
        raise ValueError("maximum planning passes must be positive")

    cold_limits = cold_ceiling.copy()
    seen: list[np.ndarray] = []
    plan: PhysicalBudgetPlan | None = None
    passes = 0
    for passes in range(1, int(max_passes) + 1):
        plan = build_plan(
            desired,
            fps=fps,
            cells=cells,
            audio_frame_bytes=audio_frame_bytes,
            max_updates=max_updates,
            max_runs=cold_limits,
            ring_capacity_patterns=ring_capacity_patterns,
            prebuffer_capacity_patterns=prebuffer_capacity_patterns,
            frame_sectors=frame_sectors,
            fill=fill,
        )
        next_limits = np.minimum(
            cold_ceiling,
            plan.prg_pattern_limits + preload,
        )
        if frame_count:
            next_limits[0] = 0
        if np.array_equal(next_limits, cold_limits):
            break
        cycle_start = next(
            (index for index, previous in enumerate(seen)
             if np.array_equal(previous, next_limits)),
            None,
        )
        if cycle_start is not None:
            cycle = seen[cycle_start:] + [cold_limits, next_limits]
            cold_limits = np.maximum.reduce(cycle)
            plan = build_plan(
                desired,
                fps=fps,
                cells=cells,
                audio_frame_bytes=audio_frame_bytes,
                max_updates=max_updates,
                max_runs=cold_limits,
                ring_capacity_patterns=ring_capacity_patterns,
                prebuffer_capacity_patterns=prebuffer_capacity_patterns,
                frame_sectors=frame_sectors,
                fill=fill,
            )
            required = np.minimum(
                cold_ceiling,
                plan.prg_pattern_limits + preload,
            )
            if frame_count:
                required[0] = 0
            if np.any(required > cold_limits):
                cold_limits = np.maximum(cold_limits, required)
                plan = build_plan(
                    desired,
                    fps=fps,
                    cells=cells,
                    audio_frame_bytes=audio_frame_bytes,
                    max_updates=max_updates,
                    max_runs=cold_limits,
                    ring_capacity_patterns=ring_capacity_patterns,
                    prebuffer_capacity_patterns=prebuffer_capacity_patterns,
                    frame_sectors=frame_sectors,
                    fill=fill,
                )
                passes += 1
            break
        seen.append(cold_limits.copy())
        cold_limits = next_limits
    else:
        raise RuntimeError("joint physical budget planning did not converge")

    assert plan is not None
    required = np.minimum(
        cold_ceiling,
        plan.prg_pattern_limits + preload,
    )
    if frame_count:
        required[0] = 0
    if np.any(required > plan.cold_pattern_limits):
        frame = int(np.flatnonzero(
            required > plan.cold_pattern_limits)[0])
        raise AssertionError(
            f"joint physical budget is not self-consistent at frame {frame}: "
            f"cold limit={int(plan.cold_pattern_limits[frame])}, "
            f"Prg+preload={int(required[frame])}")

    return PhysicalBudgetPlan(
        desired_prg_patterns=plan.desired_prg_patterns,
        prg_pattern_limits=plan.prg_pattern_limits,
        shortfall_patterns=plan.shortfall_patterns,
        reserve_patterns=plan.reserve_patterns,
        cold_pattern_limits=plan.cold_pattern_limits,
        control_block_limits=plan.control_block_limits,
        control_sectors=plan.control_sectors,
        payload_sector_capacity=plan.payload_sector_capacity,
        deadline_payload_supply_patterns=(
            plan.deadline_payload_supply_patterns),
        schedule=plan.schedule,
        planning_passes=passes,
    )
