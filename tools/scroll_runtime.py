#!/usr/bin/env python3
"""Pure helpers for encoding a fine-scrolled 64-by-32 Plane A viewport."""

from __future__ import annotations

import numpy as np

import scroll_plan


def aligned_rgb_tiles(
        image,
        state: scroll_plan.FrameScrollState,
        base_tiles,
        *,
        tile_size: int = scroll_plan.TILE_SIZE,
) -> np.ndarray:
    """Project a screen-space source frame onto primary plus guard plane tiles.

    Pixels inside the source viewport replace the corresponding rolling-plane
    pixels.  Pixels outside it retain ``base_tiles``.  Retention matters on an
    incoming edge: a five-pixel move reveals only five of the guard tile's
    eight columns, so the still-hidden three columns must not be invented.
    """

    source = np.asarray(image)
    if source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("scroll source must have shape (height, width, 3)")
    tile = int(tile_size)
    if tile <= 0:
        raise ValueError("scroll tile size must be positive")
    world = (*state.world_primary, *state.world_guard)
    base = np.asarray(base_tiles)
    expected = (len(world), tile, tile, 3)
    if base.shape != expected:
        raise ValueError(
            f"scroll base tiles have shape {base.shape}, expected {expected}")
    result = base.copy()
    height, width = source.shape[:2]
    for index, (world_row, world_column) in enumerate(world):
        plane_y = int(world_row) * tile
        plane_x = int(world_column) * tile
        for y in range(tile):
            source_y = plane_y + y + int(state.vscroll)
            if not 0 <= source_y < height:
                continue
            for x in range(tile):
                source_x = plane_x + x + int(state.hscroll)
                if 0 <= source_x < width:
                    result[index, y, x] = source[source_y, source_x]
    return result


def split_primary_guard(values, state: scroll_plan.FrameScrollState):
    """Split a primary-plus-guard vector using the state's exact cell counts."""

    array = np.asarray(values)
    primary = len(state.primary_cells)
    total = primary + len(state.guard_cells)
    if len(array) != total:
        raise ValueError(
            f"scroll vector has {len(array)} items, expected {total}")
    return array[:primary], array[primary:]
