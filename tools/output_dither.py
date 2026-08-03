#!/usr/bin/env python3
"""Deterministic RGB333 output dithering for the codec."""

from __future__ import annotations

import numpy as np


BAYER8 = np.array([
    [0, 32, 8, 40, 2, 34, 10, 42],
    [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38],
    [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41],
    [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37],
    [63, 31, 55, 23, 61, 29, 53, 21],
], dtype=np.float32)

# Keep the complete Bayer pattern through gentle gradients. Strong 3x3 luma
# edges progressively converge on ordinary nearest-colour rounding so resize
# antialiasing cannot turn a crisp boundary into alternating bright/dark dots.
EDGE_DITHER_START = 32
EDGE_DITHER_FULL = 96


def _check_rgb888(image: np.ndarray) -> np.ndarray:
    rgb = np.asarray(image)
    if rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"RGB888 image must have shape (H, W, 3), got {rgb.shape}")
    return rgb.astype(np.uint8, copy=False)


def bayer_thresholds(height: int, width: int) -> np.ndarray:
    """Return the position-fixed 8x8 Bayer threshold field."""
    return np.tile(
        (BAYER8 + 0.5) / 64.0,
        (height // 8 + 1, width // 8 + 1),
    )[:height, :width].astype(np.float32, copy=False)


def local_luma_range(image: np.ndarray) -> np.ndarray:
    """Return each pixel's integer luma range across its clipped 3x3 area."""
    rgb = _check_rgb888(image).astype(np.uint16)
    # 77/150/29 are integer BT.601-like weights whose sum is exactly 256.
    luma = ((77 * rgb[..., 0] + 150 * rgb[..., 1]
             + 29 * rgb[..., 2] + 128) >> 8).astype(np.int16)
    height, width = luma.shape
    padded = np.pad(luma, 1, mode="edge")
    neighbours = [
        padded[y:y + height, x:x + width]
        for y in range(3)
        for x in range(3)
    ]
    return np.maximum.reduce(neighbours) - np.minimum.reduce(neighbours)


def edge_dither_amount(
        edge_range: np.ndarray,
        start: int = EDGE_DITHER_START,
        full: int = EDGE_DITHER_FULL,
) -> np.ndarray:
    """Map a local luma range to Bayer amplitude: 1=same, 0=nearest."""
    if not 0 <= start < full <= 255:
        raise ValueError("edge dither limits must satisfy 0 <= start < full <= 255")
    return np.clip(
        (full - np.asarray(edge_range, dtype=np.float32)) / (full - start),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)


def bayer_rgb333(image: np.ndarray) -> np.ndarray:
    """Apply the codec's original position-fixed Bayer RGB333 conversion."""
    rgb = _check_rgb888(image)
    height, width, _channels = rgb.shape
    scaled = rgb.astype(np.float32) * (7.0 / 255.0)
    base = np.floor(scaled)
    threshold = bayer_thresholds(height, width)
    return np.clip(
        base + ((scaled - base) > threshold[..., None]), 0, 7
    ).astype(np.uint8)


def edge_adaptive_rgb333(image: np.ndarray) -> np.ndarray:
    """Apply position-fixed Bayer dither, fading it near strong luma edges."""
    rgb = _check_rgb888(image)
    height, width, _channels = rgb.shape
    scaled = rgb.astype(np.float32) * (7.0 / 255.0)
    base = np.floor(scaled)
    amount = edge_dither_amount(local_luma_range(rgb))
    bayer = bayer_thresholds(height, width)
    threshold = 0.5 + (bayer - 0.5) * amount
    return np.clip(
        base + ((scaled - base) > threshold[..., None]), 0, 7
    ).astype(np.uint8)
