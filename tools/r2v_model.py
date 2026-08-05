#!/usr/bin/env python3
"""Main-CPU writes into VDP memory for one displayed frame."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

import av_config

PATTERN_WORDS = 16
SHORT_RUN_MAX_PATTERNS = 2
DMA_REPAIR_WORDS = 1
CRAM_WORDS = 64
NT_STAGE_PITCH = 64

# The H40 aperture the codec targets.
SCREEN_COLS = av_config.SCREEN_COLS
SCREEN_ROWS = av_config.SCREEN_ROWS

# DEBUG players publish this many cells. The first screen-width row uses the
# Window name table; any remaining cells use four-word sprite-table records.
DEBUG_HUD_WORDS = 43


def name_table_words(
    cols: int,
    rows: int,
    fps: float,
    *,
    debug_hud_words: int = DEBUG_HUD_WORDS,
) -> int:
    """Return the per-frame name-table and DEBUG HUD word count."""
    cols = int(cols)
    rows = int(rows)
    debug_hud_words = int(debug_hud_words)
    if cols <= 0 or rows <= 0:
        raise ValueError(f"invalid tile grid: {cols}x{rows}")
    if debug_hud_words < 0:
        raise ValueError("DEBUG HUD word count must be non-negative")
    # Keep fps in the public call shape: the physical publication workload no
    # longer changes with cadence.
    av_config.vsync_n_for_fps(fps)
    if cols > SCREEN_COLS or rows > SCREEN_ROWS:
        raise ValueError(
            f"tile grid {cols}x{rows} exceeds the H40 aperture")
    movie_words = (rows - 1) * NT_STAGE_PITCH + cols
    window_words = min(debug_hud_words, SCREEN_COLS)
    sprite_words = max(0, debug_hud_words - SCREEN_COLS) * 4
    return movie_words + window_words + sprite_words


def calculate_words(
    pattern_count: Sequence[int] | np.ndarray,
    run_count: Sequence[int] | np.ndarray,
    palette_switch: Sequence[int] | np.ndarray,
    name_table_word_count: int | Sequence[int] | np.ndarray,
) -> dict[str, np.ndarray]:
    """Calculate physical VDP-memory words by transfer component."""
    patterns = np.asarray(pattern_count, np.int64)
    runs = np.asarray(run_count, np.int64)
    palette = np.asarray(palette_switch, np.int64)
    name_table = np.broadcast_to(
        np.asarray(name_table_word_count, np.int64), patterns.shape,
    ).copy()
    if not (
        patterns.shape == runs.shape == palette.shape == name_table.shape
    ):
        raise ValueError("R2V workload columns must have matching shapes")
    if any(np.any(values < 0) for values in (
        patterns, runs, palette, name_table
    )):
        raise ValueError("R2V workload values must be non-negative")
    pattern_words = patterns * PATTERN_WORDS
    # Every pattern run is DMA-backed. Word-RAM transfers need the mandatory
    # first-word CPU repair; the ordinary whole-run path also performs the
    # same harmless repair for DicBuf runs.
    repair_words = runs * DMA_REPAIR_WORDS
    cram_words = (palette != 0).astype(np.int64) * CRAM_WORDS
    return {
        "words": pattern_words + repair_words + name_table + cram_words,
        "pattern_words": pattern_words,
        "repair_words": repair_words,
        "name_table_words": name_table,
        "cram_words": cram_words,
    }


def timed_scale_max(values: Sequence[int] | np.ndarray) -> int:
    """Use the exact observed maximum after untimed frame 0."""
    array = np.asarray(values, np.int64)
    return max(1, int(array[1:].max(initial=0)))
