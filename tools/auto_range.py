#!/usr/bin/env python3
"""Whole-movie automatic black/white dynamic-range expansion.

The detector scans one combined RGB histogram of the complete extracted
master sequence for a dominant level spike just above black or just below
white. Such a spike is a source whose "black" or "white" sits a little off
the endpoint, which lands between MD RGB333 levels and dithers over large
flat areas. When found, one shared linear LUT stretches every channel so the
spike reaches exactly 0 / 255; a single LUT for all channels keeps hue
stable. Sources whose mass already touches the endpoints, or whose near-end
histogram is a smooth ramp rather than a spike, are left untouched.
"""

from __future__ import annotations

from concurrent import futures
import multiprocessing
from pathlib import Path

import numpy as np
from PIL import Image


# "Slightly" off the endpoint: a spike farther inside than 16/255 is a
# creative level choice, not a mastering offset, and is never stretched.
BLACK_SEARCH_MIN = 1
BLACK_SEARCH_MAX = 16
WHITE_SEARCH_MIN = 239
WHITE_SEARCH_MAX = 254

# The spike must carry at least this fraction of all samples and stand
# clear of the rest of its search window and the first bin beyond it.
SPIKE_MIN_FRACTION = 0.01
SPIKE_DOMINANCE = 3.0


def _check_rgb888(image: np.ndarray) -> np.ndarray:
    rgb = np.asarray(image)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"RGB888 image must have shape (H, W, 3), got {rgb.shape}")
    return rgb.astype(np.uint8, copy=False)


def frame_histogram(image: np.ndarray) -> np.ndarray:
    """Return one frame's combined R+G+B level histogram (256 bins)."""
    rgb = _check_rgb888(image)
    return np.bincount(rgb.ravel(), minlength=256).astype(np.int64)


def _dominant_spike(
        hist: np.ndarray,
        low: int,
        high: int,
        outside: int,
        *,
        spike_min_fraction: float = SPIKE_MIN_FRACTION,
        spike_dominance: float = SPIKE_DOMINANCE,
) -> int | None:
    """Return the dominant spike level within ``low..high``, if any."""
    values = np.asarray(hist, dtype=np.int64)
    total = int(values.sum())
    if total <= 0:
        return None
    window = values[low:high + 1]
    level = low + int(np.argmax(window))
    count = int(values[level])
    if count < total * spike_min_fraction:
        return None
    rest = (int(window.sum()) - count) / max(len(window) - 1, 1)
    if count < spike_dominance * max(rest, 1.0):
        return None
    # A histogram still rising past the window edge is a gradient, not a
    # displaced endpoint; a genuine spike also tops the first outside bin.
    if count <= int(values[outside]):
        return None
    return level


def detect_range(hist: np.ndarray) -> tuple[int, int]:
    """Return the (black, white) stretch points; (0, 255) means no change."""
    black = _dominant_spike(
        hist, BLACK_SEARCH_MIN, BLACK_SEARCH_MAX, BLACK_SEARCH_MAX + 1)
    white = _dominant_spike(
        hist, WHITE_SEARCH_MIN, WHITE_SEARCH_MAX, WHITE_SEARCH_MIN - 1)
    return (0 if black is None else black, 255 if white is None else white)


def build_lut(black: int, white: int) -> np.ndarray:
    """Return the shared uint8 LUT stretching ``black..white`` to 0..255."""
    if not 0 <= black < white <= 255:
        raise ValueError(f"invalid stretch points black={black} white={white}")
    levels = np.arange(256, dtype=np.float64)
    scaled = np.rint((levels - black) * 255.0 / (white - black))
    return np.clip(scaled, 0, 255).astype(np.uint8)


def apply_lut(image: np.ndarray, lut: np.ndarray) -> np.ndarray:
    """Apply the shared LUT to every channel of an RGB888 image."""
    return np.asarray(lut, dtype=np.uint8)[_check_rgb888(image)]


def scan_histogram(paths: list[Path]) -> np.ndarray:
    """Accumulate the combined histogram over a PNG frame sequence."""
    hist = np.zeros(256, dtype=np.int64)
    for path in paths:
        hist += frame_histogram(np.asarray(Image.open(path).convert("RGB")))
    return hist


def _rewrite_chunk(task: tuple[list[str], np.ndarray]) -> int:
    paths, lut = task
    for path in paths:
        image = np.asarray(Image.open(path).convert("RGB"))
        Image.fromarray(apply_lut(image, lut)).save(path)
    return len(paths)


def rewrite_files(paths: list[Path], lut: np.ndarray, workers: int = 1) -> None:
    """Rewrite PNG frames in place through the LUT.

    Workers use the ``spawn`` start method so a live CUDA parent process is
    never forked.
    """
    names = [str(path) for path in paths]
    if workers <= 1 or len(names) <= 1:
        _rewrite_chunk((names, lut))
        return
    workers = min(workers, len(names))
    step = -(-len(names) // workers)
    chunks = [(names[i:i + step], lut) for i in range(0, len(names), step)]
    context = multiprocessing.get_context("spawn")
    with futures.ProcessPoolExecutor(
            max_workers=workers, mp_context=context) as pool:
        done = sum(pool.map(_rewrite_chunk, chunks))
    if done != len(names):
        raise RuntimeError(
            f"auto_range rewrite covered {done} of {len(names)} frames")
