#!/usr/bin/env python3
"""Model a refillable WordBuf ring without changing encoder decisions."""

from __future__ import annotations

import argparse
import csv
import pickle
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import pack_stream  # noqa: E402
import pattern_supply  # noqa: E402
import stream_schedule  # noqa: E402


UNKNOWN = -1
PRG = pattern_supply.SOURCE_PRG
WORD = pattern_supply.SOURCE_WR
MANDATORY_PRG = 3
PATTERNS_PER_SECTOR = stream_schedule.PATTERNS_PER_SECTOR
MAX_WORD_STAGE_SECTORS = 3


@dataclass(frozen=True)
class Item:
    """One source-indivisible physical run or mandatory Prg prefetch."""

    frame: int
    parity: int
    count: int
    updates: tuple[int, ...]
    mandatory_prg: bool = False
    word_safe: bool = True


@dataclass
class ModelState:
    """Mutable delivery state used by the sector transaction."""

    sources: np.ndarray
    delivered: np.ndarray
    prg_occupancy: int
    word_occupancy: list[int]
    word_reserved: list[int]
    prg_cursor: int
    word_cursor: list[int]


class Transaction:
    """Small rollback journal for one prospective physical payload sector."""

    def __init__(self, state: ModelState):
        self.state = state
        self.sources: dict[int, int] = {}
        self.delivered: dict[int, int] = {}
        self.scalars = (
            state.prg_occupancy,
            tuple(state.word_occupancy),
            tuple(state.word_reserved),
            state.prg_cursor,
            tuple(state.word_cursor),
        )

    def touch(self, index: int) -> None:
        if index not in self.sources:
            self.sources[index] = int(self.state.sources[index])
            self.delivered[index] = int(self.state.delivered[index])

    def rollback(self) -> None:
        for index, source in self.sources.items():
            self.state.sources[index] = source
            self.state.delivered[index] = self.delivered[index]
        (
            self.state.prg_occupancy,
            word_occupancy,
            word_reserved,
            self.state.prg_cursor,
            word_cursor,
        ) = self.scalars
        self.state.word_occupancy[:] = word_occupancy
        self.state.word_reserved[:] = word_reserved
        self.state.word_cursor[:] = word_cursor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.suffix.lower() != ".tsv":
        parser.error("--output must use the .tsv extension")
    return args


def build_items(
    per,
    prefetch_per,
    transfer_orders,
    current_plan,
) -> tuple[list[Item], list[list[int]], list[list[int]], list[int]]:
    """Build source-indivisible candidate runs in physical transfer order."""

    items: list[Item] = []
    frame_items: list[list[int]] = [[] for _ in per]
    parity_items: list[list[int]] = [[], []]
    current_word_counts: list[int] = []
    for frame, (
        (_cells, entries, colds),
        sources,
        dic_indices,
        transfer_order,
        prefetch,
    ) in enumerate(zip(
        per,
        current_plan.sources,
        current_plan.dic_indices,
        transfer_orders,
        prefetch_per,
        strict=True,
    )):
        if frame:
            cold_prefetch = sorted(
                (
                    entry for entry in prefetch
                    if bool(entry[1])
                ),
                key=lambda entry: int(entry[0]),
            )
            first_prefetch_slot = (
                int(cold_prefetch[0][0]) if cold_prefetch else None)
            run_updates: list[int] = []
            previous_slot: int | None = None
            for update in transfer_order:
                if not colds[update]:
                    raise AssertionError("transfer order contains a reuse")
                slot = (int(entries[update]) & 0x07FF) - pack_stream.BASE
                source = int(sources[update])
                candidate = source != pattern_supply.SOURCE_DIC
                continues = (
                    candidate
                    and bool(run_updates)
                    and previous_slot is not None
                    and slot == previous_slot + 1
                )
                if run_updates and not continues:
                    index = len(items)
                    item = Item(
                        frame, frame & 1, len(run_updates),
                        tuple(run_updates),
                        word_safe=(
                            first_prefetch_slot is None
                            or (
                                (int(entries[run_updates[-1]]) & 0x07FF)
                                - pack_stream.BASE + 1
                                != first_prefetch_slot
                            )
                        ))
                    items.append(item)
                    current_word_counts.append(sum(
                        int(sources[update]) == WORD
                        for update in run_updates
                    ))
                    frame_items[frame].append(index)
                    parity_items[frame & 1].append(index)
                    run_updates = []
                if candidate:
                    run_updates.append(int(update))
                previous_slot = slot if candidate else None
            if run_updates:
                index = len(items)
                item = Item(
                    frame, frame & 1, len(run_updates),
                    tuple(run_updates),
                    word_safe=(
                        first_prefetch_slot is None
                        or (
                            (int(entries[run_updates[-1]]) & 0x07FF)
                            - pack_stream.BASE + 1
                            != first_prefetch_slot
                        )
                    ))
                items.append(item)
                current_word_counts.append(sum(
                    int(sources[update]) == WORD
                    for update in run_updates
                ))
                frame_items[frame].append(index)
                parity_items[frame & 1].append(index)

            prefetch_count = len(cold_prefetch)
            if prefetch_count:
                index = len(items)
                items.append(Item(
                    frame, frame & 1, prefetch_count, (),
                    mandatory_prg=True))
                current_word_counts.append(0)
                frame_items[frame].append(index)
    return items, frame_items, parity_items, current_word_counts


