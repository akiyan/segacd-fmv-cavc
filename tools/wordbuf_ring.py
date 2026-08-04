#!/usr/bin/env python3
"""Plan sector-granular timed refills for the parity WordBuf rings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

import av_config
import pattern_supply
import stream_schedule
import cavc_routing


BASE = 1
UNKNOWN = -1
PRG = pattern_supply.SOURCE_PRG
WORD = pattern_supply.SOURCE_WR
MANDATORY_PRG = 3
PATTERNS_PER_SECTOR = stream_schedule.PATTERNS_PER_SECTOR
MAX_WORD_STAGE_SECTORS = av_config.WORD_PENDING_SECTORS
MAX_SLOT_SECTORS = cavc_routing.FRAME_SECTORS
BOOT_REFILL_RESERVE_SECTORS = (2, 0)
PRG_BACKUP_TRIGGER_PATTERNS = (
    MAX_WORD_STAGE_SECTORS * PATTERNS_PER_SECTOR
)


@dataclass(frozen=True)
class Item:
    """One source-indivisible physical run or mandatory Prg prefetch."""

    frame: int
    parity: int
    count: int
    updates: tuple[int, ...]
    mandatory_prg: bool = False
    word_safe: bool = True


@dataclass(frozen=True)
class WordBufRingPlan:
    """Complete physical source and timed-delivery proof."""

    feasible: bool
    failure: str
    sources: tuple[tuple[int, ...], ...]
    boot_patterns: tuple[int, int]
    boot_end_frames: tuple[int, int]
    selected_refill_patterns: tuple[int, int]
    word_stage_sectors: np.ndarray
    word_stage_patterns: np.ndarray
    prg_payload_sectors: np.ndarray
    prg_payload_patterns: np.ndarray
    payload_sectors: np.ndarray
    control_sectors: np.ndarray
    physical_sectors: np.ndarray
    prg_loads: np.ndarray
    wr0_loads: np.ndarray
    wr1_loads: np.ndarray
    runs: np.ndarray
    prg_occupancy: np.ndarray
    word_occupancy: np.ndarray
    evaluation_end_frame: int
    prebuffer_patterns: int
    current_runs: int
    source_merged_runs: int
    model_runs: int


def schedule_dict(
    plan: WordBufRingPlan,
    block_lengths: Sequence[int] | np.ndarray,
) -> dict[str, object]:
    """Expose a refill plan through the canonical schedule field names."""

    if not plan.feasible:
        raise ValueError(f"cannot schedule an infeasible ring plan: {plan.failure}")
    lengths = np.asarray(block_lengths, np.int64)
    if lengths.shape != plan.control_sectors.shape:
        raise ValueError("ring control lengths have the wrong shape")
    control_capacity = plan.control_sectors * stream_schedule.SECTOR_BYTES
    control_need = lengths.copy()
    if len(control_need):
        control_need[0] = 0
    control_delivered = np.cumsum(control_capacity, dtype=np.int64)
    control_required = np.cumsum(control_need, dtype=np.int64)
    control_margin = control_delivered - control_required
    if np.any(control_margin < 0):
        frame = int(np.flatnonzero(control_margin < 0)[0])
        raise ValueError(
            f"frame {frame}: ring control route is short by "
            f"{-int(control_margin[frame])} bytes")

    useful_control = np.zeros(len(lengths), np.int64)
    remaining_control = int(control_need.sum())
    for frame, capacity in enumerate(control_capacity):
        take = min(int(capacity), remaining_control)
        useful_control[frame] = take
        remaining_control -= take
    if remaining_control:
        raise AssertionError("ring control delivery lost bytes")

    useful_payload = (
        np.asarray(plan.word_stage_patterns, np.int64)
        + np.asarray(plan.prg_payload_patterns, np.int64)
    ) * pattern_supply.PATTERN_BYTES
    routed_sectors = (
        np.asarray(plan.payload_sectors, np.int64)
        + np.asarray(plan.control_sectors, np.int64)
    )
    if np.any(routed_sectors > MAX_SLOT_SECTORS):
        frame = int(np.flatnonzero(
            routed_sectors > MAX_SLOT_SECTORS)[0])
        raise ValueError(
            f"frame {frame}: ring route exceeds the "
            f"{MAX_SLOT_SECTORS}-sector routing-byte limit")
    physical_bytes = (
        np.asarray(plan.physical_sectors, np.int64)
        * stream_schedule.SECTOR_BYTES
    )
    pad_bytes = physical_bytes - useful_control - useful_payload
    if np.any(pad_bytes < 0):
        frame = int(np.flatnonzero(pad_bytes < 0)[0])
        raise ValueError(
            f"frame {frame}: useful ring bytes exceed physical CD time")
    before_consume = (
        np.asarray(plan.prg_occupancy, np.int64)
        + np.asarray(plan.prg_loads, np.int64)
    )
    if len(before_consume):
        # Frame 0 is built from the untimed BODY arm and never consumes PrgBuf.
        # Its scheduled occupancy is only the frame-1 HEADER prebuffer.
        before_consume[0] = int(plan.prg_occupancy[0])
    evaluation = np.asarray(
        plan.prg_occupancy[1:plan.evaluation_end_frame], np.int64)
    ring_min_evaluation = int(
        evaluation.min()) if evaluation.size else int(
            np.asarray(plan.prg_occupancy, np.int64).min(initial=0))
    return {
        "n_pay_sec": np.asarray(plan.payload_sectors, np.int64),
        "n_ctrl_sec": np.asarray(plan.control_sectors, np.int64),
        "word_stage_sectors": np.asarray(
            plan.word_stage_sectors, np.int64),
        "prg_payload_sectors": np.asarray(
            plan.prg_payload_sectors, np.int64),
        "word_stage_patterns": np.asarray(
            plan.word_stage_patterns, np.int64),
        "prg_payload_patterns": np.asarray(
            plan.prg_payload_patterns, np.int64),
        "fsec": np.asarray(plan.physical_sectors, np.int64),
        "ratedelta": np.asarray(plan.physical_sectors, np.int64),
        "rate_lead_peak": 0,
        "rate_lead_end": 0,
        "feasible": True,
        "over": 0,
        "under": 0,
        "prebuf_pat": int(plan.prebuffer_patterns),
        "ring_capacity_patterns": int(plan.prebuffer_patterns),
        "prebuffer_capacity_patterns": int(plan.prebuffer_patterns),
        "jitter_headroom_patterns": 0,
        "ring_peak": int(before_consume.max(initial=0)),
        "ring_jitter_peak": max(
            0,
            int(before_consume.max(initial=0))
            - int(plan.prebuffer_patterns),
        ),
        "ring_min": int(
            np.asarray(plan.prg_occupancy, np.int64).min(initial=0)),
        "ring_min_evaluation": ring_min_evaluation,
        "evaluation_end_frame": int(plan.evaluation_end_frame),
        "ring_occupancy": np.asarray(plan.prg_occupancy, np.int64),
        "ring_occupancy_before_consume": before_consume,
        "max_cumulative_prg_consumption": np.cumsum(
            np.asarray(plan.prg_loads, np.int64), dtype=np.int64),
        "word_occupancy": np.asarray(plan.word_occupancy, np.int64),
        "ready_min": 0,
        "ctrl_min": int(control_margin.min(initial=0)),
        "blk_len": lengths,
        "body_useful_payload_bytes": useful_payload,
        "body_useful_control_bytes": useful_control,
        "body_pad_bytes": pad_bytes,
        "body_rate_pad_bytes": pad_bytes,
        "body_stream_pad_bytes": np.zeros(len(lengths), np.int64),
        "body_physical_bytes": physical_bytes,
        "M": int(
            np.asarray(plan.prg_loads, np.int64).sum()
            + np.asarray(plan.word_stage_patterns, np.int64).sum()),
        "f0_header": True,
        "f0_cold": 0,
        "f0_ctrl_len": int(lengths[0]) if len(lengths) else 0,
    }


def replay_frozen_schedule(
    *,
    prg_loads: Sequence[int] | np.ndarray,
    wr0_loads: Sequence[int] | np.ndarray,
    wr1_loads: Sequence[int] | np.ndarray,
    block_lengths: Sequence[int] | np.ndarray,
    payload_sectors: Sequence[int] | np.ndarray,
    control_sectors: Sequence[int] | np.ndarray,
    word_stage_sectors: Sequence[int] | np.ndarray,
    fps: float,
    prebuffer_patterns: int,
    prg_capacity_patterns: int,
    word_capacities: tuple[int, int],
    boot_patterns: tuple[int, int],
    f0_cold: int,
) -> dict[str, object]:
    """Replay a frozen ring route from materialized packer counts.

    This is deliberately independent from the source-selection heuristic.  The
    packer uses it to prove that frozen sources, control sizes, routing bytes,
    and both physical WordBuf streams still form the same bounded schedule.
    """

    prg = np.asarray(prg_loads, np.int64)
    wr0 = np.asarray(wr0_loads, np.int64)
    wr1 = np.asarray(wr1_loads, np.int64)
    lengths = np.asarray(block_lengths, np.int64)
    n_pay = np.asarray(payload_sectors, np.int64)
    n_ctrl = np.asarray(control_sectors, np.int64)
    n_word = np.asarray(word_stage_sectors, np.int64)
    shape = prg.shape
    if (
        prg.ndim != 1
        or any(values.shape != shape for values in (
            wr0, wr1, lengths, n_pay, n_ctrl, n_word))
    ):
        raise ValueError("frozen WordBuf ring traces have different shapes")
    if not len(prg):
        raise ValueError("frozen WordBuf ring route is empty")
    if any(np.any(values < 0) for values in (
            prg, wr0, wr1, lengths, n_pay, n_ctrl, n_word)):
        raise ValueError("frozen WordBuf ring route contains a negative value")
    if (
        int(n_pay[0]) != 0
        or int(n_ctrl[0]) != 0
        or int(n_word[0]) != 0
    ):
        raise ValueError("frame zero cannot contain timed ring sectors")
    if np.any(n_word > n_pay) or np.any(n_word > MAX_WORD_STAGE_SECTORS):
        frame = int(np.flatnonzero(
            (n_word > n_pay) | (n_word > MAX_WORD_STAGE_SECTORS))[0])
        raise ValueError(
            f"frame {frame}: frozen WordBuf stage prefix is invalid")
    if np.any(n_pay + n_ctrl > MAX_SLOT_SECTORS):
        frame = int(np.flatnonzero(
            n_pay + n_ctrl > MAX_SLOT_SECTORS)[0])
        raise ValueError(
            f"frame {frame}: frozen route exceeds the physical slot")

    expected_control = stream_schedule.control_sector_schedule(lengths)
    if not np.array_equal(expected_control, n_ctrl):
        frame = int(np.flatnonzero(expected_control != n_ctrl)[0])
        raise ValueError(
            f"frame {frame}: frozen control sectors differ from packed blocks")

    fsec, ratedelta, rate_lead_trace = stream_schedule.rate_match_sectors(
        n_pay, n_ctrl, fps=float(fps))
    rate_lead_peak = int(rate_lead_trace.max(initial=0))
    rate_lead_end = int(rate_lead_trace[-1])
    if rate_lead_peak:
        raise ValueError(
            "frozen WordBuf route borrows physical CD time from a later slot")

    prebuffer = int(prebuffer_patterns)
    prg_capacity = int(prg_capacity_patterns)
    capacities = tuple(int(value) for value in word_capacities)
    boots = tuple(int(value) for value in boot_patterns)
    if not 0 <= prebuffer <= prg_capacity:
        raise ValueError("frozen Prg prebuffer exceeds its capacity")
    if prebuffer % PATTERNS_PER_SECTOR:
        raise ValueError(
            "frozen Prg prebuffer must be a whole number of CD sectors; "
            f"{prebuffer} patterns is fractional and would misalign the "
            "player's ring tail")
    if any(
            boot < 0 or boot > capacity
            for boot, capacity in zip(boots, capacities, strict=True)):
        raise ValueError("frozen WordBuf boot contents exceed capacity")

    prg_payload_sectors = n_pay - n_word
    timed_prg_patterns = int(prg[1:].sum())
    if prebuffer > timed_prg_patterns:
        raise ValueError("frozen Prg prebuffer exceeds timed Prg demand")
    remaining_prg = timed_prg_patterns - prebuffer
    useful_prg_patterns = np.zeros(len(prg), np.int64)
    for frame in range(1, len(prg)):
        take = min(
            int(prg_payload_sectors[frame]) * PATTERNS_PER_SECTOR,
            remaining_prg,
        )
        useful_prg_patterns[frame] = take
        remaining_prg -= take
    if remaining_prg:
        raise ValueError(
            f"frozen Prg route omits {remaining_prg} timed patterns")

    expected_refill = (
        int(wr0.sum()) - boots[0],
        int(wr1.sum()) - boots[1],
    )
    staged = (
        int(n_word[::2].sum()) * PATTERNS_PER_SECTOR,
        int(n_word[1::2].sum()) * PATTERNS_PER_SECTOR,
    )
    if expected_refill != staged:
        raise ValueError(
            "frozen WordBuf refill counts differ from routed sectors: "
            f"loads={expected_refill} staged={staged}")

    prg_trace = np.zeros(len(prg), np.int64)
    prg_before_consume = np.zeros(len(prg), np.int64)
    word_trace = np.zeros((len(prg), 2), np.int64)
    ready_min = prg_capacity
    prg_level = prebuffer
    word_level = [boots[0], boots[1]]
    for frame in range(len(prg)):
        prg_need = 0 if frame == 0 else int(prg[frame])
        if prg_level < prg_need:
            raise ValueError(
                f"frame {frame}: Prg deadline is short by "
                f"{prg_need - prg_level} patterns")
        ready_min = min(ready_min, prg_level - prg_need)
        parity = frame & 1
        word_need = int((wr1 if parity else wr0)[frame])
        if word_level[parity] < word_need:
            raise ValueError(
                f"frame {frame}: WordBuf{parity} deadline is short by "
                f"{word_need - word_level[parity]} patterns")

        prg_level += (
            int(prg_payload_sectors[frame]) * PATTERNS_PER_SECTOR)
        prg_before_consume[frame] = prg_level
        if prg_level > prg_capacity:
            raise ValueError(
                f"frame {frame}: Prg occupancy {prg_level} exceeds "
                f"capacity {prg_capacity}")
        word_level[parity] += (
            int(n_word[frame]) * PATTERNS_PER_SECTOR)
        if word_level[parity] > capacities[parity]:
            raise ValueError(
                f"frame {frame}: WordBuf{parity} occupancy "
                f"{word_level[parity]} exceeds capacity {capacities[parity]}")

        prg_level -= prg_need
        word_level[parity] -= word_need
        prg_trace[frame] = prg_level
        word_trace[frame] = word_level

    useful_payload = (
        useful_prg_patterns + n_word * PATTERNS_PER_SECTOR
    ) * pattern_supply.PATTERN_BYTES
    control_capacity = n_ctrl * stream_schedule.SECTOR_BYTES
    control_need = lengths.copy()
    control_need[0] = 0
    control_margin = (
        np.cumsum(control_capacity, dtype=np.int64)
        - np.cumsum(control_need, dtype=np.int64)
    )
    if np.any(control_margin < 0):
        frame = int(np.flatnonzero(control_margin < 0)[0])
        raise ValueError(
            f"frame {frame}: frozen control route misses its deadline")
    useful_control = np.zeros(len(prg), np.int64)
    remaining_control = int(control_need.sum())
    for frame, capacity in enumerate(control_capacity):
        take = min(int(capacity), remaining_control)
        useful_control[frame] = take
        remaining_control -= take
    if remaining_control:
        raise AssertionError("frozen control replay lost bytes")

    physical_bytes = fsec * stream_schedule.SECTOR_BYTES
    pad_bytes = physical_bytes - useful_payload - useful_control
    if np.any(pad_bytes < 0):
        frame = int(np.flatnonzero(pad_bytes < 0)[0])
        raise ValueError(
            f"frame {frame}: frozen useful bytes exceed physical CD time")
    payload_frames = np.flatnonzero(n_pay > 0)
    evaluation_end = (
        min(len(prg), int(payload_frames[-1]) + 1)
        if payload_frames.size else len(prg)
    )
    evaluation = prg_trace[1:evaluation_end]
    ring_min_evaluation = (
        int(evaluation.min()) if evaluation.size else int(prg_trace.min()))
    return {
        "n_pay_sec": n_pay,
        "n_ctrl_sec": n_ctrl,
        "word_stage_sectors": n_word,
        "prg_payload_sectors": prg_payload_sectors,
        "word_stage_patterns": n_word * PATTERNS_PER_SECTOR,
        "prg_payload_patterns": useful_prg_patterns,
        "fsec": fsec,
        "ratedelta": ratedelta,
        "rate_lead_peak": rate_lead_peak,
        "rate_lead_end": rate_lead_end,
        "feasible": True,
        "over": 0,
        "under": 0,
        "prebuf_pat": prebuffer,
        "ring_capacity_patterns": prg_capacity,
        "prebuffer_capacity_patterns": prg_capacity,
        "jitter_headroom_patterns": 0,
        "ring_peak": int(prg_before_consume.max(initial=0)),
        "ring_jitter_peak": max(
            0, int(prg_before_consume.max(initial=0)) - prg_capacity),
        "ring_min": int(prg_trace.min(initial=0)),
        "ring_min_evaluation": ring_min_evaluation,
        "evaluation_end_frame": evaluation_end,
        "ring_occupancy": prg_trace,
        "ring_occupancy_before_consume": prg_before_consume,
        "word_occupancy": word_trace,
        "ready_min": int(ready_min),
        "ctrl_min": int(control_margin.min(initial=0)),
        "blk_len": lengths,
        "body_useful_payload_bytes": useful_payload,
        "body_useful_control_bytes": useful_control,
        "body_pad_bytes": pad_bytes,
        "body_rate_pad_bytes": pad_bytes,
        "body_stream_pad_bytes": np.zeros(len(prg), np.int64),
        "body_physical_bytes": physical_bytes,
        "M": int(prg[1:].sum() + staged[0] + staged[1]),
        "f0_header": True,
        "f0_cold": int(f0_cold),
        "f0_ctrl_len": int(lengths[0]),
    }


@dataclass
class _State:
    sources: np.ndarray
    delivered: np.ndarray
    prg_occupancy: int
    word_occupancy: list[int]
    prg_remaining: int
    word_remaining: list[int]
    prg_cursor: int
    word_cursor: list[int]


class _Transaction:
    """Rollback journal for one prospective physical payload sector."""

    def __init__(self, state: _State):
        self.state = state
        self.sources: dict[int, int] = {}
        self.delivered: dict[int, int] = {}
        self.scalars = (
            state.prg_occupancy,
            tuple(state.word_occupancy),
            state.prg_remaining,
            tuple(state.word_remaining),
            state.prg_cursor,
            tuple(state.word_cursor),
        )

    def touch(self, index: int) -> None:
        self.sources.setdefault(index, int(self.state.sources[index]))
        self.delivered.setdefault(index, int(self.state.delivered[index]))

    def rollback(self) -> None:
        for index, source in self.sources.items():
            self.state.sources[index] = source
        for index, delivered in self.delivered.items():
            self.state.delivered[index] = delivered
        (
            self.state.prg_occupancy,
            word_occupancy,
            self.state.prg_remaining,
            word_remaining,
            self.state.prg_cursor,
            word_cursor,
        ) = self.scalars
        self.state.word_occupancy[:] = word_occupancy
        self.state.word_remaining[:] = word_remaining
        self.state.word_cursor[:] = word_cursor


def _build_items(
    per,
    prefetch_per,
    transfer_orders,
    current_plan: pattern_supply.SupplyPlan,
) -> tuple[list[Item], list[list[int]], list[list[int]], list[int]]:
    items: list[Item] = []
    frame_items: list[list[int]] = [[] for _ in per]
    parity_items: list[list[int]] = [[], []]
    current_word_counts: list[int] = []
    for frame, (
        (_cells, entries, colds),
        sources,
        transfer_order,
        prefetch,
    ) in enumerate(zip(
        per,
        current_plan.sources,
        transfer_orders,
        prefetch_per,
        strict=True,
    )):
        if not frame:
            continue
        cold_prefetch = sorted(
            (entry for entry in prefetch if bool(entry[1])),
            key=lambda entry: int(entry[0]),
        )
        first_prefetch_slot = (
            int(cold_prefetch[0][0]) if cold_prefetch else None)
        run_updates: list[int] = []
        previous_slot: int | None = None

        def append_run() -> None:
            nonlocal run_updates
            if not run_updates:
                return
            last_slot = (
                (int(entries[run_updates[-1]]) & 0x07FF) - BASE)
            index = len(items)
            item = Item(
                frame,
                frame & 1,
                len(run_updates),
                tuple(run_updates),
                word_safe=(
                    first_prefetch_slot is None
                    or last_slot + 1 != first_prefetch_slot
                ),
            )
            items.append(item)
            current_word_counts.append(sum(
                int(sources[update]) == WORD
                for update in run_updates
            ))
            frame_items[frame].append(index)
            parity_items[frame & 1].append(index)
            run_updates = []

        for update in transfer_order:
            if not colds[update]:
                raise ValueError("transfer order contains a reuse")
            slot = (int(entries[update]) & 0x07FF) - BASE
            source = int(sources[update])
            candidate = source != pattern_supply.SOURCE_DIC
            continues = (
                candidate
                and bool(run_updates)
                and previous_slot is not None
                and slot == previous_slot + 1
            )
            if run_updates and not continues:
                append_run()
            if candidate:
                run_updates.append(int(update))
            previous_slot = slot if candidate else None
        append_run()

        if cold_prefetch:
            index = len(items)
            items.append(Item(
                frame,
                frame & 1,
                len(cold_prefetch),
                (),
                mandatory_prg=True,
            ))
            current_word_counts.append(0)
            frame_items[frame].append(index)
    return items, frame_items, parity_items, current_word_counts


def _assign_boot(
    items: list[Item],
    parity_items: list[list[int]],
    current_word_counts: list[int],
    state: _State,
    capacities: tuple[int, int],
    baseline_occupancy: np.ndarray,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Place the free boot turn at the first predicted Prg pressure region.

    The legacy finite Word assignment already marks the suffix where the Prg
    forecast first needs help.  Use that signal instead of consuming WordBuf
    from the beginning of the movie.  A complete physical run remains the
    indivisible source unit, and the earliest prefix that can fill the bank
    exactly keeps later runs available for timed refill.
    """

    loaded = [0, 0]
    end_frames = [0, 0]
    for parity in (0, 1):
        capacity = int(capacities[parity])
        pressure_frames = [
            items[index].frame
            for index in parity_items[parity]
            if current_word_counts[index] > 0
        ]
        pressure_start = min(pressure_frames, default=1)
        candidates = [
            index
            for index in parity_items[parity]
            if (
                items[index].frame >= pressure_start
                and items[index].word_safe
                and items[index].count <= capacity
            )
        ]
        horizon = _minimal_exact_horizon(items, candidates, capacity)
        if horizon is None:
            # Old decision logs without the pressure marker still get a
            # deterministic whole-run boot plan.
            candidates = [
                index
                for index in parity_items[parity]
                if items[index].word_safe and items[index].count <= capacity
            ]
            horizon = _minimal_exact_horizon(items, candidates, capacity)
        if horizon is None:
            continue
        pool = [
            index for index in candidates
            if items[index].frame <= horizon
        ]
        selected = _exact_subset(
            items,
            pool,
            capacity,
            key=lambda index: (
                0 if current_word_counts[index] else 1,
                -current_word_counts[index],
                (
                    -current_word_counts[index] / items[index].count
                    if current_word_counts[index] else 0.0
                ),
                int(baseline_occupancy[items[index].frame]),
                -items[index].frame,
                index,
            ),
        )
        if selected is None:
            continue
        selected_set = set(selected)
        frontier = max(
            parity_items[parity].index(index) for index in selected)
        for position, index in enumerate(parity_items[parity]):
            if position > frontier:
                break
            item = items[index]
            if index not in selected_set:
                state.sources[index] = PRG
                state.prg_remaining += item.count
                continue
            state.sources[index] = WORD
            state.delivered[index] = item.count
            state.word_occupancy[parity] += item.count
            loaded[parity] += item.count
            end_frames[parity] = max(end_frames[parity], item.frame)
        state.word_cursor[parity] = frontier + 1
    return (loaded[0], loaded[1]), (end_frames[0], end_frames[1])


