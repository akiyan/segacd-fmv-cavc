#!/usr/bin/env python3
"""Mux a profile's comparison video from its footage.

`tools/comparison_layout.py` owns the frame and reads the per-source
specification from the profile's [comparison] section. This module turns that
specification into one ffmpeg graph: each panel is scaled into its rectangle
from the layout, then the layout's overlay is composited on top, so the drawn
frame and the video placement cannot drift apart.

Timing. Every panel declares where its moving picture starts inside its own
material (`fmv_start`) and how much of the run-up is kept on the timeline
(`lead`). The timeline's picture start is the largest lead, so a panel with a
long boot sequence begins at t=0 while a bare source master waits, and all
panels begin moving on the same frame. A panel is fed from `fmv_start - lead`
and padded with black until `picture_start - lead`.

A panel with no footage yet, and a panel whose footage has not started, are
left as the blacked-out rectangle the frame draws.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from pathlib import Path

import comparison_layout as layout_mod
from comparison_layout import Comparison, Panel

# Output cadence. The emulator recordings run at 59.94, and every material here
# is NTSC, so 59.94 avoids resampling the main panels for the sake of a 30 fps
# master. Exactly 60 would put a 0.1% judder on the recordings instead.
OUT_FPS = "60000/1001"

BACKDROP = "0x0e1014"


def build_graph(spec: Comparison, present: list[Panel], overlay_index: int,
                *, still: bool = False) -> tuple[str, str]:
    """Return the filter_complex string and the final video label.

    For a still, each input has already been seeked to its own moment and only
    one frame is taken, so the output-rate conversion and the black run-up
    padding are both left out.
    """
    rects = spec.rects()
    start = spec.picture_start
    parts: list[str] = []

    # Every panel rectangle is blacked out before any video lands on it. A
    # material that does not fill its rectangle would otherwise let the frame
    # backdrop show through as grey, and a panel whose footage has not started
    # yet reads as an off screen rather than a hole in the frame.
    base = (f"color=c={BACKDROP}"
            f":s={layout_mod.CANVAS[0]}x{layout_mod.CANVAS[1]}:r={OUT_FPS}")
    for panel in spec.panels:
        x, y, w, h = rects[panel.key]
        base += f",drawbox=x={x}:y={y}:w={w}:h={h}:color=black:t=fill"
    parts.append(base + "[base0]")

    for index, panel in enumerate(present):
        x, y, w, h = rects[panel.key]
        filters: list[str] = []
        if panel.crop:
            cx, cy, cw, ch = panel.crop
            filters.append(f"crop={cw}:{ch}:{cx}:{cy}")
        # setsar=1 first: the panel rectangle already carries the aperture's
        # displayed aspect, so any stored SAR must not scale it again.
        filters.append("setsar=1")
        if panel.pad:
            pw, ph, px, py = panel.pad
            filters.append(f"pad={pw}:{ph}:{px}:{py}:color=black")
        filters.append(f"scale={w}:{h}:flags=lanczos")
        if still:
            # Each input was seeked independently, and a seek does not always
            # land its first frame on PTS 0. Pin one frame to 0 so overlay
            # composites it instead of leaving the blacked-out rectangle.
            filters.append("select=eq(n\\,0)")
            filters.append("setpts=0")
        else:
            filters.append(f"fps={OUT_FPS}")
            delay = start - panel.lead
            if delay > 0:
                filters.append(f"tpad=start_duration={delay:.6f}"
                               f":start_mode=add:color=black")
        parts.append(f"[{index}:v]" + ",".join(filters) + f"[p{index}]")

    label = "base0"
    for index, panel in enumerate(present):
        x, y, w, h = rects[panel.key]
        nxt = f"c{index}"
        parts.append(f"[{label}][p{index}]overlay=x={x}:y={y}"
                     f":eof_action=pass[{nxt}]")
        label = nxt

    parts.append(f"[{label}][{overlay_index}:v]overlay=x=0:y=0[vout]")
    return ";".join(parts), "vout"


def build_command(spec: Comparison, output: Path, *, duration: float,
                  overlay_png: Path) -> list[str]:
    present = spec.with_footage

    cmd: list[str] = ["ffmpeg", "-y"]
    for panel in present:
        if panel.input_fps:
            cmd += ["-r", panel.input_fps]
        if panel.source_start > 0:
            cmd += ["-ss", f"{panel.source_start:.6f}"]
        cmd += ["-i", str(panel.path)]
    overlay_index = len(present)
    cmd += ["-i", str(overlay_png)]

    graph, vlabel = build_graph(spec, present, overlay_index)
    audio_index = next(i for i, p in enumerate(present)
                       if p.key == spec.audio_panel)

    switch = spec.audio_switch
    if switch is None:
        audio_source = f"[{audio_index}:a]"
        audio_map = f"{audio_index}:a"
    else:
        # One panel carries the run-up and hands over when the audio panel's
        # own picture starts. Both inputs are already seeked to their own
        # start, so the intro is simply its first `switch` seconds and the
        # main audio follows from its own beginning; concat joins them without
        # either being resampled against the other's clock.
        intro_index = next(i for i, p in enumerate(present)
                           if p.key == spec.audio_intro_panel)
        fmt = "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo"
        graph += (
            f";[{intro_index}:a]atrim=0:{switch:.6f},asetpts=PTS-STARTPTS,"
            f"{fmt}[ai]"
            f";[{audio_index}:a]asetpts=PTS-STARTPTS,{fmt}[am]"
            f";[ai][am]concat=n=2:v=0:a=1[aout]")
        audio_source = "[aout]"
        audio_map = "[aout]"

    tail = spec.tail_seconds
    total = duration + tail
    if tail > 0:
        # Hold the last frame and fade it out across the tail, so the end
        # screen's cards sit on a settling picture rather than a hard cut, and
        # the audio is padded with silence instead of stopping mid-note.
        graph += (f";[{vlabel}]tpad=stop_duration={tail:.6f}:stop_mode=clone,"
                  f"fade=t=out:st={duration:.6f}:d={tail:.6f}[vtail]")
        vlabel = "vtail"
        graph += (f";{audio_source}afade=t=out:st={max(duration - 1.0, 0):.6f}"
                  f":d=1,apad=whole_dur={total:.6f}[atail]")
        audio_map = "[atail]"

    cmd += [
        "-filter_complex", graph,
        "-map", f"[{vlabel}]",
        "-map", audio_map,
        "-t", f"{total:.6f}",
        "-c:v", "libx264", "-crf", "16", "-preset", "medium",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        str(output),
    ]
    return cmd


def build_still_command(spec: Comparison, output: Path, *, at: float,
                        overlay_png: Path) -> list[str]:
    """Compose one frame of the timeline from whatever footage exists."""
    start = spec.picture_start

    active: list[tuple[Panel, float]] = []
    for panel in spec.with_footage:
        panel_start = start - panel.lead
        if at + 1e-6 < panel_start:
            continue
        active.append((panel, panel.source_start + (at - panel_start)))

    cmd: list[str] = ["ffmpeg", "-y"]
    for panel, source_time in active:
        if panel.input_fps:
            cmd += ["-r", panel.input_fps]
        cmd += ["-ss", f"{max(source_time, 0.0):.6f}", "-i", str(panel.path)]
    overlay_index = len(active)
    cmd += ["-i", str(overlay_png)]

    graph, vlabel = build_graph(spec, [p for p, _ in active], overlay_index,
                               still=True)
    cmd += ["-filter_complex", graph, "-map", f"[{vlabel}]",
            "-frames:v", "1", str(output)]
    return cmd


def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path,
                        help="profile TOML carrying [comparison]")
    parser.add_argument("--output", type=Path,
                        help="write the video here (default: the profile's "
                             "comparison.output)")
    parser.add_argument("--still", type=Path,
                        help="write one composed frame here instead of the "
                             "video, for reviewing the layout against real "
                             "pictures")
    parser.add_argument("--at", type=float,
                        help="timeline second the still is taken from "
                             "(default: 25 s into the picture)")
    parser.add_argument("--duration", type=float,
                        help="timeline seconds to render (default: the "
                             "profile's comparison.duration)")
    parser.add_argument("--overlay", type=Path,
                        help="reuse an already rendered overlay PNG instead "
                             "of writing one beside the output")
    parser.add_argument("--print-command", action="store_true",
                        help="print the ffmpeg command without running it")
    args = parser.parse_args()

    spec = layout_mod.load(args.config)

    missing = [p.key for p in spec.with_footage if not p.path.is_file()]
    if missing:
        sys.exit(f"missing footage for: {', '.join(missing)}")

    output = args.output or spec.output
    if not args.still and output is None:
        sys.exit("no --output and no comparison.output in the profile")

    target = args.still or output
    target.parent.mkdir(parents=True, exist_ok=True)

    overlay_png = args.overlay
    if overlay_png is None:
        overlay_png = target.with_name(target.stem + "_overlay.png")
        layout_mod.render(spec, transparent_windows=True).save(overlay_png)
        print(f"overlay: {overlay_png}")

    start = spec.picture_start

    if args.still:
        at = args.at if args.at is not None else start + 25.0
        cmd = build_still_command(spec, args.still, at=at,
                                  overlay_png=overlay_png)
        if args.print_command:
            print(" ".join(shlex.quote(part) for part in cmd))
            return
        subprocess.run(cmd, check=True)
        print(f"still at timeline {at:.3f}s: {args.still}")
        return

    duration = args.duration if args.duration is not None else spec.duration
    if duration <= 0:
        sys.exit("duration must be positive; set comparison.duration or --duration")

    cmd = build_command(spec, output, duration=duration,
                        overlay_png=overlay_png)
    if args.print_command:
        print(" ".join(shlex.quote(part) for part in cmd))
        return

    print(f"picture start: {start:.3f}s")
    for panel in spec.panels:
        if panel.path is None:
            print(f"  {panel.key:7s} (no footage; placeholder)")
            continue
        print(f"  {panel.key:7s} source from {panel.source_start:8.3f}s"
              f"  timeline from {start - panel.lead:7.3f}s")

    subprocess.run(cmd, check=True)
    print(f"comparison: {output}")


if __name__ == "__main__":
    _main()
