#!/usr/bin/env python3
"""Check every synthetic movie frame against recorded BlastEm VDP writes."""

import argparse
import csv
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blastem"))
import cavc_routing
from event_stream import iter_publications, rgb333


def verify(directory: Path, trace: Path, output: Path, min_loops: int) -> None:
    header = (directory / "HEADER.DAT").read_bytes()
    frames = cavc_routing.frame_count_from_header(header)
    table = (directory / "paltab.bin").read_bytes()
    segments = len(table) // 128
    index = (directory / "palidx.bin").read_bytes()
    frame_segments = []
    cursor = active = 0
    for frame in range(frames):
        while cavc_routing.palette_switch_value(
                *struct.unpack_from(">HH", index, cursor))[0] <= frame:
            active = cavc_routing.palette_switch_value(
                *struct.unpack_from(">HH", index, cursor))[1]
            cursor += 4
        assert 0 <= active < segments
        frame_segments.append(active)
    palettes = [tuple(map(rgb333, struct.unpack_from(">64H", table, segment * 128)))
        for segment in range(segments)]
    rows = []
    counter_faults = []
    expected_lines = np.arange(40 * 28) % 4
    expected_patterns = np.full((40 * 28, 32), 0x22, np.uint8)
    unique_frame0 = (directory / "unique-frame0.flag").exists()
    if unique_frame0:
        indices = np.arange(40 * 28) + 0x1000
        expected_patterns[:, 0] = indices >> 8
        expected_patterns[:, 1] = indices & 255

    for publication in iter_publications(trace):
        frame = len(rows) % frames
        raw_frame = publication.frame
        if raw_frame in (0xFFFE, 0xFFFF) and raw_frame != frame & 0xFFFF:
            continue
        assert raw_frame == frame & 0xFFFF, ("frame order", raw_frame, frame)
        digits, vram = publication.hud, publication.vram
        cram = tuple(map(rgb333, struct.unpack(">64H", publication.cram)))
        segment = frame_segments[frame]
        assert cram == palettes[segment], ("CRAM", frame, segment)
        assert digits[4] == segment % 16, ("HUD segment", frame, digits[4])
        if any(digits[5:8]):
            counter_faults.append((frame, digits[5:8]))
        entries = np.frombuffer(vram, ">u2", count=2048, offset=0xE000).reshape(
            32, 64)[:28, :40].reshape(-1)
        assert np.array_equal((entries >> 13) & 3, expected_lines), ("palette lines", frame)
        patterns = np.frombuffer(vram, np.uint8).reshape(2048, 32)[entries & 0x7FF]
        expected_patterns[0, :2] = (1, 255) if frame == frames - 1 else ((0x10, 0) if unique_frame0 else (0x22, 0x22))
        assert np.array_equal(patterns, expected_patterns), ("patterns", frame)
        rows.append((len(rows) // frames, frame, segment, digits[4], *digits[5:8]))
    complete_loops = len(rows) // frames
    assert complete_loops >= min_loops, ("complete loops", complete_loops, min_loops)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, delimiter="\t", lineterminator="\n")
        writer.writerow(("loop", "frame", "palette_segment", "hud_palette_low4",
                         "sector_slip", "control_desync", "audio_resync"))
        writer.writerows(rows)
    assert not counter_faults, ("recovery counters", counter_faults[0],
                                "affected rows", len(counter_faults), "TSV", str(output))
    print(f"PASS: {len(rows)} displayed frames, {complete_loops} complete loops, "
          f"all {segments} palettes and every cell/pattern exact; DicBuf entry 511 exact")
    print(output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--min-loops", type=int, default=1)
    args = parser.parse_args()
    if args.tsv.suffix != ".tsv":
        parser.error("--tsv must use the .tsv extension")
    verify(args.fixture, args.trace, args.tsv, args.min_loops)