def assign_boot_word(
    items: list[Item],
    parity_items: list[list[int]],
    state: ModelState,
    capacities: tuple[int, int],
) -> tuple[int, int]:
    """Fill each boot WordBuf with earliest complete physical runs."""

    loaded = [0, 0]
    for parity in (0, 1):
        remaining = int(capacities[parity])
        for index in parity_items[parity]:
            item = items[index]
            if (
                item.mandatory_prg
                or not item.word_safe
                or item.count > remaining
            ):
                continue
            state.sources[index] = WORD
            state.delivered[index] = item.count
            state.word_occupancy[parity] += item.count
            loaded[parity] += item.count
            remaining -= item.count
            if not remaining:
                break
    return loaded[0], loaded[1]


def assign_refill_sources(
    items: list[Item],
    parity_items: list[list[int]],
    current_word_counts: list[int],
    state: ModelState,
    targets: tuple[int, int],
    baseline_occupancy: np.ndarray,
) -> tuple[int, int]:
    """Select pressure runs for one additional timed WordBuf turn."""

    selected = [0, 0]
    for parity in (0, 1):
        boot_frames = [
            items[index].frame
            for index in parity_items[parity]
            if int(state.sources[index]) == WORD
        ]
        boot_end = max(boot_frames, default=0)
        candidates = [
            index
            for index in parity_items[parity]
            if (
                int(state.sources[index]) == UNKNOWN
                and items[index].frame > boot_end
                and items[index].word_safe
                and current_word_counts[index] > 0
            )
        ]
        candidates.sort(key=lambda index: (
            items[index].frame,
            -current_word_counts[index] / items[index].count,
            int(baseline_occupancy[items[index].frame]),
            index,
        ))
        for index in candidates:
            if selected[parity] >= int(targets[parity]):
                break
            if (
                selected[parity] + items[index].count
                > int(targets[parity])
            ):
                continue
            state.sources[index] = WORD
            selected[parity] += items[index].count

    # Every remaining visible run is ordinary Prg. Fixing the sources before
    # delivery lets both FIFO streams retain chronological order.
    state.sources[state.sources == UNKNOWN] = PRG
    return selected[0], selected[1]


def deliver_prg(
    items: list[Item],
    state: ModelState,
    capacity: int,
    amount: int,
    transaction: Transaction,
) -> int:
    """Deliver chronological Prg work, claiming unknown runs for Prg."""

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
        room = min(
            amount - delivered,
            capacity - state.prg_occupancy,
            item.count - int(state.delivered[index]),
        )
        if room <= 0:
            break
        state.delivered[index] += room
        state.prg_occupancy += room
        delivered += room
        if int(state.delivered[index]) == item.count:
            state.prg_cursor += 1
    return delivered


