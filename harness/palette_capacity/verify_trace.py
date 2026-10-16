#!/usr/bin/env python3
"""Check every synthetic movie frame against actual LOGVDP writes."""

import argparse
import csv
import gzip
import re
import struct
from pathlib import Path


WRITE = re.compile(
    r"(VRAM|CRAM) 0x([0-9a-f]+) write -> 0x([0-9a-f]+) \(([0-9a-f]+)\)")


def verify(directory: Path, trace: Path, output: Path, min_loops: int) -> None:
    header = (directory / "HEADER.DAT").read_bytes()
    frames = struct.unpack_from(">H", header, 4)[0]
    table = (directory / "paltab.bin").read_bytes()
    segments = len(table) // 128
    index = (directory / "palidx.bin").read_bytes()
    frame_segments = []
    cursor = active = 0
    for frame in range(frames):
        while struct.unpack_from(">H", index, cursor)[0] <= frame:
            active = struct.unpack_from(">H", index, cursor + 2)[0]
            cursor += 4
        assert 0 <= active < segments
        frame_segments.append(active)
    # LOGVDP prints the VDP's packed 9-bit CRAM value, not the CPU bus word.
    palettes = [tuple(
        ((w & 0xE00) >> 3) | ((w & 0xE0) >> 2) | ((w & 0xE) >> 1)
        for w in struct.unpack_from(">64H", table, segment * 128))
        for segment in range(segments)]
    vram = bytearray(65536)
    cram = [0] * 64
    hud = []
    pending = None
    rows = []

    def finish_frame():
        nonlocal pending
        if pending is None:
            return
        frame, digits = pending
        expected_frame = len(rows) % frames
        assert frame == expected_frame, ("frame order", frame, expected_frame)
        segment = frame_segments[frame]
        assert tuple(cram) == palettes[segment], ("CRAM", frame, segment)
        assert digits[4] == segment % 16, ("HUD segment", frame, digits[4])
        assert digits[5:8] == [0, 0, 0], ("recovery counters", frame, digits[5:8])
        for cell in range(40 * 28):
            address = 0xE000 + ((cell // 40) * 64 + cell % 40) * 2
            entry = struct.unpack_from(">H", vram, address)[0]
            assert (entry >> 13) & 3 == cell % 4, ("palette line", frame, cell)
            start = (entry & 0x7FF) * 32
            pattern = bytes(vram[start:start + 32])
            expected = (b"\x01\xff" + bytes([0x22]) * 30
                        if frame == frames - 1 and cell == 0
                        else bytes([0x22]) * 32)
            assert pattern == expected, ("pattern", frame, cell, start)
        rows.append((len(rows) // frames, frame, segment, digits[4], *digits[5:8]))
        pending = None

    with gzip.open(trace, "rt", errors="replace") as source:
        for line in source:
            if " write -> " not in line:
                continue
            match = WRITE.search(line)
            if not match:
                continue
            kind, raw_address, raw_word, raw_pc = match.groups()
            address, word, pc = (int(value, 16) for value in (raw_address, raw_word, raw_pc))
            if pc & 0xFF0000 != 0xFF0000:
                continue
            if kind == "CRAM":
                cram[(address & 0x7E) // 2] = word
                continue
            address &= 0xFFFF
            if address == 0xE000:
                # Finish the displayed state before the next movie NT is written.
                finish_frame()
            struct.pack_into(">H", vram, address, word)
            if not 0xF000 <= address < 0xF050:
                continue
            if address == 0xF000:
                hud = []
            if address == 0xF000 + len(hud) * 2 and 1744 <= (word & 0x7FF) < 1760:
                hud.append(word & 15)
            else:
                hud = []
            if len(hud) == 40:
                frame = int("".join(f"{digit:x}" for digit in hud[:4]), 16)
                if frame != 0xFFFF:
                    assert pending is None
                    pending = (frame, hud)
                hud = []
    finish_frame()
    complete_loops = len(rows) // frames
    assert complete_loops >= min_loops, ("complete loops", complete_loops, min_loops)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, delimiter="\t", lineterminator="\n")
        writer.writerow(("loop", "frame", "palette_segment", "hud_palette_low4",
                         "sector_slip", "control_desync", "audio_resync"))
        writer.writerows(rows)
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
