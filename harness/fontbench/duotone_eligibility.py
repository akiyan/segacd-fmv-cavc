#!/usr/bin/env python3
"""Measure 1bpp ("duotone") eligibility of a packed HEADER/BODY stream.

Walks the real v20 HEADER.DAT + BODY.DAT with the same reader logic as
harness/pattern_supply/verify.py (whose parsing helpers are imported), rebuilds
the displayed cell -> pattern state for every frame, and reports how much of
the movie a 2-color (<= 2 distinct 4-bit palette indices) pattern class would
cover:

- unique patterns ever armed into VRAM, by distinct-color histogram;
- displayed time-area (cell x frame) drawn by duotone patterns;
- timed BODY pattern deliveries (Prg payload + WordBuf refills) that are
  duotone, with the CD-byte saving if each shipped as 8 bytes + a color pair
  instead of 32 bytes.

Usage:
  tools/python.sh harness/fontbench/duotone_eligibility.py out/bad-apple
"""

from __future__ import annotations

import argparse
import importlib.util
import struct
import sys
import zlib
from collections import deque
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "pattern_supply_verify", REPO / "harness" / "pattern_supply" / "verify.py")
_verify = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _verify
_spec.loader.exec_module(_verify)

SECTOR = _verify.SECTOR
VERSION = _verify.VERSION
SOURCE_PRG = _verify.SOURCE_PRG
SOURCE_WR = _verify.SOURCE_WR
SOURCE_DIC = _verify.SOURCE_DIC
FEATURE_BOOT_VRAM_SIDECAR = _verify.FEATURE_BOOT_VRAM_SIDECAR

DUOTONE_PAYLOAD_BYTES = 8   # 64 px * 1 bit
DUOTONE_COLOR_BYTES = 1     # 4+4 bit color pair (descriptor spare bits could
                            # carry it; count it against the saving anyway)


