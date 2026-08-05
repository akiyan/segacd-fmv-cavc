#!/usr/bin/env python3
"""Deterministic, selectable RGB333 output dithering for the codec."""

from __future__ import annotations

import numpy as np


BAYER = "bayer"
EDGE_ATTENUATED_BAYER = "edge-attenuated-bayer"
PAL_BAYER = "pal-bayer"
NONE = "none"
MODES = (BAYER, EDGE_ATTENUATED_BAYER, PAL_BAYER, NONE)


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
EDGE_EXPANSION_RADIUS = 1


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


def expand_edge_range(
        edge_range: np.ndarray,
        radius: int = EDGE_EXPANSION_RADIUS,
) -> np.ndarray:
    """Spread the strongest local edge range outward by ``radius`` pixels."""
    values = np.asarray(edge_range)
    if values.ndim != 2:
        raise ValueError(
            f"edge range must have shape (H, W), got {values.shape}")
    if isinstance(radius, bool) or not isinstance(radius, int) or radius < 0:
        raise ValueError("edge expansion radius must be a non-negative integer")
    if radius == 0:
        return values.copy()
    height, width = values.shape
    padded = np.pad(values, radius, mode="edge")
    neighbours = [
        padded[y:y + height, x:x + width]
        for y in range(radius * 2 + 1)
        for x in range(radius * 2 + 1)
    ]
    return np.maximum.reduce(neighbours)


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


def edge_attenuated_bayer_rgb333(image: np.ndarray) -> np.ndarray:
    """Apply position-fixed Bayer dither, fading it near strong luma edges."""
    rgb = _check_rgb888(image)
    height, width, _channels = rgb.shape
    scaled = rgb.astype(np.float32) * (7.0 / 255.0)
    base = np.floor(scaled)
    # Resampling can leave a nearly white or black fringe one pixel beyond the
    # high-contrast core. Spread the core's attenuation into that fringe so a
    # moving boundary cannot expose one alternating Bayer dot just outside it.
    edge_range = expand_edge_range(local_luma_range(rgb))
    amount = edge_dither_amount(edge_range)
    bayer = bayer_thresholds(height, width)
    threshold = 0.5 + (bayer - 0.5) * amount
    return np.clip(
        base + ((scaled - base) > threshold[..., None]), 0, 7
    ).astype(np.uint8)


def nearest_rgb333(image: np.ndarray) -> np.ndarray:
    """Round every pixel to its nearest RGB333 level with no dither."""
    rgb = _check_rgb888(image)
    return np.clip(
        np.rint(rgb.astype(np.float32) * (7.0 / 255.0)), 0, 7
    ).astype(np.uint8)


def tile_bayer_numerators() -> np.ndarray:
    """Return the 8x8 Bayer thresholds as (64,) integer numerators over 128.

    ``(BAYER8 + 0.5) / 64`` equals ``(2 * BAYER8 + 1) / 128`` exactly, so the
    palette-aware comparison ``fraction > threshold`` can run entirely in
    integers.  Tiles are 8-pixel aligned to the screen, so every tile sees the
    same complete matrix.
    """
    return (2 * BAYER8.astype(np.int64) + 1).reshape(64)


