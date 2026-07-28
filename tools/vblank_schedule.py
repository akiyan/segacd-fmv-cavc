#!/usr/bin/env python3
"""Plan deterministic per-VBlank Main-CPU pattern-transfer shares.

The packed control stream carries one fixed-size table of pattern counts.  Each
count says how many consecutive cold patterns Main must transfer in that
VBlank.  The player therefore executes an encoder-authored schedule instead of
guessing a split from payload words alone.

The work model uses DMA-word equivalents.  Pattern payload is charged at 16
words per tile, every run/chunk pays setup/repair time, every VBlank keeps a
fixed guard, and the final group reserves the name-table/HUD/CRAM/flip work
that shares its blank.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Sequence

import av_config


WORDS_PER_PATTERN = 16
MAX_VBLANK_GROUPS = 8
GROUP_COUNT_BYTES = MAX_VBLANK_GROUPS * 2

# Measured blanking DMA throughput from tools/layout_preview.py.
VBLANK_WORK_LIMIT = {
    "H32": 6346 // 2,
    "H40": 7790 // 2,
    "MODE4": 11690 // 2,
}

# The p119 H40 trace proved that a nominal 3,400-word share with only five DMA
# chunks and one short CPU run already exits in active display.  Charging 128
# fixed words plus 64 per issued chunk puts that exact case just beyond the
# measured 3,895-word physical blank while retaining the real payload cost.
GROUP_FIXED_WORK = 128
TRANSFER_CHUNK_WORK = 64

# Fixed-N H40 uses one 64x28 Main-RAM name-table DMA in the final VBlank.
NT_STAGE_WORDS = 64 * 28
NT_DMA_SETUP_WORK = 64
DEBUG_STAGE_WORK = 63
FLIP_GUARD_WORK = 128
CRAM_REPLACE_WORK = 128
H40_NT_FINAL_WORK = (
    NT_STAGE_WORDS
    + NT_DMA_SETUP_WORK
    + DEBUG_STAGE_WORK
    + FLIP_GUARD_WORK
)


@dataclass(frozen=True)
class VBlankPlan:
    """One frame's fixed-width encoded VBlank plan."""

    nominal_groups: int
    groups: int
    patterns: tuple[int, ...]
    pattern_work: tuple[int, ...]
    final_reserved_work: int

    @property
    def extra_groups(self) -> int:
        return self.groups - self.nominal_groups


def nominal_group_counts(frame_count: int, fps: float) -> tuple[int, ...]:
    """Return the intended display-VBlank interval for every frame.

    Frame 0 is an untimed boot construction.  Integer NTSC divisors use their
    authoritative fixed N.  Delivery-paced rates use rounded cumulative
    deadlines; 24 fps therefore naturally alternates two and three VBlanks
    without being rounded to fixed N2.
    """
    count = int(frame_count)
    if count < 0:
        raise ValueError("frame_count must not be negative")
    if not count:
        return ()
    fixed = av_config.fixed_vblank_interval(fps)
    if fixed is not None:
        return (1,) + (int(fixed),) * (count - 1)

    source_rate = Fraction(str(float(fps)))
    if source_rate <= 0:
        raise ValueError(f"fps must be positive, got {fps!r}")
    interval = Fraction(60_000, 1001) / source_rate
    result = [1]
    previous_deadline = 0
    for frame in range(1, count):
        scaled = frame * interval
        deadline = (2 * scaled.numerator + scaled.denominator) // (
            2 * scaled.denominator)
        groups = deadline - previous_deadline
        if not 1 <= groups <= av_config.MAX_FIXED_VBLANK_INTERVAL:
            raise ValueError(
                f"frame {frame}: delivery-paced cadence needs {groups} "
                "VBlanks outside the supported 1..4 range")
        result.append(groups)
        previous_deadline = deadline
    return tuple(result)


def uses_h40_nt_dma(mode: str, fps: float) -> bool:
    """Match the specialized player's fixed-cadence H40 NT-DMA build."""
    return (
        str(mode).upper() == "H40"
        and av_config.uses_fixed_n_cadence(fps)
    )


