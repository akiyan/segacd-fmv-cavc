#!/usr/bin/env python3
"""Convert a completed BlastEm capture to native 320x224 FFV1/FLAC."""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import wave
from fractions import Fraction
from pathlib import Path


def probe(path: Path, *options: str) -> dict:
    return json.loads(subprocess.check_output(
        ("ffprobe", "-v", "error", *options, "-of", "json", str(path))
    ))


def capture_geometry(meta: dict) -> tuple[int, int]:
    frame_count, width, height = (meta[key] for key in ("frames", "width", "height"))
    h40 = set()
    next_frame = 1
    for area in meta["active_areas"]:
        start, end, x, y, w, h = (area[key] for key in ("from", "to", "x", "y", "width", "height"))
        if (start != next_frame or not start <= end <= frame_count
                or w <= 0 or h <= 0 or not 0 <= x <= width - w or not 0 <= y <= height - h):
            raise ValueError("capture has invalid active areas")
        next_frame = end + 1
        if (w, h) == (320, 224):
            h40.add((x, y))
    if next_frame != frame_count + 1 or len(h40) != 1:
        raise ValueError("capture needs one stable 320x224 H40 aperture")
    return h40.pop()


def verify_chunk(path: Path, frames: int, width: int, height: int) -> None:
    data = probe(path, "-select_streams", "v:0", "-count_frames", "-show_entries",
                 "stream=width,height,nb_read_frames")
    stream, = data.get("streams", [])
    actual = tuple(int(stream[key]) for key in ("nb_read_frames", "width", "height"))
    if actual != (frames, width, height):
        raise ValueError(f"{path}: expected {frames} frames at {width}x{height}, got {actual}")


def verify_mux(path: Path, frames: int, fps: Fraction, samples: int, rate: int) -> None:
    data = probe(path, "-select_streams", "v:0", "-show_packets", "-show_streams",
                 "-show_entries", "packet=pts:stream=codec_name,width,height,time_base")
    stream, = data.get("streams", [])
    packets = data.get("packets", [])
    if ((stream["codec_name"], stream["width"], stream["height"]) != ("ffv1", 320, 224)
            or len(packets) != frames):
        raise ValueError("lossless mux has unexpected video format or frame count")
    time_base = Fraction(stream["time_base"])
    last_pts = -1
    for frame, packet in enumerate(packets):
        pts = int(packet["pts"])
        if pts <= last_pts or abs(pts * time_base - frame / fps) > time_base:
            raise ValueError(f"lossless mux has the wrong video timestamp at frame {frame}")
        last_pts = pts
    data = probe(path, "-select_streams", "a:0", "-show_frames", "-show_streams",
                 "-show_entries", "frame=nb_samples:stream=codec_name,channels,sample_rate")
    stream, = data.get("streams", [])
    actual_samples = sum(int(frame["nb_samples"]) for frame in data.get("frames", []))
    if ((stream["codec_name"], stream["channels"], int(stream["sample_rate"])) != ("flac", 2, rate)
            or actual_samples != samples):
        raise ValueError("lossless mux has unexpected audio format or sample count")


def mux(prefix: Path, output: Path) -> None:
    def asset(suffix: str) -> Path:
        return prefix.with_name(prefix.name + suffix)

    meta = json.loads(asset(".json").read_text(encoding="utf-8"))
    if meta.get("complete") is not True or meta.get("video") is not True:
        raise ValueError("BlastEm video capture is incomplete")
    integer_fields = ("frames", "width", "height", "fps_num", "fps_den", "audio_samples",
                      "sample_rate", "video_chunk_frames", "video_chunks")
    for field in integer_fields:
        if type(meta[field]) is not int or meta[field] <= 0:
            raise ValueError(f"invalid capture metadata: {field}")
    frames, chunk_size = meta["frames"], meta["video_chunk_frames"]
    chunk_count = (frames + chunk_size - 1) // chunk_size
    if meta["video_chunks"] != chunk_count:
        raise ValueError("capture chunk count does not match frame count")
    fps = Fraction(meta["fps_num"], meta["fps_den"])
    rate, samples = meta["sample_rate"], meta["audio_samples"]
    wav_path = asset(".wav")
    with wave.open(str(wav_path), "rb") as wav:
        if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate(), wav.getnframes()) != (
                2, 2, rate, samples):
            raise ValueError("capture WAV does not match the capture metadata")
    if abs(frames / fps - Fraction(samples, rate)) > Fraction(40, 1000):
        raise ValueError("capture audio and video durations differ by more than 40 ms")
    x, y = capture_geometry(meta)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"recording already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    chunks = [asset(".apng" if i == 0 else f".part{i:04d}.apng") for i in range(chunk_count)]
    for i, path in enumerate(chunks):
        verify_chunk(path, min(chunk_size, frames - i * chunk_size), meta["width"], meta["height"])
    ffmpeg = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin"]
    with tempfile.TemporaryDirectory(prefix=".blastem-mux-", dir=output.parent) as temp:
        pending = Path(temp) / "capture.mkv"
        # Each APNG stores a rounded delay. Number the decoded frames on the
        # exact emulator clock with a single rate across all chunk boundaries.
        command = ffmpeg + [
            "-f", "rawvideo", "-pixel_format", "bgr0", "-video_size", "320x224",
            "-framerate", str(fps), "-i", "pipe:0", "-i", str(wav_path),
            "-map", "0:v:0", "-map", "1:a:0", "-fps_mode", "passthrough",
            "-c:v", "ffv1", "-threads:v", "2", "-pix_fmt", "bgr0", "-c:a", "flac", str(pending),
        ]
        with subprocess.Popen(command, stdin=subprocess.PIPE) as encoder:
            try:
                for chunk in chunks:
                    subprocess.run(ffmpeg + [
                        "-threads", "2", "-i", str(chunk), "-map", "0:v:0",
                        "-vf", f"crop=320:224:{x}:{y}", "-fps_mode", "passthrough",
                        "-f", "rawvideo", "-pix_fmt", "bgr0", "-threads", "1", "pipe:1",
                    ], check=True, stdout=encoder.stdin)
            finally:
                encoder.stdin.close()
            if encoder.wait() != 0:
                raise ValueError("FFmpeg could not encode the lossless capture")
        verify_mux(pending, frames, fps, samples, rate)
        os.link(pending, output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("prefix", type=Path)
    parser.add_argument("output_mkv", type=Path)
    args = parser.parse_args()
    try:
        mux(args.prefix, args.output_mkv)
    except (OSError, ValueError, KeyError, TypeError, wave.Error, subprocess.CalledProcessError) as error:
        print(f"BlastEm capture: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