def deliver_word(
    frame: int,
    parity: int,
    items: list[Item],
    parity_items: list[list[int]],
    state: ModelState,
    capacity: int,
    amount: int,
    transaction: Transaction,
    *,
    allow_assign: bool,
) -> int:
    """Stage complete-run Word work into the currently owned physical bank."""

    delivered = 0
    indices = parity_items[parity]
    while delivered < amount:
        while state.word_cursor[parity] < len(indices):
            index = indices[state.word_cursor[parity]]
            item = items[index]
            source = int(state.sources[index])
            if source == PRG:
                state.word_cursor[parity] += 1
                continue
            if source == WORD and int(state.delivered[index]) >= item.count:
                state.word_cursor[parity] += 1
                continue
            if source == UNKNOWN:
                if not allow_assign:
                    return delivered
                free = (
                    capacity
                    - state.word_occupancy[parity]
                    - state.word_reserved[parity]
                )
                if (
                    item.frame <= frame
                    or item.count > free
                    or (
                        item.count > amount - delivered
                        and item.frame < frame + 4
                    )
                ):
                    transaction.touch(index)
                    state.sources[index] = PRG
                    state.word_cursor[parity] += 1
                    continue
            break
        if state.word_cursor[parity] >= len(indices):
            break
        index = indices[state.word_cursor[parity]]
        item = items[index]
        transaction.touch(index)
        if int(state.sources[index]) == UNKNOWN:
            state.sources[index] = WORD
            state.word_reserved[parity] += item.count
        room = min(
            amount - delivered,
            capacity - state.word_occupancy[parity],
            item.count - int(state.delivered[index]),
        )
        if room <= 0:
            break
        state.delivered[index] += room
        state.word_occupancy[parity] += room
        state.word_reserved[parity] -= room
        delivered += room
        if int(state.delivered[index]) == item.count:
            state.word_cursor[parity] += 1
    return delivered


def remaining_patterns(items: list[Item], state: ModelState) -> int:
    return sum(
        item.count - int(state.delivered[index])
        for index, item in enumerate(items)
    )


