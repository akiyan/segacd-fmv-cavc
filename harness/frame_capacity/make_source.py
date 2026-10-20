#!/usr/bin/env python3
"""Generate a full-length low-motion video and its normal encoder profile."""

import argparse
from fractions import Fraction
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import cavc_routing


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--frames", type=int, default=16384)
    parser.add_argument("--fps", type=int, choices=(15, 24, 30), default=24)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--pattern", choices=("flat", "bars"), default="flat")
    args = parser.parse_args()
    cavc_routing.routing_sector_count(args.frames)
    markers = sorted({frame for frame in (
        0, 1, 32767, 32768, 65534, 65535, 65536,
        args.frames - 2, args.frames - 1) if 0 <= frame < args.frames})
    enable = "+".join(f"eq(n,{frame})" for frame in markers)
    duration = float(Fraction(args.frames, args.fps))
    name = f"frame_capacity_{args.pattern}_{args.fps}fps_{args.frames}.mp4"
    pattern = (f"color=c=0x404040:size=320x224:rate={args.fps}"
               if args.pattern == "flat" else f"smptebars=size=320x224:rate={args.fps}")
    command = [
        sys.executable, str(ROOT / "tools/tmpfs_workspace.py"), "run-file",
        "--output", name, "--kind", "frame-capacity-source", "--required-gb", "1",
        "--", "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", pattern,
        "-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono",
        "-frames:v", str(args.frames), "-t", f"{duration:.12f}",
        "-vf", f"drawbox=x=144:y=104:w=32:h=16:color=white:t=fill:enable='{enable}',setsar=32/35",
        "-c:v", "libx264", "-preset", "ultrafast", "-crf", "0",
        "-c:a", "aac", "-b:a", "64k", "{output}",
    ]
    result = subprocess.run(command, cwd=ROOT, check=True, text=True, capture_output=True)
    source = Path(result.stdout.strip().splitlines()[-1])
    probe = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
        "-show_entries", "stream=nb_read_frames",
        "-of", "default=noprint_wrappers=1:nokey=1", str(source),
    ], text=True).strip()
    if int(probe) != args.frames:
        raise RuntimeError(f"generated {probe} frames, expected {args.frames}")
    args.profile.parent.mkdir(parents=True, exist_ok=True)
    args.profile.write_text(f'''schema_version = 5

[source]
path = "{source}"
fps = "{args.fps}"
duration = "{duration:.12f}"
sar = "32:35"

[video]
width = 320
height = 224
fit = "pad"

[output]
directory = "tmpfs/FrameCapacity_{args.fps}fps_{args.frames}/sim"
reuse = false
emit_decisions = true

[encoder]
cold_cap = 210

[palette]
algorithm = "mosaic-gm"
''', encoding="utf-8")
    print(f"source: {source}")
    print(f"frames: {probe}; fps: {args.fps}; duration: {duration:.9f}s")
    print(f"marker frames: {markers}")
    print(f"profile: {args.profile.resolve()}")


if __name__ == "__main__":
    main()