def _minimal_exact_horizon(
    items: list[Item],
    candidates: Sequence[int],
    amount: int,
) -> int | None:
    """Return the earliest frame prefix that can sum exactly to amount."""

    if amount < 0:
        raise ValueError("exact-subset amount must be non-negative")
    if not amount:
        return 0
    mask = (1 << (amount + 1)) - 1
    reachable = 1
    ordered = sorted(
        (int(index) for index in candidates),
        key=lambda index: (items[index].frame, index),
    )
    cursor = 0
    while cursor < len(ordered):
        frame = items[ordered[cursor]].frame
        while cursor < len(ordered) and items[ordered[cursor]].frame == frame:
            count = items[ordered[cursor]].count
            if 0 < count <= amount:
                reachable |= reachable << count
                reachable &= mask
            cursor += 1
        if reachable & (1 << amount):
            return int(frame)
    return None


def _exact_subset(
    items: list[Item],
    candidates: Sequence[int],
    amount: int,
    *,
    key,
) -> tuple[int, ...] | None:
    """Choose one deterministic exact complete-run subset.

    Candidate order expresses preference.  The first proof for each subtotal
    is retained, which is sufficient because every accepted set has the same
    physical sector size and receives a separate full schedule replay.
    """

    if amount < 0:
        raise ValueError("exact-subset amount must be non-negative")
    if not amount:
        return ()
    previous_total = np.full(amount + 1, -2, np.int64)
    previous_index = np.full(amount + 1, -1, np.int64)
    previous_total[0] = -1
    for index in sorted((int(value) for value in candidates), key=key):
        count = int(items[index].count)
        if not 0 < count <= amount:
            continue
        for total in range(amount, count - 1, -1):
            if (
                int(previous_total[total]) == -2
                and int(previous_total[total - count]) != -2
            ):
                previous_total[total] = total - count
                previous_index[total] = index
        if int(previous_total[amount]) != -2:
            break
    if int(previous_total[amount]) == -2:
        return None
    selected: list[int] = []
    total = amount
    while total:
        index = int(previous_index[total])
        if index < 0:
            raise AssertionError("exact-subset predecessor is missing")
        selected.append(index)
        total = int(previous_total[total])
    selected.sort()
    return tuple(selected)


