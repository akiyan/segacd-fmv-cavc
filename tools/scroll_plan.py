#!/usr/bin/env python3
"""Adoption windows and the exact 64-by-32 rolling Plane A model."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping, Sequence

import numpy as np

import scroll_frames


PLANE_COLUMNS = 64
PLANE_ROWS = 32
TILE_SIZE = 8
# Vertical windows roll the plane's 32 rows behind the viewport, so they need
# the full-screen H40 28-row grid; a letterboxed grid would scroll its visible
# letterbox rows.  Horizontal windows only need the full-width 40-column grid.
VERTICAL_VIEWPORT_ROWS = 28


@dataclass(frozen=True)
class ScrollWindow:
    """One automatically adopted, tile-phase-safe scroll interval.

    ``anchor`` is displayed at position zero.  Motion controls start on the
    following frame.  The final position is always tile aligned, allowing the
    Main CPU to copy the current viewport back to its ordinary 40-by-N shadow
    without re-encoding patterns.
    """

    anchor: int
    end: int
    axis: str
    deltas: tuple[int, ...]
    positions: tuple[int, ...]
    detector_start: int
    support: float
    multiframe_support: float
    adoption_gain: float
    beneficial_fraction: float
    overlap_rmse_p95: float

    @property
    def movements(self) -> int:
        return self.end - self.anchor

    @property
    def final_position(self) -> int:
        return int(self.positions[-1]) if self.positions else 0

    def position_at(self, frame: int) -> int:
        value = int(frame)
        if not self.anchor <= value <= self.end:
            raise ValueError("frame is outside the scroll window")
        return int(self.positions[value - self.anchor])


@dataclass(frozen=True)
class FrameScrollState:
    """Absolute VDP position and rolling-plane cells for one movie frame."""

    frame: int
    axis: str
    position: int
    primary_cells: tuple[int, ...]
    guard_cells: tuple[int, ...]
    world_primary: tuple[tuple[int, int], ...]
    world_guard: tuple[tuple[int, int], ...]

    @property
    def hscroll(self) -> int:
        return self.position if self.axis == scroll_frames.AXIS_HORIZONTAL else 0

    @property
    def vscroll(self) -> int:
        return self.position if self.axis == scroll_frames.AXIS_VERTICAL else 0


def _window_metrics(
        rows: Sequence[scroll_frames.AdoptionMeasurement],
) -> tuple[float, float, float]:
    # Window economics use the graded per-tile costs: a fractional-speed pan
    # keeps a mild subpixel residual on part of its frames, which the codec
    # carries as an approximation instead of reloading, so those tiles must
    # not be priced like hard content changes.  The changed-tile counts stay
    # in the trace for diagnostics only.
    if not rows:
        return 0.0, 0.0, float("inf")
    fixed = sum(float(row.fixed_cost) for row in rows)
    scrolling = sum(float(row.scroll_cost) for row in rows)
    gain = fixed / max(scrolling, 1.0)
    beneficial = float(np.mean([
        row.scroll_cost < row.fixed_cost for row in rows
    ]))
    rmse95 = float(np.percentile(
        [row.overlap_rmse for row in rows], 95))
    return float(gain), beneficial, rmse95


def _candidate_runs(
        segment: scroll_frames.ScrollSegment,
        forbidden: frozenset[int],
) -> tuple[tuple[int, int], ...]:
    """Return inclusive transition-frame runs outside forbidden controls."""

    runs = []
    start = None
    for frame in range(segment.start, segment.end + 1):
        if frame in forbidden:
            if start is not None:
                runs.append((start, frame - 1))
                start = None
            continue
        if start is None:
            start = frame
    if start is not None:
        runs.append((start, segment.end))
    return tuple(runs)


def select_windows(
        segments: Iterable[scroll_frames.ScrollSegment],
        measurements: Mapping[int, scroll_frames.AdoptionMeasurement],
    *,
    fps: float,
    forbidden_frames: Iterable[int] = (),
    minimum_movements: int = 16,
        minimum_gain: float = 2.0,
        minimum_beneficial_fraction: float = 0.80,
        # Adoption quality floor on the detector's block-vote agreement. A
        # low-support pan mixes independent motion into the "pan", and every
        # adopted window also spends the shared WordBuf guard reserve and
        # per-frame Prg allowance, so a marginal window can starve a strong
        # one's mandatory guard column. 0.85 keeps the measured Lunar windows
        # (0.997) while rejecting the mixed 0.74 dolly shot.
        minimum_support: float = 0.85,
        # A moving background with an independent foreground layer (feathers,
        # subtitles, lip flaps) keeps a real overlap residual even when the
        # pan itself is exact; the beneficial-fraction and gain gates already
        # reject windows the scroll would not improve. 28 admits the measured
        # Lunar vertical rise (p95 ~= 24) while still refusing cut-like noise.
        maximum_overlap_rmse_p95: float = 28.0,
        tile_size: int = TILE_SIZE,
) -> tuple[ScrollWindow, ...]:
    """Choose sustained, useful, tile-phase-safe windows without time hints."""

    rate = float(fps)
    if not np.isfinite(rate) or rate <= 0:
        raise ValueError("fps must be positive")
    minimum = int(minimum_movements)
    tile = int(tile_size)
    if minimum < 1 or tile < 1:
        raise ValueError("minimum_movements and tile_size must be positive")
    forbidden = frozenset(int(frame) for frame in forbidden_frames)
    selected = []
    for segment in sorted(segments, key=lambda item: (item.start, item.end)):
        for run_start, run_end in _candidate_runs(segment, forbidden):
            # The detector has already confirmed the complete multiframe run
            # offline.  Seed from the last frame before motion so the normal
            # codec never has to survive a screen-space warm-up while the
            # camera is already moving.  Trim only the tail needed to end on
            # an exact tile phase; that makes the later logical rebase free.
            anchor = run_start - 1
            if anchor < 0 or anchor in forbidden:
                continue
            deltas = None
            positions = None
            end = None
            for candidate_end in range(run_end, anchor + minimum - 1, -1):
                movement = tuple(
                    int(segment.deltas[frame - segment.start])
                    for frame in range(anchor + 1, candidate_end + 1)
                )
                cumulative = tuple(int(value) for value in np.cumsum(movement))
                if cumulative and cumulative[-1] % tile == 0:
                    end = candidate_end
                    deltas = movement
                    positions = (0, *cumulative)
                    break
            if end is None:
                continue
            rows = [
                measurements[frame]
                for frame in range(anchor + 1, end + 1)
                if frame in measurements
            ]
            if len(rows) != end - anchor:
                continue
            gain, beneficial, rmse95 = _window_metrics(rows)
            if (
                float(segment.support) < float(minimum_support)
                or gain < float(minimum_gain)
                or beneficial < float(minimum_beneficial_fraction)
                or rmse95 > float(maximum_overlap_rmse_p95)
            ):
                continue
            selected.append(ScrollWindow(
                anchor=int(anchor), end=int(end), axis=segment.axis,
                deltas=tuple(deltas), positions=tuple(positions),
                detector_start=int(segment.start), support=float(segment.support),
                multiframe_support=float(segment.multiframe_support),
                adoption_gain=gain, beneficial_fraction=beneficial,
                overlap_rmse_p95=rmse95,
            ))
    return tuple(selected)


def plane_cell(world_row: int, world_column: int) -> int:
    """Map an unbounded world tile to the VDP's 64-by-32 Plane A ring."""

    return (
        (int(world_row) % PLANE_ROWS) * PLANE_COLUMNS
        + int(world_column) % PLANE_COLUMNS
    )


