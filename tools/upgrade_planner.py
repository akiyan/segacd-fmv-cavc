"""Whole-movie reserve planning for encoder quality allocation.

The virtual quality budget is deliberately separate from the physical PrgBuf
scheduler in :mod:`stream_schedule`.

This module replaces fixed occupancy percentages with a reserve curve derived
from the already-quantized movie.  The final reserve is zero by definition;
working backwards raises the reserve only where future exact-update demand is
larger than the per-frame supply.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from tile_alloc import TileAllocator


@dataclass(frozen=True)
class DemandPrediction:
    """Exact/protected byte demand plus their new-pattern counts."""

    exact_bytes: np.ndarray
    protected_bytes: np.ndarray
    exact_cold: np.ndarray
    protected_cold: np.ndarray
    # Exact packed-pattern keys encountered by the predictive allocator.  The
    # sequence is deterministic; callers that only need byte demand may leave
    # these empty for compatibility with older tests/logs.
    cold_keys: tuple[tuple[bytes, ...], ...] = ()
    protected_keys: tuple[tuple[bytes, ...], ...] = ()
    # Logical VRAM slots assigned to the exact cold keys above.  The encoder
    # uses this dry-run trace only to choose a movie-wide physical slot
    # permutation; logical residency and cold/reuse decisions stay unchanged.
    cold_slots: tuple[tuple[int, ...], ...] = ()


@dataclass(frozen=True)
class ReservePlan:
    """Capacity-feasible demand and the reserve needed to serve it."""

    reserve: np.ndarray
    planned_demand: np.ndarray
    shortfall: np.ndarray


def select_peak_priority_frames(
    trigger_frames: Sequence[bool] | np.ndarray,
    risk_scores: Sequence[int] | np.ndarray,
    search_frames: int,
) -> np.ndarray:
    """Select at most one highest-risk frame following each trigger.

    ``search_frames`` includes the trigger frame. Zero disables selection.
    A search stops before the next trigger, and a region whose maximum score
    is zero selects no frame.
    """

    triggers = np.asarray(trigger_frames, dtype=bool)
    scores = np.asarray(risk_scores, dtype=np.int64)
    if triggers.ndim != 1:
        raise ValueError("trigger frames must be one-dimensional")
    if scores.shape != triggers.shape:
        raise ValueError("risk scores must match trigger frames")
    if np.any(scores < 0):
        raise ValueError("risk scores must be non-negative")
    if isinstance(search_frames, bool) or not isinstance(
            search_frames, (int, np.integer)):
        raise ValueError("search frames must be an integer")
    if search_frames < 0:
        raise ValueError("search frames must be non-negative")
    priority = np.zeros(triggers.shape, bool)
    trigger_indices = np.flatnonzero(triggers)
    for position, trigger in enumerate(trigger_indices):
        next_trigger = (
            int(trigger_indices[position + 1])
            if position + 1 < len(trigger_indices) else len(priority)
        )
        end = min(
            int(trigger) + int(search_frames),
            next_trigger,
            len(priority),
        )
        if end <= trigger:
            continue
        relative = int(np.argmax(scores[int(trigger):end]))
        selected = int(trigger) + relative
        if int(scores[selected]) > 0:
            priority[selected] = True
    return priority


def relax_reserve_in_priority_windows(
    reserve: Sequence[int] | np.ndarray,
    priority_frames: Sequence[bool] | np.ndarray,
) -> np.ndarray:
    """Return a reserve curve with priority-window targets lowered to zero."""

    reserve_arr = np.asarray(reserve, dtype=np.int64)
    priority_arr = np.asarray(priority_frames, dtype=bool)
    if reserve_arr.ndim != 1:
        raise ValueError("reserve must be one-dimensional")
    if priority_arr.shape != reserve_arr.shape:
        raise ValueError("priority frames must match reserve")
    if np.any(reserve_arr < 0):
        raise ValueError("reserve must be non-negative")
    effective = reserve_arr.copy()
    effective[priority_arr] = 0
    return effective


def predict_update_demands(
    pattern_frames: Sequence[np.ndarray],
    palette_frames: Sequence[np.ndarray],
    *,
    vram_tiles: int,
    name_bytes: int = 2,
    pattern_bytes: int = 32,
    max_cold: int = 0,
    protected_frames: Sequence[np.ndarray] | None = None,
    forced_update_frames: Sequence[bool] | None = None,
    boot_prefetch_requests: Sequence[tuple[bytes, int]] = (),
) -> tuple[np.ndarray, np.ndarray]:
    """Estimate exact and protected byte demand in one VRAM dry run.

    The dry run follows the exact quantized target rather than the encoder's
    eventual approximations.  It uses the shared VRAM allocator, so recurring
    patterns cost only a name-table write while newly allocated patterns cost
    both a name-table write and pattern payload.  ``max_cold`` clips demand
    that the hardware could not apply in one frame anyway.

    ``protected_frames`` optionally selects the changes that count toward the
    second, narrower demand trace. ``forced_update_frames`` marks frames whose
    complete name table must be rewritten even when a cell's exact indices and
    palette-line number did not change, such as a CRAM segment switch. The dry
    run still advances through the complete exact target. Frame zero is loaded
    from HEADER.DAT and therefore has zero streaming demand, while still
    seeding the predictive VRAM state.
    """

    prediction = predict_update_demand_details(
        pattern_frames,
        palette_frames,
        vram_tiles=vram_tiles,
        name_bytes=name_bytes,
        pattern_bytes=pattern_bytes,
        max_cold=max_cold,
        protected_frames=protected_frames,
        forced_update_frames=forced_update_frames,
        boot_prefetch_requests=boot_prefetch_requests,
    )
    return prediction.exact_bytes, prediction.protected_bytes


def predict_update_demand_details(
    pattern_frames: Sequence[np.ndarray],
    palette_frames: Sequence[np.ndarray],
    *,
    vram_tiles: int,
    name_bytes: int = 2,
    pattern_bytes: int = 32,
    max_cold: int = 0,
    protected_frames: Sequence[np.ndarray] | None = None,
    forced_update_frames: Sequence[bool] | None = None,
    boot_prefetch_requests: Sequence[tuple[bytes, int]] = (),
) -> DemandPrediction:
    """Return the byte-demand traces and the cold counts behind them."""

    n = len(pattern_frames)
    if len(palette_frames) != n:
        raise ValueError("pattern and palette frame counts differ")
    if protected_frames is not None and len(protected_frames) != n:
        raise ValueError("protected frame count differs")
    if forced_update_frames is not None and len(forced_update_frames) != n:
        raise ValueError("forced-update frame count differs")
    if n == 0:
        empty = np.zeros(0, np.int64)
        return DemandPrediction(
            empty, empty.copy(), empty.copy(), empty.copy(), (), (), ())
    if vram_tiles <= 0:
        raise ValueError("vram_tiles must be positive")
    if name_bytes < 0 or pattern_bytes < 0 or max_cold < 0:
        raise ValueError("byte costs and max_cold must be non-negative")

    first_patterns = np.asarray(pattern_frames[0])
    first_palettes = np.asarray(palette_frames[0])
    if first_patterns.ndim != 2:
        raise ValueError("each pattern frame must have shape (cells, pixels)")
    cells = int(first_patterns.shape[0])
    if first_palettes.shape != (cells,):
        raise ValueError("each palette frame must have shape (cells,)")

    allocator = TileAllocator(cells, vram_tiles, 1)
    previous_keys: list[bytes | None] = [None] * cells
    previous_palettes = np.full(cells, -1, np.int64)
    exact_demand = np.zeros(n, np.int64)
    protected_demand = np.zeros(n, np.int64)
    exact_cold_demand = np.zeros(n, np.int64)
    protected_cold_demand = np.zeros(n, np.int64)
    cold_keys_by_frame: list[tuple[bytes, ...]] = []
    protected_keys_by_frame: list[tuple[bytes, ...]] = []
    cold_slots_by_frame: list[tuple[int, ...]] = []

    for frame_idx in range(n):
        patterns = np.asarray(pattern_frames[frame_idx])
        palettes = np.asarray(palette_frames[frame_idx])
        if patterns.shape != first_patterns.shape:
            raise ValueError("pattern frame shapes differ")
        if palettes.shape != (cells,):
            raise ValueError("palette frame shapes differ")

        keys = [patterns[cell].tobytes() for cell in range(cells)]
        if (
            forced_update_frames is not None
            and bool(forced_update_frames[frame_idx])
        ):
            changed_cells = list(range(cells))
        else:
            changed_cells = [
                cell for cell in range(cells)
                if keys[cell] != previous_keys[cell]
                or int(palettes[cell]) != int(previous_palettes[cell])
            ]
        if protected_frames is None:
            protected = np.ones(cells, bool)
        else:
            protected = np.asarray(protected_frames[frame_idx], dtype=bool)
            if protected.shape != (cells,):
                raise ValueError("each protected frame must have shape (cells,)")
        protected_cells = [cell for cell in changed_cells if protected[cell]]
        # Preserve first-cell order while deduplicating same-frame users.  The
        # allocator needs one physical pattern per key, and the deterministic
        # order later gives dictionary placement a stable tie-break.
        exact_cold_keys = tuple(dict.fromkeys(
            keys[cell] for cell in changed_cells
            if not allocator.is_resident(keys[cell])))
        protected_cold_keys = tuple(dict.fromkeys(
            keys[cell] for cell in protected_cells
            if not allocator.is_resident(keys[cell])))
        placements = allocator.place_frame(
            [(cell, keys[cell]) for cell in changed_cells], frame_idx)
        exact_cold_slots = tuple(
            int(slot) for slot, cold in placements if cold)

        if frame_idx > 0:
            exact_cold = len(exact_cold_keys)
            protected_cold = len(protected_cold_keys)
            if max_cold:
                exact_cold = min(exact_cold, max_cold)
                protected_cold = min(protected_cold, max_cold)
                exact_cold_keys = exact_cold_keys[:max_cold]
                protected_cold_keys = protected_cold_keys[:max_cold]
                exact_cold_slots = exact_cold_slots[:max_cold]
            exact_demand[frame_idx] = (
                len(changed_cells) * name_bytes + exact_cold * pattern_bytes)
            protected_demand[frame_idx] = (
                len(protected_cells) * name_bytes
                + protected_cold * pattern_bytes)
            exact_cold_demand[frame_idx] = exact_cold
            protected_cold_demand[frame_idx] = protected_cold

        cold_keys_by_frame.append(exact_cold_keys if frame_idx > 0 else ())
        protected_keys_by_frame.append(
            protected_cold_keys if frame_idx > 0 else ())
        cold_slots_by_frame.append(
            exact_cold_slots if frame_idx > 0 else ())

        if frame_idx == 0:
            for key, deadline in boot_prefetch_requests:
                result = allocator.prefetch(key, frame_idx, int(deadline))
                if result is None or not result[1]:
                    raise ValueError(
                        "boot-prefetch request does not fit a free VRAM slot")

        for cell in changed_cells:
            previous_keys[cell] = keys[cell]
            previous_palettes[cell] = int(palettes[cell])

    return DemandPrediction(
        exact_demand,
        protected_demand,
        exact_cold_demand,
        protected_cold_demand,
        tuple(cold_keys_by_frame),
        tuple(protected_keys_by_frame),
        tuple(cold_slots_by_frame),
    )


def build_reserve_curve(
    demand: Sequence[int] | np.ndarray,
    supply: int | Sequence[int] | np.ndarray,
    capacity: int,
) -> np.ndarray:
    """Return the minimum quality-budget bytes to retain after each frame.

    ``reserve[-1]`` is always zero.  For every earlier frame, the backwards
    pass retains only the bytes that future demand cannot replenish from its
    own per-frame supply.  Values are clipped to the physical usable capacity;
    demand beyond that cannot be made feasible by optional-upgrade restraint.
    """

    demand_arr = np.asarray(demand, dtype=np.int64)
    if demand_arr.ndim != 1:
        raise ValueError("demand must be one-dimensional")
    if capacity < 0:
        raise ValueError("capacity must be non-negative")
    if np.any(demand_arr < 0):
        raise ValueError("demand must be non-negative")

    if np.isscalar(supply):
        supply_arr = np.full(len(demand_arr), int(supply), np.int64)
    else:
        supply_arr = np.asarray(supply, dtype=np.int64)
        if supply_arr.shape != demand_arr.shape:
            raise ValueError("supply must be scalar or match demand")
    if np.any(supply_arr < 0):
        raise ValueError("supply must be non-negative")

    reserve = np.zeros(len(demand_arr), np.int64)
    for frame_idx in range(len(reserve) - 2, -1, -1):
        next_frame = frame_idx + 1
        needed = (
            int(reserve[next_frame])
            + int(demand_arr[next_frame])
            - int(supply_arr[next_frame])
        )
        reserve[frame_idx] = min(capacity, max(0, needed))
    return reserve


def _peak_buffer_draw(
    demand: np.ndarray,
    supply: np.ndarray,
) -> int:
    """Return the largest cumulative draw since the last full refill."""

    draw = 0
    peak = 0
    for frame_demand, frame_supply in zip(demand, supply):
        draw = max(0, draw + int(frame_demand) - int(frame_supply))
        peak = max(peak, draw)
    return peak


def _first_overloaded_busy_period(
    demand: np.ndarray,
    supply: np.ndarray,
    capacity: int,
) -> tuple[int, int] | None:
    """Return the start and peak frame of the first over-capacity burst."""

    draw = 0
    busy_start = 0
    frame_idx = 0
    while frame_idx < len(demand):
        draw = max(
            0,
            draw + int(demand[frame_idx]) - int(supply[frame_idx]),
        )
        if draw == 0:
            busy_start = frame_idx + 1
            frame_idx += 1
            continue
        if draw <= capacity:
            frame_idx += 1
            continue

        peak_draw = draw
        peak_frame = frame_idx
        scan_draw = draw
        scan_idx = frame_idx + 1
        while scan_idx < len(demand):
            scan_draw = max(
                0,
                scan_draw
                + int(demand[scan_idx])
                - int(supply[scan_idx]),
            )
            if scan_draw > peak_draw:
                peak_draw = scan_draw
                peak_frame = scan_idx
            if scan_draw == 0:
                break
            scan_idx += 1
        return busy_start, peak_frame
    return None


def build_balanced_reserve_plan(
    demand: Sequence[int] | np.ndarray,
    supply: int | Sequence[int] | np.ndarray,
    capacity: int,
    *,
    minimum_demand: Sequence[int] | np.ndarray | None = None,
) -> ReservePlan:
    """Balance unavoidable shortage across each over-capacity burst.

    The ordinary clipped backwards curve preserves a full buffer for later
    frames when a burst needs more than the buffer can ever hold.  That makes
    the first frame of the burst absorb all unavoidable quality loss.  This
    planner instead applies one common served fraction to the predicted demand
    from the burst's start through its peak. ``minimum_demand`` protects work
    that must not be diluted by that fraction, such as a CRAM switch's full
    name-table refresh. The resulting demand is feasible with ``capacity`` and
    therefore produces a reserve curve without clipped overflow.
    """

    demand_arr = np.asarray(demand, dtype=np.int64)
    if demand_arr.ndim != 1:
        raise ValueError("demand must be one-dimensional")
    if capacity < 0:
        raise ValueError("capacity must be non-negative")
    if np.any(demand_arr < 0):
        raise ValueError("demand must be non-negative")
    if minimum_demand is None:
        minimum_arr = np.zeros(demand_arr.shape, np.int64)
    else:
        minimum_arr = np.asarray(minimum_demand, dtype=np.int64)
        if minimum_arr.shape != demand_arr.shape:
            raise ValueError("minimum demand must match demand")
        if np.any(minimum_arr < 0):
            raise ValueError("minimum demand must be non-negative")
        if np.any(minimum_arr > demand_arr):
            raise ValueError("minimum demand cannot exceed demand")

    if np.isscalar(supply):
        supply_arr = np.full(len(demand_arr), int(supply), np.int64)
    else:
        supply_arr = np.asarray(supply, dtype=np.int64)
        if supply_arr.shape != demand_arr.shape:
            raise ValueError("supply must be scalar or match demand")
    if np.any(supply_arr < 0):
        raise ValueError("supply must be non-negative")
    if _peak_buffer_draw(minimum_arr, supply_arr) > capacity:
        raise ValueError(
            "minimum demand is infeasible within the quality-budget capacity")

    planned = demand_arr.copy()
    max_passes = max(1, len(planned) * 2)
    for _pass in range(max_passes):
        overloaded = _first_overloaded_busy_period(
            planned, supply_arr, capacity)
        if overloaded is None:
            break
        start, peak = overloaded
        window_demand = planned[start:peak + 1]
        window_minimum = minimum_arr[start:peak + 1]
        window_supply = supply_arr[start:peak + 1]

        low = 0.0
        high = 1.0
        for _ in range(60):
            fraction = (low + high) * 0.5
            candidate = (
                window_minimum
                + np.floor(
                    (window_demand - window_minimum).astype(np.float64)
                    * fraction
                ).astype(np.int64)
            )
            if _peak_buffer_draw(candidate, window_supply) <= capacity:
                low = fraction
            else:
                high = fraction
        candidate = (
            window_minimum
            + np.floor(
                (window_demand - window_minimum).astype(np.float64) * low
            ).astype(np.int64)
        )
        if np.array_equal(candidate, window_demand):
            # Integer rounding should already make progress.  Keep a strict
            # fallback so malformed inputs cannot turn this into an endless
            # planner loop.
            reducible = np.flatnonzero(candidate > window_minimum)
            if not reducible.size:
                raise AssertionError(
                    "balanced demand is overloaded with no reducible work")
            candidate[int(reducible[-1])] -= 1
        planned[start:peak + 1] = candidate
    else:
        raise RuntimeError("balanced reserve planning did not converge")

    if _peak_buffer_draw(planned, supply_arr) > capacity:
        raise AssertionError("balanced demand still exceeds buffer capacity")
    if np.any(planned < minimum_arr):
        raise AssertionError("balanced demand fell below its mandatory floor")
    reserve = build_reserve_curve(planned, supply_arr, capacity)
    shortfall = demand_arr - planned
    return ReservePlan(reserve, planned, shortfall)


def planned_spend_limit(
    *,
    budget_before: int,
    frame_supply: int,
    reserve_after: int,
    already_spent: int,
) -> int:
    """Return this frame's total byte limit after protecting its reserve.

    A caller may pass work already committed before planning. In that case it
    remains authoritative and later work receives no additional bytes.
    """

    if min(budget_before, frame_supply, reserve_after, already_spent) < 0:
        raise ValueError(
            "budget, supply, reserve, and spending must be non-negative")
    spendable = max(0, budget_before + frame_supply - reserve_after)
    return max(already_spent, spendable)