def _best_exact_subset(
    items: list[Item],
    candidates: Sequence[int],
    amount: int,
    *,
    score,
) -> tuple[int, ...] | None:
    """Maximize an additive score for one small exact sector."""

    best: list[
        tuple[tuple[int, ...], tuple[int, ...]] | None
    ] = [None] * (amount + 1)
    best[0] = ((0, 0, 0, 0, 0), ())
    for index in candidates:
        count = int(items[index].count)
        if not 0 < count <= amount:
            continue
        item_score = tuple(int(value) for value in score(int(index)))
        for total in range(amount, count - 1, -1):
            previous = best[total - count]
            if previous is None:
                continue
            candidate_score = tuple(
                left + right
                for left, right in zip(
                    previous[0], item_score, strict=True)
            )
            candidate = (
                candidate_score,
                previous[1] + (int(index),),
            )
            if best[total] is None or candidate_score > best[total][0]:
                best[total] = candidate
    if best[amount] is None:
        return None
    return tuple(sorted(best[amount][1]))


def _deliver_prg(
    items: list[Item],
    state: _State,
    capacity: int,
    amount: int,
    transaction: _Transaction,
) -> int:
    delivered = 0
    while delivered < amount and state.prg_occupancy < capacity:
        while state.prg_cursor < len(items):
            index = state.prg_cursor
            source = int(state.sources[index])
            if source == WORD:
                state.prg_cursor += 1
                continue
            if int(state.delivered[index]) >= items[index].count:
                state.prg_cursor += 1
                continue
            break
        if state.prg_cursor >= len(items):
            break
        index = state.prg_cursor
        item = items[index]
        transaction.touch(index)
        if int(state.sources[index]) == UNKNOWN:
            state.sources[index] = PRG
            state.prg_remaining += item.count
        room = min(
            amount - delivered,
            capacity - state.prg_occupancy,
            item.count - int(state.delivered[index]),
        )
        if room <= 0:
            break
        state.delivered[index] += room
        state.prg_occupancy += room
        state.prg_remaining -= room
        delivered += room
        if int(state.delivered[index]) == item.count:
            state.prg_cursor += 1
    return delivered