def normal_plane_cells(columns: int, rows: int) -> tuple[int, ...]:
    """Map the ordinary logical shadow into Plane A's top-left physical area."""

    cols = int(columns)
    line_count = int(rows)
    if not 0 < cols <= PLANE_COLUMNS or not 0 < line_count <= PLANE_ROWS:
        raise ValueError("normal shadow exceeds the physical scroll plane")
    return tuple(
        plane_cell(row, column)
        for row in range(line_count)
        for column in range(cols)
    )


def frame_state(
        window: ScrollWindow,
        frame: int,
        *,
        columns: int,
        rows: int,
) -> FrameScrollState:
    """Return primary viewport and one incoming guard edge for a frame."""

    value = int(frame)
    position = window.position_at(value)
    cols = int(columns)
    line_count = int(rows)
    if cols <= 0 or line_count <= 0:
        raise ValueError("scroll geometry must be positive")
    if cols > PLANE_COLUMNS or line_count > PLANE_ROWS:
        raise ValueError("scroll viewport exceeds the physical plane")
    offset = value - window.anchor
    if offset > 0:
        movement = int(window.deltas[offset - 1])
    elif window.deltas:
        movement = int(window.deltas[0])
    else:
        movement = -1

    if window.axis == scroll_frames.AXIS_HORIZONTAL:
        first_column = math.floor(-position / TILE_SIZE)
        primary_world = tuple(
            (row, first_column + column)
            for row in range(line_count)
            for column in range(cols)
        )
        guard_column = (
            first_column + cols if movement <= 0 else first_column - 1)
        guard_world = tuple(
            (row, guard_column) for row in range(line_count))
    elif window.axis == scroll_frames.AXIS_VERTICAL:
        first_row = math.floor(-position / TILE_SIZE)
        primary_world = tuple(
            (first_row + row, column)
            for row in range(line_count)
            for column in range(cols)
        )
        guard_row = first_row + line_count if movement <= 0 else first_row - 1
        guard_world = tuple(
            (guard_row, column) for column in range(cols))
    else:
        raise ValueError(f"unsupported scroll axis: {window.axis!r}")
    return FrameScrollState(
        frame=value, axis=window.axis, position=position,
        primary_cells=tuple(plane_cell(*item) for item in primary_world),
        guard_cells=tuple(plane_cell(*item) for item in guard_world),
        world_primary=primary_world, world_guard=guard_world,
    )


