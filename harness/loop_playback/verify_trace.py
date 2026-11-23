"""Compare every displayed movie frame across loops of an existing DEBUG disc.

The first loop is the visual reference, not an independent SIM oracle. This
checks replay state restoration and frame order; it cannot prove source quality
or sound. Use the palette fixture for independent expected pixels.
"""

import argparse
import csv
import hashlib
from pathlib import Path
import struct
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blastem"))
import cavc_routing
from event_stream import iter_publications, rgb333
import player_constants


def verify(header, trace, output, min_loops):
    with header.open("rb") as source:
        pc = player_constants.parse_header_sector(source.read(2048))
    if pc.frames > 65535:
        raise ValueError("this reader supports movies up to 65,535 frames")
    reference, rows, faults = [], [], []
    for publication in iter_publications(trace):
        frame, digits = publication.frame, publication.hud
        ordinal = len(rows)
        expected = ordinal % pc.frames
        if frame in (0xFFFE, 0xFFFF) and frame != expected:
            continue
        if frame != expected:
            raise ValueError(f"frame {frame}, expected {expected}, visit {ordinal // pc.frames}")
        vram, vsram = publication.vram, publication.vsram
        cram = np.fromiter(map(rgb333, struct.unpack(">64H", publication.cram)), np.uint16)
        table = np.frombuffer(vram, ">u2", count=2048, offset=0xE000).reshape(32, 64)
        if pc.features & cavc_routing.FEATURE_SCROLL:
            # The player uses a 64x32 plane with whole-screen H/V scroll.
            horizontal = struct.unpack_from(">H", vram, 0xFC00)[0]
            x = (np.arange(pc.col0*8, (pc.col0+pc.tcols)*8) - horizontal) & 511
            vertical = struct.unpack_from(">H", vsram)[0]
            y = (np.arange(pc.row0*8, (pc.row0+pc.trows)*8) + vertical) & 255
            entries = table[y[:, None]//8, x[None, :]//8]
            tx = np.where(entries & 0x800, 7-(x[None, :] & 7), x[None, :] & 7)
            ty = np.where(entries & 0x1000, 7-(y[:, None] & 7), y[:, None] & 7)
            packed = np.frombuffer(vram, np.uint8)[(entries & 0x7FF)*32 + ty*4 + tx//2]
            pixels = (packed >> np.where(tx & 1, 0, 4)) & 15
            colors = cram[((entries >> 13) & 3)*16 + pixels]
        else:
            entries = table[pc.row0:pc.row0+pc.trows, pc.col0:pc.col0+pc.tcols].reshape(-1)
            patterns = np.frombuffer(vram, np.uint8).reshape(2048, 32)[entries & 0x7FF]
            pixels = np.stack((patterns >> 4, patterns & 15), axis=2).reshape(-1, 8, 8)
            pixels = np.where((entries & 0x800)[:, None, None], pixels[:, :, ::-1], pixels)
            pixels = np.where((entries & 0x1000)[:, None, None], pixels[:, ::-1, :], pixels)
            colors = cram[((entries >> 13) & 3)[:, None]*16 + pixels.reshape(-1, 64)]
        digest = hashlib.sha256(np.asarray(colors, dtype=">u2").tobytes()).hexdigest()
        if ordinal < pc.frames:
            reference.append(digest)
        elif digest != reference[frame]:
            faults.append(f"pixels differ: loop {ordinal // pc.frames}, frame {frame}")
        if any(digits[5:8]):
            faults.append(f"recovery counters: loop {ordinal // pc.frames}, frame {frame}: {digits[5:8]}")
        rows.append((ordinal // pc.frames, frame, *digits[5:8], digest))
    with output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, delimiter="\t", lineterminator="\n")
        writer.writerow(("loop", "frame", "sector_slip", "control_desync", "audio_resync", "rgb333_sha256"))
        writer.writerows(rows)
    complete = len(rows) // pc.frames
    if complete < min_loops:
        faults.append(f"only {complete} complete loops; need {min_loops}")
    if faults:
        raise ValueError(f"{len(faults)} faults; first: {faults[0]}; diagnostic TSV: {output}")
    print(f"PASS: {len(rows)} displayed frames, {complete} complete loops; every replay pixel matches loop 0; recovery counters zero")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--min-loops", type=int, default=3)
    args = parser.parse_args()
    if args.min_loops < 2 or args.tsv.suffix != ".tsv":
        parser.error("require --min-loops >= 2 and a .tsv output")
    verify(args.header, args.trace, args.tsv, args.min_loops)