def _deliver_word(
    frame: int,
    parity: int,
    items: list[Item],
    parity_items: list[list[int]],
    current_word_counts: list[int],
    state: _State,
    capacity: int,
    amount: int,
    transaction: _Transaction,
    baseline_occupancy: np.ndarray,
    target_frame: int,
) -> int:
    """Commit one exact Word sector around the next Prg low-water point."""

    if amount <= 0 or state.word_occupancy[parity] + amount > capacity:
        return 0
    indices = parity_items[parity]
    while state.word_cursor[parity] < len(indices):
        index = indices[state.word_cursor[parity]]
        if int(state.sources[index]) == UNKNOWN:
            break
        state.word_cursor[parity] += 1
    candidates = [
        index
        for index in indices[state.word_cursor[parity]:]
        if (
            int(state.sources[index]) == UNKNOWN
            and items[index].word_safe
            and items[index].frame > frame
            and items[index].count <= amount
        )
    ]
    if not candidates:
        return 0
    before_target = [
        index for index in candidates
        if items[index].frame <= target_frame
    ]
    if _minimal_exact_horizon(items, before_target, amount) is not None:
        horizon = int(target_frame)
    else:
        horizon = _minimal_exact_horizon(items, candidates, amount)
        if horizon is None:
            return 0
    pool = [
        index for index in candidates
        if items[index].frame <= horizon
    ]
    selected = _best_exact_subset(
        items,
        pool,
        amount,
        score=lambda index: (
            (
                items[index].count
                if items[index].frame <= target_frame else 0
            ),
            -abs(items[index].frame - target_frame)
            * items[index].count,
            current_word_counts[index],
            -int(baseline_occupancy[items[index].frame])
            * items[index].count,
            -max(0, items[index].frame - target_frame)
            * items[index].count,
        ),
    )
    if selected is None:
        return 0
    if not any(items[index].frame <= target_frame for index in selected):
        return 0
    selected_set = set(selected)
    selected_positions = [
        indices.index(index, state.word_cursor[parity])
        for index in selected
    ]
    frontier = max(selected_positions)
    delivered = 0
    for position in range(state.word_cursor[parity], frontier + 1):
        index = indices[position]
        if int(state.sources[index]) != UNKNOWN:
            continue
        item = items[index]
        transaction.touch(index)
        if index in selected_set:
            state.sources[index] = WORD
            state.delivered[index] = item.count
            delivered += item.count
        else:
            state.sources[index] = PRG
            state.prg_remaining += item.count
    if delivered != amount:
        raise AssertionError(
            f"exact Word sector delivered {delivered}/{amount} patterns")
    state.word_occupancy[parity] += delivered
    state.word_cursor[parity] = frontier + 1
    return delivered