def position_state(
        frame: int,
        axis: str,
        position: int,
        delta: int = -1,
        *,
        columns: int,
        rows: int,
) -> FrameScrollState:
    """Build a frame state from an already validated absolute control value."""

    value = int(position)
    window = ScrollWindow(
        anchor=int(frame),
        end=int(frame),
        axis=str(axis),
        deltas=(int(delta),),
        positions=(value,),
        detector_start=int(frame),
        support=1.0,
        multiframe_support=1.0,
        adoption_gain=1.0,
        beneficial_fraction=1.0,
        overlap_rmse_p95=0.0,
    )
    return frame_state(
        window, int(frame), columns=int(columns), rows=int(rows))


def build_frame_states(
        windows: Sequence[ScrollWindow],
        *,
        columns: int,
        rows: int,
) -> dict[int, FrameScrollState]:
    """Expand non-overlapping windows into absolute per-frame states."""

    result = {}
    for window in windows:
        for frame in range(window.anchor, window.end + 1):
            if frame in result:
                raise ValueError("automatic scroll windows overlap")
            result[frame] = frame_state(
                window, frame, columns=columns, rows=rows)
    return result


class RollingPlane:
    """Exact name-table/pattern model for Main CPU rolling-shadow tests."""

    def __init__(self, empty=-1):
        self.empty = int(empty)
        self.entries = np.full(
            (PLANE_ROWS, PLANE_COLUMNS), self.empty, np.int64)

    def update(self, world_cells, entries) -> None:
        cells = tuple((int(row), int(column)) for row, column in world_cells)
        values = tuple(int(entry) for entry in entries)
        if len(cells) != len(values):
            raise ValueError("rolling cells and entries differ in length")
        for (row, column), entry in zip(cells, values):
            self.entries[row % PLANE_ROWS, column % PLANE_COLUMNS] = entry

    def seed_normal(self, entries) -> None:
        source = np.asarray(entries, np.int64)
        if source.ndim != 2:
            raise ValueError("normal shadow must be two-dimensional")
        rows, columns = source.shape
        if rows > PLANE_ROWS or columns > PLANE_COLUMNS:
            raise ValueError("normal shadow exceeds the rolling plane")
        self.entries[:rows, :columns] = source

    def viewport_entries(
            self, state: FrameScrollState, *, columns: int, rows: int) -> np.ndarray:
        """Return the tile-aligned viewport used by a phase-safe exit."""

        if state.position % TILE_SIZE:
            raise ValueError("viewport entries require a tile-aligned position")
        return np.asarray([
            self.entries[row % PLANE_ROWS, column % PLANE_COLUMNS]
            for row, column in state.world_primary
        ], np.int64).reshape(int(rows), int(columns))

    def render(
            self,
            patterns: Mapping[int, np.ndarray],
            state: FrameScrollState,
            *,
            width: int,
            height: int,
    ) -> np.ndarray:
        """Render the exact fine-scroll viewport from 8-by-8 pattern pixels."""

        plane = None
        sample_shape = None
        for entry in np.unique(self.entries):
            if int(entry) == self.empty:
                continue
            pattern = np.asarray(patterns[int(entry)])
            if pattern.shape[:2] != (TILE_SIZE, TILE_SIZE):
                raise ValueError("rolling patterns must begin with shape 8x8")
            sample_shape = pattern.shape[2:]
            break
        if sample_shape is None:
            sample_shape = ()
        plane = np.zeros(
            (PLANE_ROWS * TILE_SIZE, PLANE_COLUMNS * TILE_SIZE, *sample_shape),
            dtype=np.asarray(next(iter(patterns.values()))).dtype,
        )
        for row in range(PLANE_ROWS):
            for column in range(PLANE_COLUMNS):
                entry = int(self.entries[row, column])
                if entry == self.empty:
                    continue
                plane[
                    row * TILE_SIZE:(row + 1) * TILE_SIZE,
                    column * TILE_SIZE:(column + 1) * TILE_SIZE,
                ] = np.asarray(patterns[entry])
        yy = (
            np.arange(int(height), dtype=np.int64) - state.vscroll
        ) % plane.shape[0]
        xx = (
            np.arange(int(width), dtype=np.int64) - state.hscroll
        ) % plane.shape[1]
        return plane[yy[:, None], xx[None, :]]
