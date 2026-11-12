#!/usr/bin/env python3
"""Generate a repeatable multi-fade source that cannot prepare at every black."""

import argparse
from pathlib import Path
import subprocess

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "progressive-fades.mkv"
    rng = np.random.default_rng(127)
    black = np.zeros((224, 320, 3), np.uint8)
    frames = [black, black]
    for _ in range(3):
        colours = rng.integers(64, 220, (28, 40, 3), dtype=np.uint8)
        image = colours.repeat(8, axis=0).repeat(8, axis=1).astype(np.int16)
        image += rng.integers(-40, 41, image.shape, dtype=np.int16)
        for scale in [*np.linspace(0.15, 1, 6), *([1] * 12),
                      *np.linspace(0.85, 0.15, 6), 0]:
            frames.append(np.clip(image * scale, 0, 255).astype(np.uint8))
    subprocess.run([
        "ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
        "-video_size", "320x224", "-framerate", "30", "-i", "pipe:0",
        "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=22050",
        "-t", str(len(frames) / 30), "-c:v", "ffv1", "-c:a", "pcm_s16le",
        str(source),
    ], input=b"".join(frame.tobytes() for frame in frames), check=True)
    profile = directory / "fixture.toml"
    profile.write_text(f'''schema_version = 5
[source]
path = "{source}"
fps = "30"
duration = "{len(frames) / 30}"
sar = "32:35"
[video]
width = 320
height = 224
fit = "pad"
master_denoise = false
[output]
directory = "{directory / 'sim'}"
reuse = true
emit_decisions = true
[encoder]
cold_cap = 64
[palette]
algorithm = "mosaic-gm"
''', encoding="utf-8")
    print(f"{len(frames)} frames, 320x224, 30fps, tone audio; profile: {profile}")


if __name__ == "__main__":
    main()
