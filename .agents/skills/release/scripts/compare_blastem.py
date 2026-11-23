#!/usr/bin/env python3
"""Compare every DEBUG and release movie publication in BlastEm captures."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "harness" / "blastem"))

import cavc_routing
from compare_recordings import RecordingError, decode_framemd5
from event_stream import iter_events, iter_publications
from hud_gate import normalize_result
from player_constants import parse_header_sector

# The DEBUG overlay uses the top Window row and three 8x8 sprites below it.
HUD_MASK = (
    "format=bgr0,"
    "drawbox=x=0:y=0:w=320:h=8:color=black:t=fill,"
    "drawbox=x=0:y=8:w=24:h=8:color=black:t=fill"
)
NTSC_VBLANK_CYCLES = (262 - 224) * 3420


def read_run(path):
    run = json.loads(path.read_text(encoding="utf-8"))
    if run.get("backend") != "blastem" or run.get("complete") is not True:
        raise ValueError(f"incomplete BlastEm run receipt: {path}")
    output = run.get("lossless_recording")
    if output:
        video = Path(output["path"])
        stat = video.stat()
        if (output["trim_seconds"] != 0
                or (stat.st_size, stat.st_mtime_ns) != (output["size"], output["mtime_ns"])):
            raise ValueError(f"expected the original untrimmed recording: {video}")
    else:
        video = Path(run["raw_recording"])
    return run, video, Path(run["vdp_event_log"])


def debug_scanouts(trace, count, frame0):
    captures = []
    for publication in iter_publications(trace):
        if publication.capture_index < frame0:
            continue
        ordinal = len(captures)
        if publication.frame != (ordinal & 0xFFFF):
            raise ValueError(f"DEBUG trace diverged at movie frame {ordinal}")
        captures.append(publication.capture_index)
        if len(captures) == count:
            if captures[0] != frame0:
                raise ValueError("DEBUG frame-zero scanout differs from the recording gate")
            return captures
    raise ValueError("DEBUG trace does not contain the complete movie")


def release_scanouts(trace, constants):
    start_address = 0xE000 + 2 * (constants.row0 * 64 + constants.col0)
    sizes = {2 * ((constants.trows - 1) * 64 + constants.tcols)}
    if constants.features & cavc_routing.FEATURE_SCROLL:
        sizes.update((2 * constants.trows * 64, 2 * 32 * 64))
    registers = bytearray(256)
    scanout = flush_cycle = written = length = first = 0
    movie_started = False
    for event in iter_events(trace):
        if event.kind == "FRAME":
            scanout += 1
            flush_cycle = event.cycle
        elif event.kind == "REGISTER":
            # The player clears its table with display disabled, then shows
            # the untimed frame -1 before the first movie publication.
            if event.address == 1:
                if movie_started and event.data[0] == 0x34:
                    return
                if (registers[1] == 0x34 and event.data[0] == 0x74
                        and registers[2] == 0x38 and registers[3] == 0x3C
                        and registers[4] == 7 and registers[5] == 0x6E):
                    if registers[18] != 0:
                        raise ValueError("release trace enabled the DEBUG Window")
                    movie_started = True
            registers[event.address] = event.data[0]
        elif event.kind == "VRAM" and movie_started:
            # The trace records each 16-bit VRAM write low byte first. A
            # publication can cross the flush near the end of VBlank.
            if written and event.address != ((start_address + written) ^ 1):
                written = 0
            if not written and event.address == (start_address ^ 1):
                length = 2 * (registers[19] | (registers[20] << 8))
                if length in sizes:
                    # A late transfer may start after BlastEm flushes the
                    # preceding image, while that same blank is still open.
                    first = scanout + int(event.cycle - flush_cycle > NTSC_VBLANK_CYCLES)
                    written = 1
            elif written:
                written += 1
            if written and written == length:
                yield first
                written = 0


def picture_hashes(path):
    _, frames = decode_framemd5(path, video_filter=HUD_MASK)
    if any(frame.size != 320 * 224 * 4 for frame in frames):
        raise ValueError(f"{path} does not have the native 320x224 raster")
    return [frame.digest for frame in frames]


def compare(args):
    baseline, debug_video, debug_trace = read_run(args.baseline)
    release, release_video, release_trace = read_run(args.release)
    for name in ("bios", "binary", "input_script"):
        if baseline["inputs"][name]["sha256"] != release["inputs"][name]["sha256"]:
            raise ValueError(f"BlastEm runs differ in {name}")
    gate = normalize_result(json.loads(args.baseline_gate.read_text(encoding="utf-8")))
    status = debug_video.stat()
    if (gate["gate"] != "PASS" or Path(gate["recording"]).resolve() != debug_video.resolve()
            or (status.st_size, status.st_mtime_ns) !=
            (gate["recording_size"], gate["recording_mtime_ns"])):
        raise ValueError("DEBUG capture needs its matching PASS gate")
    with args.header.open("rb") as header:
        constants = parse_header_sector(header.read(2048))
    count = constants.frames
    if gate["expected_frames"] != count or gate["observed_first_loop_frames"] != count:
        raise ValueError("DEBUG gate does not cover all frames of the supplied stream")

    debug = debug_scanouts(debug_trace, count, gate["ocr_start_anchor"]["frame0_capture_first"])
    actual = list(release_scanouts(release_trace, constants))
    if len(actual) != count or any(a >= b for a, b in zip(actual, actual[1:])):
        raise ValueError("release trace does not contain one distinct publication per movie frame")
    release_images = picture_hashes(release_video)
    debug_images = picture_hashes(debug_video)
    expected = [debug_images[i] for i in debug]
    if actual[-1] >= len(release_images):
        raise ValueError("release recording ends before the last traced publication")
    mismatches = [i for i, at in enumerate(actual) if release_images[at] != expected[i]]
    cadence = [
        {"frame": i, "debug_vblanks": debug[i] - debug[i - 1],
         "release_vblanks": at - actual[i - 1]}
        for i, at in enumerate(actual) if i > 0 and debug[i] - debug[i - 1] != at - actual[i - 1]
    ]
    return {
        "kind": "blastem-release-comparison",
        "pass": not mismatches,
        "baseline_receipt": str(args.baseline.resolve()),
        "release_receipt": str(args.release.resolve()),
        "baseline_gate": str(args.baseline_gate.resolve()),
        "frames": count,
        "debug_first_scanout": debug[0],
        "release_first_scanout": actual[0],
        "picture_mismatches_excluding_debug_hud": mismatches,
        "cadence_changes": cadence,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="DEBUG BlastEm run receipt")
    parser.add_argument("--release", required=True, type=Path, help="release BlastEm run receipt")
    parser.add_argument("--baseline-gate", required=True, type=Path)
    parser.add_argument("--header", required=True, type=Path)
    parser.add_argument("--json", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = compare(args)
    except (IndexError, KeyError, OSError, TypeError, ValueError, RecordingError) as exc:
        parser.exit(1, f"BlastEm release comparison: {exc}\n")
    args.json.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"{result['frames']} publications compared. "
          f"Picture mismatches: {len(result['picture_mismatches_excluding_debug_hud'])}. "
          f"Cadence changes: {len(result['cadence_changes'])}. {args.json}")
    return 0 if result["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