def final_reserved_work(
        mode: str, *, nt_dma_flip: bool, palette_switch: bool,
) -> int:
    """Return non-pattern work that must coexist with the last group."""
    normalized = str(mode).upper()
    if normalized not in VBLANK_WORK_LIMIT:
        raise ValueError(f"unsupported display mode: {mode!r}")
    reserve = H40_NT_FINAL_WORK if nt_dma_flip else FLIP_GUARD_WORK
    if palette_switch:
        reserve += CRAM_REPLACE_WORK
    return reserve


def _validated_run_counts(
        runs: Sequence[Sequence[int]],
) -> tuple[int, ...]:
    counts = []
    for index, run in enumerate(runs):
        if len(run) < 2:
            raise ValueError(f"run {index} has no count")
        count = int(run[1])
        if count <= 0:
            raise ValueError(f"run {index} has invalid count {count}")
        counts.append(count)
    return tuple(counts)


def _take_group(
        run_counts: tuple[int, ...],
        run_index: int,
        run_offset: int,
        capacity: int,
) -> tuple[int, int, int, int]:
    """Greedily take the largest safe ordered prefix for one VBlank.

    One- and two-pattern source runs stay intact.  Longer runs may be divided
    at an encoder-authored boundary; each resulting chunk pays its own setup.
    """
    work = GROUP_FIXED_WORK
    patterns = 0
    index = int(run_index)
    offset = int(run_offset)
    while index < len(run_counts):
        original = run_counts[index]
        remaining = original - offset
        room = int(capacity) - work - TRANSFER_CHUNK_WORK
        take = min(remaining, max(0, room // WORDS_PER_PATTERN))
        if take <= 0:
            break
        if original <= 2 and offset == 0 and take < remaining:
            break
        work += TRANSFER_CHUNK_WORK + take * WORDS_PER_PATTERN
        patterns += take
        offset += take
        if offset == original:
            index += 1
            offset = 0
            continue
        break
    return patterns, work, index, offset


def plan_frame(
        runs: Sequence[Sequence[int]],
        nominal_groups: int,
        *,
        mode: str,
        nt_dma_flip: bool,
        palette_switch: bool = False,
) -> VBlankPlan:
    """Partition ordered run payload into safe, deterministic VBlank groups.

    The nominal cadence is tried first.  If its physical blanks cannot contain
    the measured work, extra groups are added rather than letting a transfer
    spill into active display.  The fixed eight-word table keeps control-block
    size independent of this decision.
    """
    normalized = str(mode).upper()
    try:
        limit = VBLANK_WORK_LIMIT[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported display mode: {mode!r}") from exc
    nominal = int(nominal_groups)
    if not 1 <= nominal <= MAX_VBLANK_GROUPS:
        raise ValueError(
            f"nominal VBlank groups must be within 1..{MAX_VBLANK_GROUPS}")
    run_counts = _validated_run_counts(runs)
    reserve = final_reserved_work(
        normalized,
        nt_dma_flip=bool(nt_dma_flip),
        palette_switch=bool(palette_switch),
    )
    if reserve + GROUP_FIXED_WORK > limit:
        raise ValueError(
            f"{normalized} final VBlank reserve {reserve} leaves no group room")

    for group_count in range(nominal, MAX_VBLANK_GROUPS + 1):
        index = 0
        offset = 0
        counts: list[int] = []
        works: list[int] = []
        for group in range(group_count):
            capacity = limit - (reserve if group == group_count - 1 else 0)
            patterns, work, index, offset = _take_group(
                run_counts, index, offset, capacity)
            counts.append(patterns)
            works.append(work)
        if index == len(run_counts) and offset == 0:
            padded_counts = tuple(
                counts + [0] * (MAX_VBLANK_GROUPS - group_count))
            padded_work = tuple(
                works + [0] * (MAX_VBLANK_GROUPS - group_count))
            if sum(padded_counts) != sum(run_counts):
                raise AssertionError("VBlank plan lost pattern payload")
            return VBlankPlan(
                nominal_groups=nominal,
                groups=group_count,
                patterns=padded_counts,
                pattern_work=padded_work,
                final_reserved_work=reserve,
            )

    total = sum(run_counts)
    raise ValueError(
        f"{normalized} cannot schedule {total} patterns across "
        f"{MAX_VBLANK_GROUPS} VBlanks with {len(run_counts)} runs")