def _remaining_source(
    items: list[Item],
    state: _State,
    source: int,
    parity: int | None = None,
) -> int:
    return sum(
        item.count - int(state.delivered[index])
        for index, item in enumerate(items)
        if (
            int(state.sources[index]) == source
            and (parity is None or item.parity == parity)
        )
    )


def _remaining_potential_prg(
    items: list[Item],
    state: _State,
) -> int:
    """Count undelivered patterns that are not already committed to WordBuf."""

    return sum(
        item.count - int(state.delivered[index])
        for index, item in enumerate(items)
        if int(state.sources[index]) != WORD
    )


def _next_prg_pressure_frame(
    *,
    frame: int,
    items: list[Item],
    frame_items: list[list[int]],
    state: _State,
    payload_capacity: np.ndarray,
    prg_capacity: int,
) -> int | None:
    """Forecast the next low-water frame with every unknown run on Prg.

    The current slot is omitted: this helper is called only after PrgBuf could
    not accept another full sector.  Future slots still fill Prg first.  A
    refill is useful only when the forecast enters one maximum Word-prefix
    batch of empty.  That four-sector lookahead is required because the
    routing byte can move at most four Word sectors in one slot; waiting for
    the final sector of Prg headroom can leave no later spare slot.
    """

    level = int(state.prg_occupancy)
    remaining_delivery = _remaining_potential_prg(items, state)
    minimum_level = level
    minimum_frame = frame
    for future in range(frame, len(frame_items)):
        need = sum(
            items[index].count
            for index in frame_items[future]
            if int(state.sources[index]) != WORD
        )
        if level < need:
            return int(future)

        if future != frame:
            for _sector in range(int(payload_capacity[future])):
                if prg_capacity - level < PATTERNS_PER_SECTOR:
                    break
                if remaining_delivery >= PATTERNS_PER_SECTOR:
                    level += PATTERNS_PER_SECTOR
                    remaining_delivery -= PATTERNS_PER_SECTOR
                    continue
                if remaining_delivery:
                    # A final short useful sector still advances the physical
                    # write pointer by one complete sector.
                    level += PATTERNS_PER_SECTOR
                    remaining_delivery = 0
                break

        level -= need
        if level < minimum_level:
            minimum_level = level
            minimum_frame = future

    if minimum_level <= PRG_BACKUP_TRIGGER_PATTERNS:
        return int(minimum_frame)
    return None


