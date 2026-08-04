#!/usr/bin/env python3
"""Automatic axis-only camera-scroll detection and adoption measurements.

The detector has no source-specific frame ranges.  It measures raw source
frames in playback order, lets textured 16-by-16 blocks vote for an integer
horizontal or vertical displacement, and joins only sustained, self-consistent
motion into scroll segments.  A separate master/reconstruction comparison is
used to decide whether a detected segment is actually cheaper than the fixed
screen grid.

``delta_x`` and ``delta_y`` describe screen motion: a source pixel at ``(x, y)``
in the preceding frame is expected at ``(x + delta_x, y + delta_y)`` in the
current frame.  Lunar's left-moving cast therefore reports ``delta_x=-5``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
from PIL import Image


AXIS_NONE = "none"
AXIS_HORIZONTAL = "x"
AXIS_VERTICAL = "y"


@dataclass(frozen=True)
class MotionEstimate:
    """One raw-frame transition measured by the block voter."""

    frame: int
    axis: str
    delta: int
    support: float
    residual: float
    zero_residual: float
    gain: float
    runner_up_margin: float
    valid_blocks: int
    accepted: bool
    cut: bool


@dataclass(frozen=True)
class ScrollSegment:
    """Inclusive frame interval whose transitions form one camera scroll."""

    start: int
    end: int
    axis: str
    deltas: tuple[int, ...]
    cumulative: tuple[int, ...]
    support: float
    residual: float
    gain: float
    multiframe_support: float

    @property
    def transitions(self) -> int:
        return self.end - self.start + 1

    @property
    def displacement(self) -> int:
        return int(self.cumulative[-1]) if self.cumulative else 0


@dataclass(frozen=True)
class AdoptionMeasurement:
    """Fixed-grid and motion-compensated master costs for one transition."""

    frame: int
    fixed_changed: int
    edge_tiles: int
    residual_changed: int
    scroll_changed: int
    gain: float
    overlap_rmse: float


def _candidate_shifts(max_shift: int) -> tuple[tuple[int, int], ...]:
    limit = int(max_shift)
    if limit < 1:
        raise ValueError("max_shift must be positive")
    # Keep zero first so ties prefer no motion.  Horizontal precedes vertical
    # only as a deterministic tie-break; acceptance still requires a margin.
    return (
        ((0, 0),)
        + tuple((value, 0) for value in range(-limit, limit + 1) if value)
        + tuple((0, value) for value in range(-limit, limit + 1) if value)
    )


def _as_rgb(frame) -> np.ndarray:
    if isinstance(frame, (str, Path)):
        image = np.asarray(Image.open(frame).convert("RGB"), dtype=np.uint8)
    else:
        image = np.asarray(frame)
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("scroll frames must have shape (height, width, 3)")
    if min(image.shape[:2]) < 64:
        raise ValueError("scroll frames are too small for 16x16 block voting")
    if image.dtype != np.uint8:
        image = np.clip(np.rint(image), 0, 255).astype(np.uint8)
    return image


def _sample_grid(
        height: int,
        width: int,
        *,
        margin: int,
        block_size: int,
        sample_stride: int,
) -> tuple[np.ndarray, np.ndarray, int, int]:
    block = int(block_size)
    stride = int(sample_stride)
    if block <= 0 or stride <= 0 or block % stride:
        raise ValueError("block_size must be a positive multiple of sample_stride")
    usable_h = (height - 2 * margin) // block * block
    usable_w = (width - 2 * margin) // block * block
    if usable_h < block or usable_w < block:
        raise ValueError("frame has no block-voting area after the shift margin")
    rows = usable_h // block
    columns = usable_w // block
    offsets = np.arange(stride // 2, block, stride, dtype=np.int32)
    base_y = margin + np.arange(rows, dtype=np.int32)[:, None] * block
    base_x = margin + np.arange(columns, dtype=np.int32)[None, :] * block
    yy = (base_y[:, :, None, None] + offsets[None, None, :, None])
    xx = (base_x[:, :, None, None] + offsets[None, None, None, :])
    yy = np.broadcast_to(yy, (rows, columns, len(offsets), len(offsets)))
    xx = np.broadcast_to(xx, (rows, columns, len(offsets), len(offsets)))
    return yy.reshape(-1, len(offsets) ** 2), xx.reshape(-1, len(offsets) ** 2), rows, columns


def _array_module(backend: str):
    selected = str(backend).strip().lower()
    if selected not in {"auto", "cpu", "gpu"}:
        raise ValueError("scroll backend must be auto, cpu, or gpu")
    if selected == "cpu":
        return np, False
    try:
        import gpu_quant

        if gpu_quant.enabled():
            return gpu_quant.cupy(), True
    except Exception:  # noqa: BLE001 - every CUDA failure falls back to CPU
        if selected == "gpu":
            raise
    if selected == "gpu":
        raise RuntimeError("GPU scroll detection requested but CuPy is unavailable")
    return np, False


def estimate_motion(
        previous,
        current,
        *,
        frame: int = 1,
        max_shift: int = 24,
        block_size: int = 16,
        sample_stride: int = 4,
        minimum_texture: float = 10.0,
        minimum_blocks: int = 20,
        minimum_support: float = 0.32,
        minimum_gain: float = 1.35,
        minimum_runner_up_margin: float = 0.06,
        maximum_residual: float = 34.0,
        cut_zero_residual: float = 58.0,
        cut_best_residual: float = 42.0,
        backend: str = "auto",
) -> MotionEstimate:
    """Measure one transition with textured-block axis-only voting.

    The fixed sampling lattice makes the CPU fallback inexpensive while still
    measuring every 16-by-16 block.  CuPy evaluates the same lattice and returns
    the same scalar metrics.
    """

    prev = _as_rgb(previous)
    curr = _as_rgb(current)
    if prev.shape != curr.shape:
        raise ValueError("scroll frame dimensions differ")
    limit = int(max_shift)
    candidates = _candidate_shifts(limit)
    yy, xx, _rows, _columns = _sample_grid(
        prev.shape[0], prev.shape[1],
        margin=limit,
        block_size=block_size,
        sample_stride=sample_stride,
    )
    xp, on_gpu = _array_module(backend)
    prev_samples = prev[yy, xx].astype(np.float32)
    # Texture and brightness are source-side eligibility tests.  Flat colour,
    # black bars, and clipped white fields do not get a vote.
    luma = (
        prev_samples[..., 0] * 0.299
        + prev_samples[..., 1] * 0.587
        + prev_samples[..., 2] * 0.114
    )
    texture = luma.std(axis=1)
    mean_luma = luma.mean(axis=1)
    valid = (
        (texture >= float(minimum_texture))
        & (mean_luma >= 8.0)
        & (mean_luma <= 247.0)
    )
    valid_count = int(np.count_nonzero(valid))
    if valid_count < int(minimum_blocks):
        return MotionEstimate(
            frame=int(frame), axis=AXIS_NONE, delta=0, support=0.0,
            residual=float("inf"), zero_residual=float("inf"), gain=1.0,
            runner_up_margin=0.0, valid_blocks=valid_count,
            accepted=False, cut=False,
        )

    g_prev = xp.asarray(prev_samples[valid], dtype=xp.float32)
    g_curr = xp.asarray(curr, dtype=xp.uint8)
    g_yy = xp.asarray(yy[valid], dtype=xp.int32)
    g_xx = xp.asarray(xx[valid], dtype=xp.int32)
    per_candidate = []
    for dx, dy in candidates:
        shifted = g_curr[g_yy + int(dy), g_xx + int(dx)].astype(xp.float32)
        per_candidate.append(xp.abs(g_prev - shifted).mean(axis=(1, 2)))
    errors = xp.stack(per_candidate, axis=0)
    scores = xp.median(errors, axis=1)
    scores_host = (
        xp.asnumpy(scores) if on_gpu else np.asarray(scores, dtype=np.float32))
    best_index = int(np.argmin(scores_host))
    best_dx, best_dy = candidates[best_index]
    best_score = float(scores_host[best_index])
    zero_score = float(scores_host[0])

    winners = xp.argmin(errors, axis=0)
    winners_host = xp.asnumpy(winners) if on_gpu else np.asarray(winners)
    if best_dx:
        neighbour_indices = {
            index for index, (dx, dy) in enumerate(candidates)
            if dy == 0 and abs(dx - best_dx) <= 1
        }
        axis = AXIS_HORIZONTAL
        delta = int(best_dx)
    elif best_dy:
        neighbour_indices = {
            index for index, (dx, dy) in enumerate(candidates)
            if dx == 0 and abs(dy - best_dy) <= 1
        }
        axis = AXIS_VERTICAL
        delta = int(best_dy)
    else:
        neighbour_indices = {0}
        axis = AXIS_NONE
        delta = 0
    support = float(np.isin(winners_host, tuple(neighbour_indices)).mean())

    # Adjacent sub-pixel ambiguity is part of the winning motion, not a useful
    # runner-up.  Compare against zero, the other axis, and displacements at
    # least two pixels away.
    competitors = []
    for index, (dx, dy) in enumerate(candidates):
        if index == best_index:
            continue
        if best_dx and dy == 0 and abs(dx - best_dx) <= 1:
            continue
        if best_dy and dx == 0 and abs(dy - best_dy) <= 1:
            continue
        competitors.append(float(scores_host[index]))
    runner_up = min(competitors, default=best_score)
    runner_margin = (runner_up - best_score) / max(runner_up, 1e-6)
    gain = zero_score / max(best_score, 1e-6)
    cut = (
        zero_score >= float(cut_zero_residual)
        and best_score >= float(cut_best_residual)
    )
    accepted = (
        axis != AXIS_NONE
        and not cut
        and support >= float(minimum_support)
        and gain >= float(minimum_gain)
        and runner_margin >= float(minimum_runner_up_margin)
        and best_score <= float(maximum_residual)
    )
    return MotionEstimate(
        frame=int(frame), axis=axis, delta=delta,
        support=support, residual=best_score, zero_residual=zero_score,
        gain=gain, runner_up_margin=runner_margin,
        valid_blocks=valid_count, accepted=bool(accepted), cut=bool(cut),
    )


def estimate_sequence(
        frames: Sequence,
        *,
        first_frame: int = 0,
        backend: str = "auto",
        **kwargs,
) -> tuple[MotionEstimate, ...]:
    """Measure every adjacent transition in a frame sequence."""

    if len(frames) < 2:
        return ()
    return tuple(
        estimate_motion(
            frames[index - 1], frames[index],
            frame=int(first_frame) + index,
            backend=backend,
            **kwargs,
        )
        for index in range(1, len(frames))
    )


def _bridge_short_gaps(
        estimates: Sequence[MotionEstimate],
        *,
        maximum_gap: int,
        delta_tolerance: int,
) -> tuple[MotionEstimate, ...]:
    out = list(estimates)
    index = 0
    while index < len(out):
        if out[index].accepted or out[index].cut:
            index += 1
            continue
        start = index
        while index < len(out) and not out[index].accepted and not out[index].cut:
            index += 1
        gap = index - start
        if gap > int(maximum_gap) or start == 0 or index >= len(out):
            continue
        left = out[start - 1]
        right = out[index]
        if not left.accepted or not right.accepted or left.axis != right.axis:
            continue
        if abs(left.delta - right.delta) > int(delta_tolerance):
            continue
        # A rejected transition may be a true hold.  Preserve measured zero as
        # zero; otherwise use the neighbouring integer motion as the safest
        # continuity estimate.  These inferred rows never contribute support.
        inferred = int(round((left.delta + right.delta) / 2))
        for position in range(start, index):
            measured = out[position]
            delta = 0 if measured.axis == AXIS_NONE and measured.zero_residual <= 8.0 else inferred
            out[position] = replace(
                measured,
                axis=left.axis,
                delta=delta,
                accepted=True,
                support=0.0,
            )
    return tuple(out)


def build_segments(
        estimates: Sequence[MotionEstimate],
        *,
        minimum_transitions: int = 8,
        maximum_gap: int = 2,
        delta_tolerance: int = 1,
        minimum_displacement: int = 16,
) -> tuple[ScrollSegment, ...]:
    """Join accepted transitions without any source-time hints."""

    rows = _bridge_short_gaps(
        estimates,
        maximum_gap=maximum_gap,
        delta_tolerance=delta_tolerance,
    )
    segments = []
    index = 0
    while index < len(rows):
        if not rows[index].accepted or rows[index].delta == 0:
            index += 1
            continue
        start = index
        axis = rows[index].axis
        reference_delta = rows[index].delta
        index += 1
        while index < len(rows):
            row = rows[index]
            if row.cut or not row.accepted or row.axis != axis:
                break
            if row.delta and abs(row.delta - reference_delta) > int(delta_tolerance):
                break
            if row.delta:
                reference_delta = int(round((reference_delta + row.delta) / 2))
            index += 1
        group = rows[start:index]
        deltas = tuple(int(row.delta) for row in group)
        cumulative = tuple(int(value) for value in np.cumsum(deltas))
        if (
            len(group) >= int(minimum_transitions)
            and abs(cumulative[-1]) >= int(minimum_displacement)
        ):
            supported = [row for row in group if row.support > 0]
            segments.append(ScrollSegment(
                start=int(group[0].frame),
                end=int(group[-1].frame),
                axis=axis,
                deltas=deltas,
                cumulative=cumulative,
                support=float(np.mean([row.support for row in supported]))
                if supported else 0.0,
                residual=float(np.mean([row.residual for row in supported]))
                if supported else float("inf"),
                gain=float(np.mean([row.gain for row in supported]))
                if supported else 1.0,
                multiframe_support=0.0,
            ))
        if index == start:
            index += 1
    return tuple(segments)


def validate_multiframe(
        segments: Sequence[ScrollSegment],
        frames: Sequence,
        *,
        first_frame: int = 0,
        maximum_error: int = 1,
        minimum_support: float = 0.60,
        backend: str = "auto",
        max_shift: int = 48,
        **kwargs,
) -> tuple[ScrollSegment, ...]:
    """Require two-frame estimates to agree with adjacent displacement sums."""

    validated = []
    origin = int(first_frame)
    for segment in segments:
        checks = []
        for frame in range(segment.start + 1, segment.end + 1):
            local = frame - origin
            if local < 2 or local >= len(frames):
                continue
            offset = frame - segment.start
            expected = segment.deltas[offset - 1] + segment.deltas[offset]
            if expected == 0:
                continue
            result = estimate_motion(
                frames[local - 2], frames[local],
                frame=frame,
                max_shift=max(int(max_shift), abs(int(expected)) + 2),
                backend=backend,
                **kwargs,
            )
            checks.append(
                result.accepted
                and result.axis == segment.axis
                and abs(result.delta - expected) <= int(maximum_error)
            )
        support = float(np.mean(checks)) if checks else 0.0
        if support >= float(minimum_support):
            validated.append(replace(segment, multiframe_support=support))
    return tuple(validated)


def detect_segments(
        frames: Sequence,
        *,
        first_frame: int = 0,
        backend: str = "auto",
        validate: bool = True,
        estimate_kwargs: dict | None = None,
        segment_kwargs: dict | None = None,
) -> tuple[tuple[MotionEstimate, ...], tuple[ScrollSegment, ...]]:
    """Run adjacent detection, temporal grouping, and multi-frame validation."""

    estimate_options = dict(estimate_kwargs or {})
    rows = estimate_sequence(
        frames, first_frame=first_frame, backend=backend, **estimate_options)
    segments = build_segments(rows, **dict(segment_kwargs or {}))
    if validate and segments:
        multi_options = dict(estimate_options)
        multi_options.pop("max_shift", None)
        segments = validate_multiframe(
            segments,
            frames,
            first_frame=first_frame,
            backend=backend,
            **multi_options,
        )
    return rows, segments


def _tile_change_count(
        first: np.ndarray,
        second: np.ndarray,
        *,
        tile_size: int,
        threshold: float,
) -> tuple[int, float]:
    height = min(first.shape[0], second.shape[0])
    width = min(first.shape[1], second.shape[1])
    height = height // tile_size * tile_size
    width = width // tile_size * tile_size
    if not height or not width:
        return 0, float("inf")
    delta = first[:height, :width].astype(np.float32) - second[:height, :width]
    squared = np.mean(delta * delta, axis=2)
    tiles = squared.reshape(
        height // tile_size, tile_size,
        width // tile_size, tile_size,
    ).transpose(0, 2, 1, 3)
    rmse = np.sqrt(np.mean(tiles, axis=(2, 3)))
    return int(np.count_nonzero(rmse > float(threshold))), float(np.sqrt(np.mean(squared)))


def measure_adoption(
        previous,
        current,
        *,
        frame: int,
        axis: str,
        delta: int,
        tile_size: int = 8,
        tile_rmse_threshold: float = 8.0,
) -> AdoptionMeasurement:
    """Compare a fixed screen grid with scroll plus edge/residual updates."""

    prev = _as_rgb(previous)
    curr = _as_rgb(current)
    if prev.shape != curr.shape:
        raise ValueError("adoption frame dimensions differ")
    fixed, _fixed_rmse = _tile_change_count(
        prev, curr, tile_size=tile_size, threshold=tile_rmse_threshold)
    dx = int(delta) if axis == AXIS_HORIZONTAL else 0
    dy = int(delta) if axis == AXIS_VERTICAL else 0
    x0 = max(0, dx)
    x1 = min(prev.shape[1], prev.shape[1] + dx)
    y0 = max(0, dy)
    y1 = min(prev.shape[0], prev.shape[0] + dy)
    prev_overlap = prev[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    curr_overlap = curr[y0:y1, x0:x1]
    residual, overlap_rmse = _tile_change_count(
        prev_overlap,
        curr_overlap,
        tile_size=tile_size,
        threshold=tile_rmse_threshold,
    )
    if axis == AXIS_HORIZONTAL:
        edge = int(np.ceil(abs(dx) / tile_size)) * (prev.shape[0] // tile_size)
    elif axis == AXIS_VERTICAL:
        edge = int(np.ceil(abs(dy) / tile_size)) * (prev.shape[1] // tile_size)
    else:
        edge = 0
    scroll = int(edge + residual)
    return AdoptionMeasurement(
        frame=int(frame), fixed_changed=int(fixed), edge_tiles=int(edge),
        residual_changed=int(residual), scroll_changed=scroll,
        gain=float(fixed / max(scroll, 1)), overlap_rmse=overlap_rmse,
    )


def measure_segment_adoption(
        segment: ScrollSegment,
        frames: Sequence,
        *,
        first_frame: int = 0,
        **kwargs,
) -> tuple[AdoptionMeasurement, ...]:
    """Measure every detected transition against master/reconstruction frames."""

    origin = int(first_frame)
    out = []
    for frame in range(segment.start, segment.end + 1):
        local = frame - origin
        delta = segment.deltas[frame - segment.start]
        out.append(measure_adoption(
            frames[local - 1], frames[local],
            frame=frame, axis=segment.axis, delta=delta, **kwargs))
    return tuple(out)


def adopt_segment(
        segment: ScrollSegment,
        measurements: Iterable[AdoptionMeasurement],
        *,
        minimum_mean_gain: float = 2.0,
        minimum_beneficial_fraction: float = 0.80,
        maximum_overlap_rmse: float = 18.0,
) -> bool:
    """Return whether motion compensation is materially cheaper and faithful."""

    rows = tuple(measurements)
    if not rows:
        return False
    gains = np.asarray([row.gain for row in rows], np.float64)
    beneficial = np.asarray(
        [row.scroll_changed < row.fixed_changed for row in rows], bool)
    residuals = np.asarray([row.overlap_rmse for row in rows], np.float64)
    return bool(
        float(gains.mean()) >= float(minimum_mean_gain)
        and float(beneficial.mean()) >= float(minimum_beneficial_fraction)
        and float(np.percentile(residuals, 95)) <= float(maximum_overlap_rmse)
    )