def palette_aware_indices(
        targets888: np.ndarray,
        assign: np.ndarray,
        pals_arr: np.ndarray,
        pair_cap_sq: int = 0,
) -> np.ndarray:
    """Ordered-dither tiles between their two best palette entries.

    ``targets888`` is (C, 64, 3) uint8 source pixels (pre-quantization),
    ``assign`` is (C,) palette-line selection, ``pals_arr`` is (4, 15, 3)
    RGB333.  For each pixel the first candidate is the nearest palette entry;
    the second reflects the target across the first, so the pair straddles it;
    the position-fixed Bayer threshold picks between them by the projection
    fraction along the c1-to-c2 axis. ``pair_cap_sq`` bounds the squared
    RGB333-level distance between the two entries (0 disables the bound).  All arithmetic is integer so CPU and GPU agree bit for bit.

    Returns (C, 64) uint8 CRAM indices 1..15.
    """
    targets = np.asarray(targets888)
    if targets.ndim != 3 or targets.shape[1:] != (64, 3):
        raise ValueError(
            f"targets must have shape (C, 64, 3), got {targets.shape}")
    # Work in units of 1/255 RGB333 level: t255 = pixel * 7, entry255 = e * 255.
    t255 = targets.astype(np.int64) * 7                       # (C,64,3)
    rows = np.asarray(pals_arr, dtype=np.int64)[
        np.asarray(assign, dtype=np.int64)] * 255             # (C,15,3)
    diff1 = (t255[:, :, None, :] - rows[:, None, :, :])       # (C,64,15,3)
    dist1 = (diff1 * diff1).sum(-1)                           # (C,64,15)
    c1 = dist1.argmin(-1)                                     # (C,64)
    e1 = np.take_along_axis(rows, c1[..., None], axis=1)      # (C,64,3)
    # The natural partner reflects the target across c1, so the pair straddles
    # the target and their Bayer mix keeps the mean colour. Picking the merely
    # nearest entry instead flattens gradients and makes neighbouring tiles
    # choose different pairs, which reads as tile-boundary noise.
    mirror = 2 * t255 - e1
    diff2 = mirror[:, :, None, :] - rows[:, None, :, :]
    far_cost = (diff2 * diff2).sum(-1)                        # (C,64,15)
    c2 = far_cost.argmin(-1)
    if pair_cap_sq > 0:
        # Bound how far apart a mixing pair may sit. Beyond the cap the mix
        # spans unrelated colours (a dark halo blended with black reads as
        # isolated black specks). Move the partner only as close as the cap
        # requires, keeping the best remaining match to the reflected target
        # rather than collapsing to the nearest entry. With no eligible
        # partner inside the cap the far one stands.
        levels = np.asarray(pals_arr, dtype=np.int64)[
            np.asarray(assign, dtype=np.int64)]               # (C,15,3)
        e1_levels = np.take_along_axis(
            levels, c1[..., None], axis=1)                    # (C,64,3)
        span = levels[:, None, :, :] - e1_levels[:, :, None, :]
        span_sq = (span * span).sum(-1)                       # (C,64,15)
        eligible = (span_sq <= int(pair_cap_sq)) & (span_sq > 0)
        capped_cost = np.where(eligible, far_cost, np.iinfo(np.int64).max)
        c2_capped = capped_cost.argmin(-1)
        too_far = np.take_along_axis(
            span_sq, c2[..., None], axis=-1)[..., 0] > int(pair_cap_sq)
        c2 = np.where(too_far & eligible.any(-1), c2_capped, c2)
    e2 = np.take_along_axis(rows, c2[..., None], axis=1)
    d = t255 - e1
    e = e2 - e1
    num = (d * e).sum(-1)                                     # projection numerator
    den = (e * e).sum(-1)                                     # |e|^2 (0 when c1==c2)
    thr = tile_bayer_numerators()[None, :]                    # (1,64) /128
    take_second = (128 * num) > (thr * den)
    chosen = np.where(take_second & (den > 0), c2, c1)
    return (chosen + 1).astype(np.uint8)


def normalize_mode(value: str) -> str:
    """Return one supported profile spelling for an output-dither mode."""
    mode = str(value).strip().lower()
    if mode not in MODES:
        raise ValueError(
            f"output dither must be one of {', '.join(MODES)}, got {value!r}")
    return mode


def quantize_rgb333(image: np.ndarray, mode: str = BAYER) -> np.ndarray:
    """Convert RGB888 to RGB333 with the selected deterministic dither."""
    selected = normalize_mode(mode)
    if selected == BAYER:
        return bayer_rgb333(image)
    if selected == PAL_BAYER:
        # pal-bayer defers its own dithering to the palette-aware index stage.
        # Training and line assignment keep the Bayer view so palettes stay
        # identical to the plain-bayer pipeline.
        return bayer_rgb333(image)
    if selected == NONE:
        return nearest_rgb333(image)
    return edge_attenuated_bayer_rgb333(image)