def _transfer_run_records(
    entries,
    colds,
    sources,
    prefetch,
    dic_indices,
    transfer_order,
) -> tuple[tuple[int, int, int, int], ...]:
    order = tuple(int(index) for index in transfer_order)
    slots = [
        (int(entries[index]) & 0x07FF) - BASE
        for index in order
    ]
    item_sources = [int(sources[index]) for index in order]
    item_dic = [int(dic_indices[index]) for index in order]
    cold_prefetch = sorted(
        (item for item in prefetch if bool(item[1])),
        key=lambda item: int(item[0]),
    )
    slots.extend(int(item[0]) for item in cold_prefetch)
    item_sources.extend(PRG for _item in cold_prefetch)
    item_dic.extend(-1 for _item in cold_prefetch)
    return pattern_supply.source_runs(slots, item_sources, item_dic)


def _transfer_runs(
    entries,
    colds,
    sources,
    prefetch,
    dic_indices,
    transfer_order,
) -> int:
    return len(_transfer_run_records(
        entries,
        colds,
        sources,
        prefetch,
        dic_indices,
        transfer_order,
    ))


def _transfer_run_trace(
    per,
    sources,
    prefetch_per,
    dic_indices,
    transfer_orders,
    *,
    word_capacities: tuple[int, int] | None = None,
) -> np.ndarray:
    """Return exact per-frame descriptors, splitting WordBuf ring crossings."""
    word_cursors = [0, 0]
    counts = np.zeros(len(per), np.int64)
    for frame, (
            (_cells, entries, colds),
            frame_sources,
            prefetch,
            frame_dic_indices,
            transfer_order,
    ) in enumerate(zip(
            per,
            sources,
            prefetch_per,
            dic_indices,
            transfer_orders,
            strict=True,
    )):
        runs = _transfer_run_records(
            entries,
            colds,
            frame_sources,
            prefetch,
            frame_dic_indices,
            transfer_order,
        )
        if word_capacities is not None:
            parity = frame & 1
            runs, word_cursors[parity] = pattern_supply.split_word_ring_runs(
                runs,
                capacity=int(word_capacities[parity]),
                cursor=word_cursors[parity],
            )
        counts[frame] = len(runs)
    return counts