def remaining_source_patterns(
    items: list[Item],
    state: ModelState,
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


def run_model(log: dict) -> dict[str, object]:
    pack_stream.configure_from_log(log)
    (
        per,
        prefetch_per,
        transfer_orders,
        _n_load,
        n_upd,
        _pal_w,
        patterns,
        _tearing,
    ) = pack_stream.resolve(log, int(log["vram_tiles"]))
    layout = pattern_supply.word_ram_layout(
        len(per), pack_stream.C_CELLS, int(log["max_cold"]))
    current = pattern_supply.plan_supply(
        log,
        per,
        patterns,
        prefetch_per=prefetch_per,
        transfer_orders=transfer_orders,
        wr0_patterns=layout.wr0_patterns,
        wr1_patterns=layout.wr1_patterns,
    )
    (
        items,
        frame_items,
        parity_items,
        current_word_counts,
    ) = build_items(
        per, prefetch_per, transfer_orders, current)
    sources = np.full(len(items), UNKNOWN, np.int8)
    sources[np.asarray(
        [item.mandatory_prg for item in items], bool)] = MANDATORY_PRG
    state = ModelState(
        sources=sources,
        delivered=np.zeros(len(items), np.int64),
        prg_occupancy=0,
        word_occupancy=[0, 0],
        word_reserved=[0, 0],
        prg_cursor=0,
        word_cursor=[0, 0],
    )
    capacities = (layout.wr0_patterns, layout.wr1_patterns)
    boot_word = assign_boot_word(
        items, parity_items, state, capacities)
    boot_end_frames = tuple(
        max(
            (
                items[index].frame
                for index in parity_items[parity]
                if int(state.sources[index]) == WORD
            ),
            default=0,
        )
        for parity in (0, 1)
    )
    current_word_totals = (
        int(np.asarray(current.wr0_loads, np.int64).sum()),
        int(np.asarray(current.wr1_loads, np.int64).sum()),
    )
    refill_selected = assign_refill_sources(
        items,
        parity_items,
        current_word_counts,
        state,
        current_word_totals,
        np.asarray(
            log["stream_schedule"]["ring_occupancy"], np.int64),
    )

    prg_normal = int(log["prg_buf_kb"]) * 1024 // 32
    bootstrap = Transaction(state)
    delivered = deliver_prg(
        items, state, prg_normal, prg_normal, bootstrap)
    if delivered != prg_normal:
        raise AssertionError(
            f"prospective Prg prebuffer reached only {delivered} patterns")

    # Whole-run assignment preserves the source-merged run count, so no extra
    # descriptor reservation is hidden. Reserved routing bits carry the count
    # of complete Word payload sectors; no control record is added.
    merged_sources = tuple(
        tuple(
            PRG if source == WORD else source
            for source in frame
        )
        for frame in current.sources
    )
    merged_runs = np.asarray([
        len(pack_stream.sourced_transfer_runs(
            entries,
            colds,
            frame_sources,
            prefetch,
            dic_indices,
            transfer_order,
        ))
        for (
            (_cells, entries, colds),
            frame_sources,
            prefetch,
            dic_indices,
            transfer_order,
        ) in zip(
            per,
            merged_sources,
            prefetch_per,
            current.dic_indices,
            transfer_orders,
            strict=True,
        )
    ], np.int64)
    block_lengths = stream_schedule.control_block_lengths(
        np.asarray(n_upd, np.int64),
        merged_runs,
        cells=pack_stream.C_CELLS,
        audio_frame_bytes=pack_stream.AUDIO_CONTROL,
    )
    control_sectors = stream_schedule.control_sector_schedule(block_lengths)
    physical_sectors = stream_schedule.rate_deltas(
        len(per), float(log["fps"]))
    payload_capacity_sectors = physical_sectors - control_sectors
    if np.any(payload_capacity_sectors < 0):
        frame = int(np.flatnonzero(payload_capacity_sectors < 0)[0])
        raise AssertionError(
            f"frame {frame}: prospective control exceeds fixed CD time")

    prg_trace = np.zeros(len(per), np.int64)
    word_trace = np.zeros((len(per), 2), np.int64)
    staged_word = np.zeros(len(per), np.int64)
    word_stage_sectors = np.zeros(len(per), np.int64)
    delivered_prg = np.zeros(len(per), np.int64)
    payload_sectors = np.zeros(len(per), np.int64)
    failure = ""
    for frame in range(len(per)):
        for index in frame_items[frame]:
            item = items[index]
            if int(state.delivered[index]) != item.count:
                failure = (
                    f"frame {frame}: source {int(state.sources[index])} "
                    f"delivered {int(state.delivered[index])}/{item.count}")
                break
        if failure:
            break

        for _sector in range(int(payload_capacity_sectors[frame])):
            transaction = Transaction(state)
            prg_count = deliver_prg(
                items,
                state,
                prg_normal,
                PATTERNS_PER_SECTOR,
                transaction,
            )
            prg_remaining = remaining_source_patterns(
                items, state, PRG) + remaining_source_patterns(
                    items, state, MANDATORY_PRG)
            if prg_count == PATTERNS_PER_SECTOR:
                payload_sectors[frame] += 1
                delivered_prg[frame] += prg_count
                continue
            if prg_count and prg_remaining == 0:
                state.prg_occupancy += PATTERNS_PER_SECTOR - prg_count
                payload_sectors[frame] += 1
                delivered_prg[frame] += prg_count
                continue
            transaction.rollback()

            if word_stage_sectors[frame] >= MAX_WORD_STAGE_SECTORS:
                break
            transaction = Transaction(state)
            word_count = deliver_word(
                frame,
                frame & 1,
                items,
                parity_items,
                state,
                capacities[frame & 1],
                PATTERNS_PER_SECTOR,
                transaction,
                allow_assign=False,
            )
            word_remaining = remaining_source_patterns(
                items,
                state,
                WORD,
                frame & 1,
            )
            if word_count == PATTERNS_PER_SECTOR:
                pass
            elif word_count and word_remaining == 0:
                pad = PATTERNS_PER_SECTOR - word_count
                if (
                    state.word_occupancy[frame & 1] + pad
                    > capacities[frame & 1]
                ):
                    transaction.rollback()
                    break
                state.word_occupancy[frame & 1] += pad
            else:
                transaction.rollback()
                break
            payload_sectors[frame] += 1
            word_stage_sectors[frame] += 1
            staged_word[frame] += word_count

        for index in frame_items[frame]:
            item = items[index]
            source = int(state.sources[index])
            if source in (PRG, MANDATORY_PRG):
                state.prg_occupancy -= item.count
            elif source == WORD:
                state.word_occupancy[item.parity] -= item.count
            else:
                raise AssertionError(
                    f"frame {frame}: item source was never assigned")
        if min(state.prg_occupancy, *state.word_occupancy) < 0:
            raise AssertionError("prospective ring occupancy became negative")
        prg_trace[frame] = state.prg_occupancy
        word_trace[frame] = state.word_occupancy

    model_sources = [
        [int(source) for source in frame]
        for frame in current.sources
    ]
    for index, item in enumerate(items):
        if item.mandatory_prg:
            continue
        source = int(state.sources[index])
        if source == UNKNOWN:
            source = PRG
        for update in item.updates:
            model_sources[item.frame][update] = source
    model_runs = np.asarray([
        len(pack_stream.sourced_transfer_runs(
            entries,
            colds,
            frame_sources,
            prefetch,
            dic_indices,
            transfer_order,
        ))
        for (
            (_cells, entries, colds),
            frame_sources,
            prefetch,
            dic_indices,
            transfer_order,
        ) in zip(
            per,
            model_sources,
            prefetch_per,
            current.dic_indices,
            transfer_orders,
            strict=True,
        )
    ], np.int64)
    if not failure and not np.array_equal(model_runs, merged_runs):
        frame = int(np.flatnonzero(model_runs != merged_runs)[0])
        raise AssertionError(
            f"whole-run assignment changed frame {frame} runs: "
            f"{int(merged_runs[frame])} -> {int(model_runs[frame])}")

    candidate_word = np.zeros((len(per), 2), np.int64)
    candidate_prg = np.zeros(len(per), np.int64)
    for index, item in enumerate(items):
        source = int(state.sources[index])
        if item.mandatory_prg or source in (PRG, MANDATORY_PRG, UNKNOWN):
            candidate_prg[item.frame] += item.count
        else:
            candidate_word[item.frame, item.parity] += item.count

    baseline = log["stream_schedule"]
    current_runs = np.asarray(
        log["pattern_transfers"]["runs"], np.int64)
    timed_word_total = int(candidate_word.sum()) - sum(boot_word)
    payload_frames = np.flatnonzero(payload_sectors > 0)
    evaluation_end = (
        min(len(per), int(payload_frames[-1]) + 1)
        if payload_frames.size else len(per)
    )
    evaluation_slice = slice(1, max(2, evaluation_end))
    combined_trace = prg_trace + word_trace.sum(axis=1)
    return {
        "profile": str(log["config"]["profile"]["path"]),
        "frames": len(per),
        "failure": failure or "none",
        "prg_normal_patterns": prg_normal,
        "baseline_prg_min_patterns": int(
            baseline["ring_min_evaluation"]),
        "model_evaluation_end_frame": evaluation_end,
        "model_prg_min_evaluation_patterns": int(
            prg_trace[evaluation_slice].min(initial=prg_normal)),
        "model_prg_min_full_patterns": int(
            prg_trace[1:].min(initial=prg_normal)),
        "model_prg_peak_patterns": int(prg_trace.max(initial=0)),
        "model_combined_min_evaluation_patterns": int(
            combined_trace[evaluation_slice].min(initial=prg_normal)),
        "wr0_capacity": capacities[0],
        "wr0_boot_patterns": boot_word[0],
        "wr0_boot_end_frame": boot_end_frames[0],
        "wr0_model_min_patterns": int(
            word_trace[1:, 0].min(initial=boot_word[0])),
        "wr0_model_peak_patterns": int(
            word_trace[:, 0].max(initial=boot_word[0])),
        "wr1_capacity": capacities[1],
        "wr1_boot_patterns": boot_word[1],
        "wr1_boot_end_frame": boot_end_frames[1],
        "wr1_model_min_patterns": int(
            word_trace[1:, 1].min(initial=boot_word[1])),
        "wr1_model_peak_patterns": int(
            word_trace[:, 1].max(initial=boot_word[1])),
        "timed_word_refill_patterns": timed_word_total,
        "staged_word_patterns": int(staged_word.sum()),
        "selected_refill_patterns": sum(refill_selected),
        "timed_word_refill_frames": int(np.count_nonzero(staged_word)),
        "timed_word_refill_max": int(staged_word.max(initial=0)),
        "word_stage_sector_max": int(
            word_stage_sectors.max(initial=0)),
        "payload_sectors": int(payload_sectors.sum()),
        "payload_sector_capacity": int(
            payload_capacity_sectors.clip(min=0).sum()),
        "current_runs": int(current_runs.sum()),
        "source_merged_runs": int(merged_runs.sum()),
        "model_runs": int(model_runs.sum()),
        "model_extra_runs": int(model_runs.sum() - merged_runs.sum()),
        "model_word_cold_total": int(candidate_word.sum()),
        "model_prg_cold_total": int(candidate_prg.sum()),
    }


def main() -> None:
    args = parse_args()
    if not args.decisions.is_file():
        raise SystemExit(f"decision log does not exist: {args.decisions}")
    log = pickle.loads(args.decisions.read_bytes())
    row = run_model(log)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(row),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerow(row)
    print(f"TSV: {args.output}")


if __name__ == "__main__":
    main()
