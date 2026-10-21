"""Exact half-open ranges on the profile's output-frame clock."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import os
import wave


def frame_range(source):
    start, end = source.get("start_frame"), source.get("end_frame")
    if start is None and end is None:
        return None
    if (type(start) is not int or type(end) is not int
            or start < 0 or end <= start):
        raise ValueError("source.start_frame/end_frame require 0 <= start < end")
    return start, end


def video_filter(base, fps, bounds=None):
    result = f"{base},fps={fps}"
    if bounds is not None:
        start, end = bounds
        result += f",trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS"
    return result


def sample_range(bounds, fps, rate):
    clock = Fraction(str(fps))
    if clock <= 0:
        raise ValueError("source fps must be positive")
    return tuple(int(Fraction(frame * rate, 1) / clock) for frame in bounds)


def trim_audio(path: Path, bounds, fps):
    """Slice the fully filtered/resampled PCM; pad an absent source tail."""
    temporary = path.with_suffix(".range.wav")
    try:
        with wave.open(str(path), "rb") as source:
            start, end = sample_range(bounds, fps, source.getframerate())
            source.setpos(min(start, source.getnframes()))
            stride = source.getnchannels() * source.getsampwidth()
            with wave.open(str(temporary), "wb") as output:
                output.setparams(source.getparams())
                remaining = end - start
                while remaining:
                    count = min(remaining, 65536)
                    block = source.readframes(count)
                    output.writeframesraw(block.ljust(count * stride, b"\0"))
                    remaining -= count
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