def plan(
    *,
    per,
    prefetch_per,
    transfer_orders,
    current_plan: pattern_supply.SupplyPlan,
    n_updates: Sequence[int] | np.ndarray,
    update_lists: Sequence[bool] | np.ndarray | None = None,
    frame_types: Sequence[int] | np.ndarray | None = None,
    fps: float,
    cells: int,
    audio_frame_bytes: int,
    prg_capacity_patterns: int,
    word_capacities: tuple[int, int],
    baseline_occupancy: Sequence[int] | np.ndarray,
) -> WordBufRingPlan:
    """Return a proven need-driven refill plan or a descriptive failure."""

    frame_count = len(per)
    if not (
        len(prefetch_per) == frame_count
        and len(transfer_orders) == frame_count
        and len(current_plan.sources) == frame_count
    ):
        raise ValueError("WordBuf ring inputs have different frame counts")
    baseline = np.asarray(baseline_occupancy, np.int64)
    if baseline.shape != (frame_count,):
        raise ValueError("baseline Prg occupancy has the wrong shape")
    capacities = tuple(int(value) for value in word_capacities)
    if any(value <= 0 or value % PATTERNS_PER_SECTOR for value in capacities):
        raise ValueError("WordBuf ring capacities must be positive sectors")

    items, frame_items, parity_items, current_word_counts = _build_items(
        per, prefetch_per, transfer_orders, current_plan)
    sources = np.full(len(items), UNKNOWN, np.int8)
    sources[np.asarray(
        [item.mandatory_prg for item in items], bool)] = MANDATORY_PRG
    state = _State(
        sources=sources,
        delivered=np.zeros(len(items), np.int64),
        prg_occupancy=0,
        word_occupancy=[0, 0],
        prg_remaining=sum(
            item.count
            for item in items
            if item.mandatory_prg
        ),
        word_remaining=[0, 0],
        prg_cursor=0,
        word_cursor=[0, 0],
    )
    boot_targets = tuple(
        max(
            0,
            capacity
            - reserve_sectors * PATTERNS_PER_SECTOR,
        )
        for capacity, reserve_sectors in zip(
            capacities, BOOT_REFILL_RESERVE_SECTORS, strict=True)
    )
    boot, boot_end = _assign_boot(
        items,
        parity_items,
        current_word_counts,
        state,
        boot_targets,
        baseline,
    )
    failure = ""
    if boot != boot_targets:
        failure = (
            f"complete-run boot fill reached {boot}, "
            f"expected {boot_targets}")

    merged_sources = tuple(
        tuple(PRG if source == WORD else source for source in frame)
        for frame in current_plan.sources
    )
    merged_runs = _transfer_run_trace(
        per,
        merged_sources,
        prefetch_per,
        current_plan.dic_indices,
        transfer_orders,
    )
    block_lengths = stream_schedule.control_block_lengths(
        np.asarray(n_updates, np.int64),
        merged_runs,
        cells=int(cells),
        audio_frame_bytes=int(audio_frame_bytes),
        update_lists=update_lists,
        frame_types=frame_types,
    )
    control_sectors = stream_schedule.control_sector_schedule(block_lengths)
    physical_sectors = stream_schedule.rate_deltas(frame_count, float(fps))
    # At 15 fps the physical cadence alternates between five and six sectors,
    # but the one-byte route can describe at most five useful sectors.  The
    # sixth sector is physical CD time/pad, not another payload opportunity.
    routed_capacity = np.minimum(physical_sectors, MAX_SLOT_SECTORS)
    payload_capacity = routed_capacity - control_sectors
    if np.any(payload_capacity < 0) and not failure:
        frame = int(np.flatnonzero(payload_capacity < 0)[0])
        failure = f"frame {frame}: control exceeds fixed CD time"

    transaction = _Transaction(state)
    # The player prefills the ring with prebuf_pat*32 bytes and the timed
    # BODY payload continues from that exact byte offset, so the prebuffer
    # must be a whole number of CD sectors. A fractional-sector prebuffer
    # (e.g. the 24 fps 389 KiB ceiling = 194.5 sectors) leaves ring_tail
    # permanently half-sector-misaligned: every ring lap one sector store
    # straddles RING_END, its tail bytes land outside the ring, and the pop
    # stream gains a permanent half-sector lead that scrambles every later
    # cold tile.
    prebuffer_target = (
        int(prg_capacity_patterns)
        // PATTERNS_PER_SECTOR
        * PATTERNS_PER_SECTOR
    )
    prebuffer = _deliver_prg(
        items,
        state,
        int(prg_capacity_patterns),
        prebuffer_target,
        transaction,
    )
    if prebuffer != prebuffer_target and not failure:
        failure = (
            f"Prg prebuffer reached {prebuffer}, "
            f"expected {prebuffer_target}")

    prg_trace = np.zeros(frame_count, np.int64)
    word_trace = np.zeros((frame_count, 2), np.int64)
    word_stage_patterns = np.zeros(frame_count, np.int64)
    word_stage_sectors = np.zeros(frame_count, np.int64)
    prg_payload_patterns = np.zeros(frame_count, np.int64)
    prg_payload_sectors = np.zeros(frame_count, np.int64)

    if not failure:
        for frame in range(frame_count):
            for index in frame_items[frame]:
                item = items[index]
                if int(state.delivered[index]) != item.count:
                    frame_prg_need = sum(
                        items[frame_index].count
                        for frame_index in frame_items[frame]
                        if int(state.sources[frame_index]) != WORD
                    )
                    failure = (
                        f"frame {frame}: source {int(state.sources[index])} "
                        f"delivered {int(state.delivered[index])}/{item.count}; "
                        f"Prg occupancy/need="
                        f"{state.prg_occupancy}/{frame_prg_need}, "
                        f"Word occupancy={tuple(state.word_occupancy)}")
                    break
            if failure:
                break

            sector = 0
            frame_payload_capacity = int(payload_capacity[frame])
            while sector < frame_payload_capacity:
                transaction = _Transaction(state)
                prg_count = _deliver_prg(
                    items,
                    state,
                    int(prg_capacity_patterns),
                    PATTERNS_PER_SECTOR,
                    transaction,
                )
                prg_remaining = _remaining_potential_prg(items, state)
                if prg_count == PATTERNS_PER_SECTOR:
                    prg_payload_patterns[frame] += prg_count
                    prg_payload_sectors[frame] += 1
                    sector += 1
                    continue
                if prg_count and prg_remaining == 0:
                    state.prg_occupancy += PATTERNS_PER_SECTOR - prg_count
                    prg_payload_patterns[frame] += prg_count
                    prg_payload_sectors[frame] += 1
                    sector += 1
                    continue
                transaction.rollback()

                target_frame = _next_prg_pressure_frame(
                    frame=frame,
                    items=items,
                    frame_items=frame_items,
                    state=state,
                    payload_capacity=payload_capacity,
                    prg_capacity=int(prg_capacity_patterns),
                )
                if target_frame is None:
                    break
                parity = frame & 1
                available_word_sectors = min(
                    MAX_WORD_STAGE_SECTORS
                    - int(word_stage_sectors[frame]),
                    frame_payload_capacity - sector,
                    (
                        capacities[parity]
                        - state.word_occupancy[parity]
                    ) // PATTERNS_PER_SECTOR,
                )
                accepted_word_patterns = 0
                for batch_sectors in range(
                        available_word_sectors, 0, -1):
                    batch_patterns = (
                        batch_sectors * PATTERNS_PER_SECTOR)
                    transaction = _Transaction(state)
                    word_count = _deliver_word(
                        frame,
                        parity,
                        items,
                        parity_items,
                        current_word_counts,
                        state,
                        capacities[parity],
                        batch_patterns,
                        transaction,
                        baseline,
                        target_frame,
                    )
                    if word_count == batch_patterns:
                        accepted_word_patterns = word_count
                        word_stage_patterns[frame] += word_count
                        word_stage_sectors[frame] += batch_sectors
                        sector += batch_sectors
                        break
                    transaction.rollback()
                if not accepted_word_patterns:
                    break

            for index in frame_items[frame]:
                item = items[index]
                source = int(state.sources[index])
                if source in (PRG, MANDATORY_PRG):
                    state.prg_occupancy -= item.count
                elif source == WORD:
                    state.word_occupancy[item.parity] -= item.count
                else:
                    raise AssertionError("ring item source was never assigned")
            if min(state.prg_occupancy, *state.word_occupancy) < 0:
                raise AssertionError("ring occupancy became negative")
            prg_trace[frame] = state.prg_occupancy
            word_trace[frame] = state.word_occupancy

    model_sources = [
        [int(source) for source in frame]
        for frame in current_plan.sources
    ]
    for index, item in enumerate(items):
        if item.mandatory_prg:
            continue
        source = int(state.sources[index])
        if source == UNKNOWN:
            source = PRG
        for update in item.updates:
            model_sources[item.frame][update] = source
    model_sources_tuple = tuple(
        tuple(frame) for frame in model_sources)
    model_compact_runs = _transfer_run_trace(
        per,
        model_sources_tuple,
        prefetch_per,
        current_plan.dic_indices,
        transfer_orders,
    )
    if (
        not failure
        and not np.array_equal(model_compact_runs, merged_runs)
    ):
        frame = int(np.flatnonzero(
            model_compact_runs != merged_runs)[0])
        failure = (
            f"frame {frame}: whole-run source choice changed runs "
            f"{int(merged_runs[frame])}->"
            f"{int(model_compact_runs[frame])}")
    model_runs = _transfer_run_trace(
        per,
        model_sources_tuple,
        prefetch_per,
        current_plan.dic_indices,
        transfer_orders,
        word_capacities=capacities,
    )
    model_block_lengths = stream_schedule.control_block_lengths(
        np.asarray(n_updates, np.int64),
        model_runs,
        cells=int(cells),
        audio_frame_bytes=int(audio_frame_bytes),
        update_lists=update_lists,
        frame_types=frame_types,
    )
    model_control_sectors = stream_schedule.control_sector_schedule(
        model_block_lengths)
    if (
        not failure
        and not np.array_equal(model_control_sectors, control_sectors)
    ):
        frame = int(np.flatnonzero(
            model_control_sectors != control_sectors)[0])
        failure = (
            f"frame {frame}: WordBuf ring-end descriptor split changes "
            f"control sectors {int(control_sectors[frame])}->"
            f"{int(model_control_sectors[frame])}")
    if not failure:
        # The construction loop used the same sector envelope. Preserve its
        # source/delivery choices, but replay and freeze the exact extra
        # four-byte descriptors introduced at physical ring boundaries.
        block_lengths = model_block_lengths

    prg_loads = np.zeros(frame_count, np.int64)
    wr0_loads = np.zeros(frame_count, np.int64)
    wr1_loads = np.zeros(frame_count, np.int64)
    for index, item in enumerate(items):
        source = int(state.sources[index])
        if item.mandatory_prg or source == PRG:
            prg_loads[item.frame] += item.count
        elif source == WORD:
            (wr1_loads if item.parity else wr0_loads)[item.frame] += (
                item.count)
    if frame_count:
        prg_loads[0] = int(np.asarray(current_plan.prg_loads, np.int64)[0])
        wr0_loads[0] = int(np.asarray(current_plan.wr0_loads, np.int64)[0])
        wr1_loads[0] = int(np.asarray(current_plan.wr1_loads, np.int64)[0])
    selected = (
        int(wr0_loads.sum()) - boot[0],
        int(wr1_loads.sum()) - boot[1],
    )
    if (
        not failure
        and any(value % PATTERNS_PER_SECTOR for value in selected)
    ):
        failure = f"refill selection is not sector exact: {selected}"
    payload_sectors = prg_payload_sectors + word_stage_sectors
    payload_frames = np.flatnonzero(payload_sectors > 0)
    evaluation_end = (
        min(frame_count, int(payload_frames[-1]) + 1)
        if payload_frames.size else frame_count
    )
    current_runs = int(_transfer_run_trace(
        per,
        current_plan.sources,
        prefetch_per,
        current_plan.dic_indices,
        transfer_orders,
        word_capacities=capacities,
    ).sum())
    if not failure:
        try:
            replay_frozen_schedule(
                prg_loads=prg_loads,
                wr0_loads=wr0_loads,
                wr1_loads=wr1_loads,
                block_lengths=block_lengths,
                payload_sectors=payload_sectors,
                control_sectors=control_sectors,
                word_stage_sectors=word_stage_sectors,
                fps=float(fps),
                prebuffer_patterns=prebuffer_target,
                prg_capacity_patterns=int(prg_capacity_patterns),
                word_capacities=capacities,
                boot_patterns=boot,
                f0_cold=int(np.asarray(
                    current_plan.prg_loads, np.int64)[0]),
            )
        except ValueError as exc:
            failure = f"exact frozen-route replay failed: {exc}"
    return WordBufRingPlan(
        feasible=not failure,
        failure=failure or "none",
        sources=model_sources_tuple,
        boot_patterns=boot,
        boot_end_frames=boot_end,
        selected_refill_patterns=selected,
        word_stage_sectors=word_stage_sectors,
        word_stage_patterns=word_stage_patterns,
        prg_payload_sectors=prg_payload_sectors,
        prg_payload_patterns=prg_payload_patterns,
        payload_sectors=payload_sectors,
        control_sectors=control_sectors,
        physical_sectors=physical_sectors,
        prg_loads=prg_loads,
        wr0_loads=wr0_loads,
        wr1_loads=wr1_loads,
        runs=model_runs,
        prg_occupancy=prg_trace,
        word_occupancy=word_trace,
        evaluation_end_frame=evaluation_end,
        prebuffer_patterns=prebuffer_target,
        current_runs=int(current_runs),
        source_merged_runs=int(merged_runs.sum()),
        model_runs=int(model_runs.sum()),
    )
