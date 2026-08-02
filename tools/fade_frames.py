#!/usr/bin/env python3
"""Automatic black-fade shot detection for CRAM-only movie frames.

The detector deliberately has no timeline or profile inputs.  It finds a
bright interval between two black runs, fits every interval frame to one
static reference image plus a single global brightness scale, and accepts the
interval only when that scale rises and then falls.  Moving shots, hard cuts,
and merely dark scenes therefore stay on the ordinary tile-update path.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BlackRun:
    """Inclusive frame range whose sampled image is effectively black."""

    start: int
    end: int


@dataclass(frozen=True)
class FadeShot:
    """One static shot that fades in and out between two black runs."""

    left_black: BlackRun
    start: int
    end: int
    reference: int
    peak: int
    right_black: BlackRun
    scales: tuple[float, ...]
    fit_rmse: tuple[float, ...]

    @property
    def anchor(self) -> int:
        """Black frame on which the encoder can prepare the reference image."""

        return self.left_black.end


def _black_runs(mask: np.ndarray) -> tuple[BlackRun, ...]:
    hits = np.flatnonzero(mask)
    if not len(hits):
        return ()
    runs: list[BlackRun] = []
    start = previous = int(hits[0])
    for raw_frame in hits[1:]:
        frame = int(raw_frame)
        if frame == previous + 1:
            previous = frame
            continue
        runs.append(BlackRun(start, previous))
        start = previous = frame
    runs.append(BlackRun(start, previous))
    return tuple(runs)


def _fit_static_scale(
        samples: np.ndarray,
        black: np.ndarray,
) -> tuple[int, np.ndarray, np.ndarray]:
    """Return the best bright reference and each frame's scale/error."""

    centered = samples - black[None, ...]
    energy = np.einsum("fsc,fsc->f", centered, centered)
    # A fade reference is the brightest observed frame.  The final maximum is
    # preferred so a two-frame peak naturally leaves its last frame as the
    # unmodified reference/plateau frame.
    maximum = float(energy.max(initial=0.0))
    candidates = np.flatnonzero(np.isclose(energy, maximum, rtol=1e-6, atol=1e-6))
    reference_local = int(candidates[-1]) if len(candidates) else 0
    reference = centered[reference_local]
    denominator = float(np.sum(reference * reference))
    if denominator <= 1e-9:
        return reference_local, np.zeros(len(samples)), np.full(len(samples), np.inf)
    scales = np.einsum("fsc,sc->f", centered, reference) / denominator
    prediction = black[None, ...] + scales[:, None, None] * reference[None, ...]
    rmse = np.sqrt(np.mean((samples - prediction) ** 2, axis=(1, 2)))
    return reference_local, scales, rmse


def detect_fade_shots(
        probes,
        dark_fraction,
        *,
        black_fraction_min: float = 0.98,
        black_mean_max: float = 16.0,
        min_frames: int = 3,
        min_scale_change: float = 0.20,
        monotonic_tolerance: float = 0.06,
        maximum_scale: float = 1.08,
        maximum_rmse: float = 10.0,
        maximum_relative_rmse: float = 0.18,
) -> tuple[FadeShot, ...]:
    """Detect static fade-in/out shots without user-supplied frame ranges.

    ``probes`` is ``(frames, samples, 3)`` RGB888 data.  One sample per source
    tile is enough; using a small spatial grid preserves motion and hard-cut
    evidence while keeping the whole-movie detector cheap.  ``dark_fraction``
    is the per-frame fraction of source pixels below the encoder's black
    luminance threshold.
    """

    samples = np.asarray(probes, dtype=np.float64)
    dark = np.asarray(dark_fraction, dtype=np.float64)
    if samples.ndim != 3 or samples.shape[2] != 3:
        raise ValueError("fade probes must have shape (frames, samples, 3)")
    if dark.shape != (len(samples),):
        raise ValueError("fade probes and dark fractions must have equal frame counts")
    if not np.isfinite(samples).all() or not np.isfinite(dark).all():
        raise ValueError("fade probes and dark fractions must be finite")
    if min_frames < 1:
        raise ValueError("min_frames must be positive")

    frame_mean = samples.mean(axis=(1, 2))
    black_mask = (
        (dark >= float(black_fraction_min))
        & (frame_mean <= float(black_mean_max))
    )
    runs = _black_runs(black_mask)
    shots: list[FadeShot] = []
    for left, right in zip(runs, runs[1:]):
        start = left.end + 1
        end = right.start - 1
        if end - start + 1 < int(min_frames):
            continue
        interval = samples[start:end + 1]
        black = np.mean(
            np.concatenate(
                (samples[left.start:left.end + 1],
                 samples[right.start:right.end + 1]),
                axis=0,
            ),
            axis=0,
        )
        reference_local, scales, rmse = _fit_static_scale(interval, black)
        peak_local = int(np.argmax(scales))
        peak_scale = float(scales[peak_local])
        if peak_scale <= 0:
            continue
        relative_scales = scales / peak_scale
        relative_error = rmse / np.maximum(interval.mean(axis=(1, 2)), 16.0)
        rising = np.diff(relative_scales[:peak_local + 1])
        falling = np.diff(relative_scales[peak_local:])
        if (
            float(relative_scales.min(initial=1.0)) < -monotonic_tolerance
            or float(relative_scales.max(initial=0.0)) > maximum_scale
            or float(relative_scales[0]) > 1.0 - min_scale_change
            or float(relative_scales[-1]) > 1.0 - min_scale_change
            or (len(rising) and float(rising.min()) < -monotonic_tolerance)
            or (len(falling) and float(falling.max()) > monotonic_tolerance)
            or float(rmse.max(initial=0.0)) > maximum_rmse
            or float(relative_error.max(initial=0.0)) > maximum_relative_rmse
        ):
            continue
        shots.append(FadeShot(
            left_black=left,
            start=start,
            end=end,
            reference=start + reference_local,
            peak=start + peak_local,
            right_black=right,
            scales=tuple(float(value) for value in relative_scales),
            fit_rmse=tuple(float(value) for value in rmse),
        ))
    return tuple(shots)