def color_count(pattern: bytes) -> int:
    seen = set()
    for byte in pattern:
        seen.add(byte >> 4)
        seen.add(byte & 0xF)
    return len(seen)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stream_dir", type=Path,
                        help="directory with HEADER.DAT + BODY.DAT")
    args = parser.parse_args()

    header = (args.stream_dir / "HEADER.DAT").read_bytes()
    body = (args.stream_dir / "BODY.DAT").read_bytes()

    (magic, version, frames, cols, rows, cells, pool, base, _fsec,
     _nseg) = struct.unpack_from(">4s9H", header)
    if magic != b"TTRC" or version != VERSION:
        raise SystemExit(f"expected TTRC v{VERSION}, got {magic!r} v{version}")
    prebuf_patterns, routing_sectors, prebuf_sectors, _ring_peak = (
        struct.unpack_from(">4L", header, 22))
    f0_ctrl_sectors, f0_pattern_sectors, paltab_sectors = struct.unpack_from(
        ">3L", header, 40)
    vsync_n, decoded_audio, fps, _afd, audio_preload, features = (
        struct.unpack_from(">6H", header, 52))
    audio_bytes = 4 + decoded_audio // 2
    if zlib.crc32(header[:64]) & 0xFFFFFFFF != struct.unpack_from(
            ">L", header, 192)[0]:
        raise SystemExit("header signature mismatch")
    supply = struct.unpack_from(">4s9H", header, 196)
    if supply[0] != b"PSUP" or supply[1] != 3:
        raise SystemExit(f"invalid pattern-supply extension: {supply!r}")
    wr0_count, wr1_count, dic_count, wr0_sec, wr1_sec, dic_sec, _cold_cap = (
        supply[3:])

    cursor = SECTOR
    boot_stage = header[cursor:cursor + paltab_sectors * SECTOR]
    sidecar_vram: dict[int, bytes] = {}
    if boot_stage[0x0FC0:0x0FC4] == b"BVRM":
        region_counts = struct.unpack_from(">3H", boot_stage, 0x0FC4)
        for offset, count in zip((0x0000, 0x1000, 0x5000), region_counts,
                                 strict=True):
            for index in range(count):
                record = offset + index * 34
                slot = struct.unpack_from(">H", boot_stage, record)[0]
                sidecar_vram[slot] = boot_stage[record + 2:record + 34]
    cursor += len(boot_stage)
    dic_blob, cursor = _verify.take_region(
        header, cursor, dic_sec, dic_count * 32, "Dic")
    cursor += 5 * SECTOR
    wr0, cursor = _verify.take_region(header, cursor, wr0_sec, wr0_count * 32, "Wr0")
    wr1, cursor = _verify.take_region(header, cursor, wr1_sec, wr1_count * 32, "Wr1")
    routing_region = header[cursor:cursor + routing_sectors * SECTOR]
    routes = []
    for encoded in routing_region[:frames]:
        n_word = (encoded >> 6) & 3
        ctrl_field = encoded & 7
        n_ctrl = ctrl_field
        if ctrl_field & 4:
            n_ctrl = ctrl_field & 3
            n_word = 4
        total = (encoded >> 3) & 7
        routes.append((total - n_ctrl, n_ctrl, n_word))
    cursor += len(routing_region)
    prebuffer, cursor = _verify.take_region(
        header, cursor, prebuf_sectors, prebuf_patterns * 32, "Prg prebuffer")
    if cursor != len(header):
        raise SystemExit("unparsed HEADER bytes")

    body_cursor = audio_preload * SECTOR
    f0_region = body[body_cursor:body_cursor + f0_ctrl_sectors * SECTOR]
    f0_len = struct.unpack_from(">H", f0_region)[0]
    f0_control = _verify.parse_control(f0_region[:f0_len], 0, cells, audio_bytes)
    body_cursor += len(f0_region)
    f0_cold = sum(count for _s, count, source, _d in f0_control.runs
                  if source == SOURCE_PRG)
    f0_patterns, body_cursor = _verify.take_region(
        body, body_cursor, f0_pattern_sectors, f0_cold * 32, "frame 0 patterns")

    control_stream, body_payload, word_refill = _verify.body_streams(
        body[body_cursor:], routes, fps, vsync_n, features)
    controls = [f0_control]
    control_cursor = 0
    for frame in range(1, frames):
        length = struct.unpack_from(">H", control_stream, control_cursor)[0]
        controls.append(_verify.parse_control(
            control_stream[control_cursor:control_cursor + length], frame,
            cells, audio_bytes))
        control_cursor += length

    streamed_prg = prebuffer + body_payload
    wr_seq = (wr0 + word_refill[0], wr1 + word_refill[1])
    sources = {
        "F0": deque(f0_patterns[p:p + 32]
                    for p in range(0, len(f0_patterns), 32)),
        "Prg": deque(streamed_prg[p:p + 32]
                     for p in range(0, len(streamed_prg), 32)),
        "Wr0": deque(wr_seq[0][p:p + 32] for p in range(0, len(wr_seq[0]), 32)),
        "Wr1": deque(wr_seq[1][p:p + 32] for p in range(0, len(wr_seq[1]), 32)),
        "Dic": tuple(dic_blob[p:p + 32] for p in range(0, len(dic_blob), 32)),
    }
    consumed = {name: 0 for name in sources}

    duo_cache: dict[bytes, int] = {}

    def colors_of(pattern: bytes) -> int:
        n = duo_cache.get(pattern)
        if n is None:
            n = color_count(pattern)
            duo_cache[pattern] = n
        return n

    unique_hist: dict[bytes, int] = {}   # pattern -> distinct colors
    slot_duo = np.zeros(pool + 1, dtype=bool)   # last slot = "never armed"
    shadow = np.full(cells, pool, dtype=np.int32)
    timed_total = 0
    timed_duo = 0
    area_total = 0
    area_duo = 0
    per_frame_duo = np.zeros(frames, dtype=np.float64)

    for slot, pattern in sidecar_vram.items():
        unique_hist[pattern] = colors_of(pattern)
        slot_duo[slot] = colors_of(pattern) <= 2

    for frame, control in enumerate(controls):
        for run_slot, run_count, source_id, dic_index in control.runs:
            source_name = (
                "F0" if frame == 0 and source_id == SOURCE_PRG else
                "Prg" if source_id == SOURCE_PRG else
                ("Wr1" if frame & 1 else "Wr0") if source_id == SOURCE_WR else
                "Dic")
            for offset in range(run_count):
                slot = run_slot + offset
                if source_name == "Dic":
                    pattern = sources["Dic"][dic_index + offset]
                else:
                    pattern = sources[source_name].popleft()
                index = consumed[source_name]
                consumed[source_name] += 1
                colors = colors_of(pattern)
                unique_hist[pattern] = colors
                slot_duo[slot] = colors <= 2
                # Timed CD deliveries: Prg beyond the HEADER prebuffer, and
                # WordBuf entries beyond the boot preload (BODY refills).
                if source_name == "Prg" and index >= prebuf_patterns:
                    timed_total += 1
                    timed_duo += colors <= 2
                elif source_name == "Wr0" and index >= wr0_count:
                    timed_total += 1
                    timed_duo += colors <= 2
                elif source_name == "Wr1" and index >= wr1_count:
                    timed_total += 1
                    timed_duo += colors <= 2

        if control.entries:
            update_cells = _verify.bitmap_cells(control.bitmap, cells)
            for cell, entry in zip(update_cells, control.entries, strict=True):
                shadow[cell] = (entry & 0x07FF) - base
        if frame == 0 and np.any(shadow == pool):
            raise SystemExit("frame 0 leaves cells without a name entry")
        duo_cells = int(slot_duo[shadow].sum())
        area_total += cells
        area_duo += duo_cells
        per_frame_duo[frame] = duo_cells / cells

    hist = {}
    for colors in unique_hist.values():
        hist[colors] = hist.get(colors, 0) + 1

    print(f"stream\t{args.stream_dir}")
    print(f"frames\t{frames}\tcells\t{cells}\tpool\t{pool}")
    print()
    unique_total = len(unique_hist)
    unique_duo = sum(count for colors, count in hist.items() if colors <= 2)
    print("distinct_colors\tunique_patterns\tshare")
    for colors in sorted(hist):
        label = str(colors) if colors < 5 else str(colors)
        print(f"{label}\t{hist[colors]}\t{hist[colors] / unique_total:.1%}")
    print(f"unique_total\t{unique_total}")
    print(f"unique_duotone(<=2)\t{unique_duo}\t{unique_duo / unique_total:.1%}")
    print()
    print(f"time_area_total(cell*frames)\t{area_total}")
    print(f"time_area_duotone\t{area_duo}\t{area_duo / area_total:.1%}")
    print(f"per_frame_duotone_share\tmin {per_frame_duo.min():.1%}"
          f"\tmedian {np.median(per_frame_duo):.1%}"
          f"\tmax {per_frame_duo.max():.1%}")
    print()
    saved = timed_duo * (32 - DUOTONE_PAYLOAD_BYTES - DUOTONE_COLOR_BYTES)
    print(f"timed_pattern_deliveries\t{timed_total}")
    print(f"timed_duotone\t{timed_duo}\t"
          f"{timed_duo / timed_total:.1%}" if timed_total else "n/a")
    print(f"timed_pattern_bytes\t{timed_total * 32}")
    print(f"duotone_saving_bytes\t{saved}\t"
          f"{saved / (timed_total * 32):.1%} of timed pattern bytes")
    untimed = {
        "F0": consumed["F0"],
        "Prg_prebuffer": min(consumed["Prg"], prebuf_patterns),
        "Wr0_boot": min(consumed["Wr0"], wr0_count),
        "Wr1_boot": min(consumed["Wr1"], wr1_count),
        "Dic_hits": consumed["Dic"],
        "sidecar": len(sidecar_vram),
    }
    print()
    print("consumption\t" + "\t".join(f"{k}={v}" for k, v in untimed.items()))


if __name__ == "__main__":
    main()
