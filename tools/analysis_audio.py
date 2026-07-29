#!/usr/bin/env python3
"""Audio-panel helpers shared by analysis rendering and regression tests."""
from __future__ import annotations

import numpy as np


def decode_pcm_mono(
        raw: bytes, *, sample_width: int, channels: int) -> tuple[np.ndarray, int]:
    """Decode unsigned PCM8 or little-endian PCM16 into signed mono samples."""
    if channels != 1:
        raise ValueError(f"analysis audio must be mono, got {channels} channels")
    if sample_width == 1:
        samples = np.frombuffer(raw, np.uint8).astype(np.int32) - 128
        return samples, 128
    if sample_width == 2:
        samples = np.frombuffer(raw, "<i2").astype(np.int32)
        return samples, 32768
    raise ValueError(f"unsupported waveform sample width: {sample_width}")


def frame_sample_bounds(
        frame: int,
        *,
        fps: float,
        sample_rate: int,
        total_samples: int,
        window_frames: float = 1.0,
) -> tuple[int, int]:
    """Return the clipped sample interval owned by one video-frame window."""
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    if sample_rate <= 0:
        raise ValueError(f"sample_rate must be positive, got {sample_rate}")
    if window_frames <= 0:
        raise ValueError(
            f"window_frames must be positive, got {window_frames}")
    start = round(frame * sample_rate / fps)
    stop = round((frame + window_frames) * sample_rate / fps)
    return (
        int(np.clip(start, 0, total_samples)),
        int(np.clip(stop, 0, total_samples)),
    )


def waveform_extrema(
        samples: np.ndarray,
        *,
        start: int,
        stop: int,
        columns: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce signed samples to minimum/maximum values for each pixel column."""
    if columns <= 0:
        raise ValueError(f"columns must be positive, got {columns}")
    samples = np.asarray(samples, np.int32)
    start = int(np.clip(start, 0, len(samples)))
    stop = int(np.clip(stop, start, len(samples)))
    minima = np.zeros(columns, np.int32)
    maxima = np.zeros(columns, np.int32)
    if stop <= start:
        return minima, maxima
    edges = np.rint(np.linspace(start, stop, columns + 1)).astype(np.int64)
    for column in range(columns):
        left = int(edges[column])
        right = max(left + 1, int(edges[column + 1]))
        chunk = samples[left:min(right, stop)]
        if len(chunk):
            minima[column] = int(chunk.min())
            maxima[column] = int(chunk.max())
    return minima, maxima


def spectrum_levels(
        samples: np.ndarray,
        *,
        sample_rate: int,
        center_sample: int,
        full_scale: int,
        fft_size: int = 2048,
        min_hz: float = 40.0,
        max_hz: float = 11_025.0,
        bands: int = 24,
        floor_db: float = -72.0,
) -> np.ndarray:
    """Return normalized Hann-window FFT levels in logarithmic frequency bands."""
    if fft_size <= 0 or fft_size & (fft_size - 1):
        raise ValueError(f"fft_size must be a positive power of two: {fft_size}")
    if bands <= 0:
        raise ValueError(f"bands must be positive, got {bands}")
    if sample_rate <= 0 or full_scale <= 0:
        raise ValueError("sample_rate and full_scale must be positive")
    nyquist = sample_rate / 2.0
    upper_hz = min(float(max_hz), nyquist)
    if not 0 < min_hz < upper_hz:
        raise ValueError(
            f"frequency range must fit below Nyquist: {min_hz}..{upper_hz}")

    source = np.asarray(samples, np.int32)
    segment = np.zeros(fft_size, np.float64)
    start = int(center_sample) - fft_size // 2
    src_start = max(0, start)
    src_stop = min(len(source), start + fft_size)
    if src_stop > src_start:
        dst_start = src_start - start
        segment[dst_start:dst_start + src_stop - src_start] = (
            source[src_start:src_stop])

    window = np.hanning(fft_size)
    magnitudes = np.abs(np.fft.rfft(segment * window))
    reference = full_scale * window.sum() / 2.0
    amplitudes = magnitudes / max(reference, 1.0)
    frequencies = np.fft.rfftfreq(fft_size, d=1.0 / sample_rate)
    edges = np.geomspace(float(min_hz), upper_hz, bands + 1)
    levels = np.zeros(bands, np.float64)
    for band in range(bands):
        include_upper = band == bands - 1
        mask = (
            (frequencies >= edges[band])
            & (frequencies <= edges[band + 1] if include_upper
               else frequencies < edges[band + 1])
        )
        if np.any(mask):
            amplitude = float(amplitudes[mask].max())
        else:
            nearest = int(np.argmin(np.abs(
                frequencies - np.sqrt(edges[band] * edges[band + 1]))))
            amplitude = float(amplitudes[nearest])
        level_db = 20.0 * np.log10(max(amplitude, 1e-12))
        levels[band] = np.clip(
            (level_db - floor_db) / -floor_db, 0.0, 1.0)
    return levels
