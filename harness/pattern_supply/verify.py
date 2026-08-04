#!/usr/bin/env python3
"""Independently replay the current Prg/Wr0/Wr1/Dic pattern supply format.

This verifier deliberately does not import the production packer, scheduler,
or pattern-supply planner.  It walks the real HEADER.DAT and BODY.DAT, consumes
every source in player order, and compares every resulting VRAM tile with the
authenticated decision log.
"""

from __future__ import annotations

import argparse
import pickle
import struct
import zlib
from collections import deque
from dataclasses import dataclass
from pathlib import Path


SECTOR = 2048
PATTERN_BYTES = 32
CONTROL_SUFFIX_HEADER_BYTES = 2
FEATURE_COLD_RUNS = 0x0001
FEATURE_VBLANK_CADENCE = 0x0002
FEATURE_PATTERN_SUPPLY = 0x0008
FEATURE_SHADOW_UPDATE_LISTS = 0x0010
FEATURE_VRAM_RAW_PREFETCH = 0x0020
FEATURE_DICBUF_INDEXED_RUNS = 0x0040
FEATURE_BOOT_VRAM_SIDECAR = 0x0080
SOURCE_PRG = 0
SOURCE_WR = 1
SOURCE_DIC = 2
SOURCE_MASK = 0x1800
SOURCE_SHIFT = 11
RUN_COUNT_MASK = 0x07FF
RUN_SOURCE_SHIFT = 14
DIC_RUN_BLOCK = 256
DIC_CAPACITY = 512
ENTRY_DISPLAY_MASK = 0x67FF
SHADOW_UPDATE_LIST_TAG = 0x8000
SHADOW_FRAME_TYPE_MASK = 0x6000
SHADOW_FRAME_TYPE_SHIFT = 13
SHADOW_FRAME_TYPE_RESERVED = 3
SHADOW_UPDATE_COUNT_MASK = 0x1FFF
INLINE_CRAM_BYTES = 128
WORD_RAM_BANK_BYTES = 0x20000
OUTPUT_HEADER_BYTES = 4
OUTPUT_RUN_RECORD_BYTES = 22
OUTPUT_MAIN_BASE = 0x200000
DIC_MAIN_BASE = 0xFFBA40
STATUS_BYTES = 0x0100
CTRL_SCR_BYTES = 0x2000
PAD_SCR_BYTES = 0x0800


@dataclass(frozen=True)
class Control:
    seq: int
    bitmap: bytes
    entries: tuple[int, ...]
    runs: tuple[tuple[int, int, int, int], ...]
    use_list: bool


def packed_pattern(key: bytes) -> bytes:
    if len(key) != 64:
        raise AssertionError(f"decision pattern has {len(key)} pixels, expected 64")
    out = bytearray()
    for pos in range(0, 64, 2):
        high, low = key[pos], key[pos + 1]
        if high > 15 or low > 15:
            raise AssertionError("decision pattern contains a palette index above 15")
        out.append((high << 4) | low)
    return bytes(out)


def raw_prefetch_expectations(
    decisions: dict,
    frames: int,
    pool: int,
    feature_enabled: bool,
) -> tuple[
    tuple[tuple[tuple[int, bytes], ...], ...],
    tuple[tuple[int, bytes], ...],
]:
    """Return inline and boot-sidecar raw-prefetch records in packed order."""
    raw = decisions.get("raw_prefetch") or {}
    enabled = bool(raw.get("enabled", False))
    if enabled != feature_enabled:
        raise AssertionError(
            "raw-prefetch decision/header feature state differs")
    empty = tuple(() for _ in range(frames))
    if not enabled:
        return empty, ()
    if int(raw.get("schema_version", 0)) != 3:
        raise AssertionError("raw-prefetch decisions are not schema 3")

    requests = raw.get("requests")
    cold_trace = raw.get("cold")
    if requests is None or len(requests) != frames:
        raise AssertionError("raw-prefetch request frame count differs")
    if cold_trace is None or len(cold_trace) != frames:
        raise AssertionError("raw-prefetch cold trace frame count differs")

    expected = []
    for frame, (frame_requests, cold_count) in enumerate(
            zip(requests, cold_trace, strict=True)):
        if len(frame_requests) != int(cold_count):
            raise AssertionError(
                f"frame {frame}: raw-prefetch requests/cold count differ")
        records = []
        seen_slots = set()
        for request in frame_requests:
            if len(request) != 3:
                raise AssertionError(
                    f"frame {frame}: raw-prefetch request has no frozen slot")
            key, deadline, raw_slot = request
            slot = int(raw_slot)
            if not 0 <= slot < pool:
                raise AssertionError(
                    f"frame {frame}: raw-prefetch slot {slot} is outside the pool")
            if slot in seen_slots:
                raise AssertionError(
                    f"frame {frame}: duplicate raw-prefetch slot {slot}")
            if int(deadline) <= frame:
                raise AssertionError(
                    f"frame {frame}: raw-prefetch deadline {deadline} is not future")
            records.append((slot, packed_pattern(bytes(key))))
            seen_slots.add(slot)
        expected.append(tuple(sorted(records)))

    inline_count = int(raw.get("boot_inline_requests", -1))
    sidecar_count = int(raw.get("boot_sidecar_requests", -1))
    if min(inline_count, sidecar_count) < 0:
        raise AssertionError("raw-prefetch boot split is missing")
    if inline_count + sidecar_count != len(expected[0]):
        raise AssertionError("raw-prefetch boot split differs from frame 0")
    frame0 = expected[0]
    expected[0] = frame0[:inline_count]
    sidecar = frame0[inline_count:inline_count + sidecar_count]
    return tuple(expected), sidecar


def parse_control(raw: bytes, seq: int, cells: int, audio_bytes: int) -> Control:
    if len(raw) < 8:
        raise AssertionError(f"frame {seq}: control is truncated")
    total, packed_seq, raw_count = struct.unpack_from(">HHH", raw)
    n_upd = raw_count & SHADOW_UPDATE_COUNT_MASK
    use_list = bool(raw_count & SHADOW_UPDATE_LIST_TAG)
    frame_type = (
        raw_count & SHADOW_FRAME_TYPE_MASK) >> SHADOW_FRAME_TYPE_SHIFT
    if total != len(raw) or total & 1:
        raise AssertionError(f"frame {seq}: invalid total_len {total}/{len(raw)}")
    if packed_seq != seq or n_upd > cells:
        raise AssertionError(
            f"frame {seq}: packed seq/count is {packed_seq}/{n_upd}, cells={cells}")
    if frame_type == SHADOW_FRAME_TYPE_RESERVED:
        raise AssertionError(f"frame {seq}: reserved frame type")
    if frame_type and (n_upd or use_list):
        raise AssertionError(f"frame {seq}: fade control carries updates")

    bitmap_start = 6
    bitmap_bytes = (cells + 7) // 8
    bitmap_end = bitmap_start + bitmap_bytes
    entries_start = (bitmap_end + 1) & ~1
    entries_end = entries_start + n_upd * 2
    if use_list:
        entries_start = bitmap_start
        entries_end = entries_start + n_upd * 4
    elif frame_type:
        entries_start = bitmap_start
        entries_end = entries_start + INLINE_CRAM_BYTES
    audio_end = entries_end + audio_bytes
    suffix_start = (audio_end + 1) & ~1
    if suffix_start + CONTROL_SUFFIX_HEADER_BYTES > len(raw):
        raise AssertionError(f"frame {seq}: descriptor suffix is truncated")
    if raw[audio_end:suffix_start] != (b"\0" if audio_end & 1 else b""):
        raise AssertionError(f"frame {seq}: invalid audio alignment byte")

    if frame_type:
        bitmap = bytes(bitmap_bytes)
        entries = ()
    elif use_list:
        bitmap_mut = bytearray(bitmap_bytes)
        entries_mut = []
        previous_cell = -1
        for index in range(n_upd):
            offset, entry = struct.unpack_from(">HH", raw, entries_start + index * 4)
            if offset & 1 or offset >= cells * 2:
                raise AssertionError(f"frame {seq}: invalid shadow offset {offset}")
            cell = offset // 2
            if cell <= previous_cell:
                raise AssertionError(f"frame {seq}: list cells are not ascending")
            bitmap_mut[cell >> 3] |= 1 << (cell & 7)
            entries_mut.append(entry)
            previous_cell = cell
        bitmap = bytes(bitmap_mut)
        entries = tuple(entries_mut)
    else:
        bitmap = raw[bitmap_start:bitmap_end]
        if any(raw[bitmap_end:entries_start]):
            raise AssertionError(f"frame {seq}: bitmap alignment pad is nonzero")
        entries = (
            tuple(struct.unpack_from(f">{n_upd}H", raw, entries_start))
            if n_upd else ()
        )
    if sum(value.bit_count() for value in bitmap) != n_upd:
        raise AssertionError(f"frame {seq}: update cell population differs from n_upd")
    n_runs = struct.unpack_from(">H", raw, suffix_start)[0]
    descriptor_start = suffix_start + CONTROL_SUFFIX_HEADER_BYTES
    suffix_end = descriptor_start + n_runs * 4
    if suffix_end != len(raw):
        raise AssertionError(
            f"frame {seq}: descriptor suffix ends at {suffix_end}, total={len(raw)}")
    runs = []
    for index in range(n_runs):
        word0, encoded = struct.unpack_from(
            ">HH", raw, descriptor_start + index * 4)
        slot = word0 & 0x07FF
        count = encoded & RUN_COUNT_MASK
        raw_source = encoded >> RUN_SOURCE_SHIFT
        dic_index = ((word0 >> 11) << 3) | ((encoded >> 11) & 7)
        if not count or raw_source > 3:
            raise AssertionError(
                f"frame {seq}: invalid run {index}: "
                f"slot={slot} count={count} source={raw_source}")
        if raw_source >= SOURCE_DIC:
            if dic_index + count > DIC_RUN_BLOCK:
                raise AssertionError(
                    f"frame {seq}: Dic run {index} crosses its 256-entry block")
            dic_index += (raw_source - SOURCE_DIC) * DIC_RUN_BLOCK
            source = SOURCE_DIC
        else:
            source = raw_source
            if dic_index:
                raise AssertionError(
                    f"frame {seq}: non-Dic run carries index {dic_index}")
        runs.append((slot, count, source, dic_index))
    return Control(seq, bitmap, entries, tuple(runs), use_list)


def expected_runs(entries: tuple[int, ...], base: int) -> tuple[tuple[int, int, int], ...]:
    runs: list[list[int]] = []
    previous_slot = -2
    previous_source = -1
    for entry in entries:
        if not entry & 0x8000:
            if entry & SOURCE_MASK:
                raise AssertionError("reuse entry carries a pattern source")
            continue
        source = (entry & SOURCE_MASK) >> SOURCE_SHIFT
        slot = (entry & 0x07FF) - base
        if runs and source == previous_source and slot == previous_slot + 1:
            runs[-1][1] += 1
        else:
            runs.append([slot, 1, source])
        previous_slot = slot
        previous_source = source
    # Keep this hot full-movie path as an explicit loop. Managed CPython 3.14.4
    # has crashed in executor invalidation after repeatedly specializing the
    # nested generator expression here on a 6,576-frame stream.
    frozen = []
    for slot, count, source in runs:
        frozen.append((slot, count, source))
    return tuple(frozen)


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) // alignment * alignment


def vdp_destination_command(destination: int) -> int:
    """Return the exact 68000 VDP write command emitted by Sub."""
    return (
        0x40000000
        | ((destination & 0x3FFF) << 16)
        | ((destination >> 14) & 0x0003)
    )


def vdp_source_registers(raw_source: int, source: int) -> tuple[int, int, int]:
    """Return registers 95-97, including the measured Word-RAM +2 fix."""
    corrected = raw_source if source == SOURCE_DIC else raw_source + 2
    word_source = corrected >> 1
    return (
        0x9500 | (word_source & 0xFF),
        0x9600 | ((word_source >> 8) & 0xFF),
        0x9700 | ((word_source >> 16) & 0xFF),
    )


def encode_loads_v2(
    transfers: list[tuple[int, int, int, tuple[bytes, ...]]],
    *,
    parity: int,
    base: int,
    word_ptrs: list[int],
    word_starts: tuple[int, int],
    word_ends: tuple[int, int],
) -> tuple[bytes, dict[int, bytes]]:
    """Model Sub's source resolution and exact interleaved O_LOADS v2 bytes."""
    loads = bytearray()
    external: dict[int, bytes] = {}
    n_load = 0
    for slot, source, dic_index, patterns in transfers:
        count = len(patterns)
        if count <= 0:
            raise AssertionError("O_LOADS v2 cannot encode an empty run")
        record_start = OUTPUT_HEADER_BYTES + len(loads)
        if source == SOURCE_PRG:
            raw_source = OUTPUT_MAIN_BASE + record_start + OUTPUT_RUN_RECORD_BYTES
        elif source == SOURCE_WR:
            pointer = word_ptrs[parity]
            if pointer == word_ends[parity]:
                pointer = word_starts[parity]
            end = pointer + count * PATTERN_BYTES
            if end > word_ends[parity]:
                raise AssertionError(
                    f"Wr{parity} run crosses its generated ring end: "
                    f"{pointer:#x}+{count} patterns > {word_ends[parity]:#x}")
            raw_source = OUTPUT_MAIN_BASE + pointer
            word_ptrs[parity] = end
        elif source == SOURCE_DIC:
            raw_source = DIC_MAIN_BASE + dic_index * PATTERN_BYTES
        else:
            raise AssertionError(f"invalid O_LOADS v2 source {source}")

        destination = (base + slot) * PATTERN_BYTES
        length_words = count * PATTERN_BYTES // 2
        reg93 = 0x9300 | (length_words & 0xFF)
        reg94 = 0x9400 | ((length_words >> 8) & 0xFF)
        reg95, reg96, reg97 = vdp_source_registers(raw_source, source)
        loads += struct.pack(
            ">HHHLHHHHL",
            length_words,
            reg93,
            reg94,
            vdp_destination_command(destination),
            destination,
            reg95,
            reg96,
            reg97,
            raw_source,
        )
        if source == SOURCE_PRG:
            loads += b"".join(patterns)
        else:
            for index, pattern in enumerate(patterns):
                address = raw_source + index * PATTERN_BYTES
                previous = external.setdefault(address, pattern)
                if previous != pattern:
                    raise AssertionError(
                        f"two O_LOADS sources disagree at {address:#x}")
        n_load += count
    return struct.pack(">HH", len(transfers), n_load) + loads, external


def decode_loads_v2(
    output: bytes,
    external: dict[int, bytes],
    *,
    base: int,
) -> tuple[tuple[int, int, int, tuple[bytes, ...]], ...]:
    """Model Main's single-cursor in-place consumption of O_LOADS v2."""
    if len(output) < OUTPUT_HEADER_BYTES:
        raise AssertionError("O_LOADS v2 output is truncated")
    n_runs, n_load = struct.unpack_from(">HH", output)
    cursor = OUTPUT_HEADER_BYTES
    decoded = []
    decoded_loads = 0
    for run_index in range(n_runs):
        if cursor + OUTPUT_RUN_RECORD_BYTES > len(output):
            raise AssertionError(f"O_LOADS v2 run {run_index} is truncated")
        (
            length_words,
            reg93,
            reg94,
            command,
            destination,
            reg95,
            reg96,
            reg97,
            raw_source,
        ) = struct.unpack_from(">HHHLHHHHL", output, cursor)
        cursor += OUTPUT_RUN_RECORD_BYTES
        if length_words == 0 or length_words & 15:
            raise AssertionError(
                f"O_LOADS v2 run {run_index} has invalid length {length_words}")
        count = length_words // 16
        if (reg93, reg94) != (
                0x9300 | (length_words & 0xFF),
                0x9400 | ((length_words >> 8) & 0xFF)):
            raise AssertionError(
                f"O_LOADS v2 run {run_index} has invalid length registers")
        if destination % PATTERN_BYTES:
            raise AssertionError(
                f"O_LOADS v2 run {run_index} has unaligned destination")
        slot = destination // PATTERN_BYTES - base
        if command != vdp_destination_command(destination):
            raise AssertionError(
                f"O_LOADS v2 run {run_index} has invalid VDP command")

        inline_source = OUTPUT_MAIN_BASE + cursor
        if raw_source == inline_source:
            source = SOURCE_PRG
            byte_count = count * PATTERN_BYTES
            payload = output[cursor:cursor + byte_count]
            if len(payload) != byte_count:
                raise AssertionError(
                    f"O_LOADS v2 run {run_index} inline Prg is truncated")
            patterns = tuple(
                payload[pos:pos + PATTERN_BYTES]
                for pos in range(0, byte_count, PATTERN_BYTES)
            )
            cursor += byte_count
            dic_index = 0
        else:
            source = SOURCE_DIC if raw_source >= DIC_MAIN_BASE else SOURCE_WR
            dic_index = (
                (raw_source - DIC_MAIN_BASE) // PATTERN_BYTES
                if source == SOURCE_DIC else 0
            )
            try:
                patterns = tuple(
                    external[raw_source + index * PATTERN_BYTES]
                    for index in range(count)
                )
            except KeyError as exc:
                raise AssertionError(
                    f"O_LOADS v2 run {run_index} points outside resolved storage"
                ) from exc
        if (reg95, reg96, reg97) != vdp_source_registers(raw_source, source):
            raise AssertionError(
                f"O_LOADS v2 run {run_index} has invalid source registers")
        decoded.append((slot, source, dic_index, patterns))
        decoded_loads += count
    if cursor != len(output):
        raise AssertionError(
            f"O_LOADS v2 leaves {len(output) - cursor} unconsumed bytes")
    if decoded_loads != n_load:
        raise AssertionError(
            f"O_NLOAD {n_load} differs from records {decoded_loads}")
    return tuple(decoded)


def take_region(
    header: bytes, cursor: int, sectors: int, useful_bytes: int, label: str,
) -> tuple[bytes, int]:
    region = header[cursor:cursor + sectors * SECTOR]
    if len(region) != sectors * SECTOR:
        raise AssertionError(f"{label} is truncated")
    if useful_bytes > len(region):
        raise AssertionError(f"{label} useful bytes exceed its sectors")
    if any(region[useful_bytes:]):
        raise AssertionError(f"{label} sector padding is nonzero")
    return region[:useful_bytes], cursor + len(region)


def body_streams(
    body: bytes, routes: list[tuple[int, int, int]], fps: int, vsync_n: int,
    features: int,
) -> tuple[bytes, bytes, tuple[bytes, bytes]]:
    """Split BODY slots into control, Prg payload, and parity WordBuf refills.

    Each timed slot is [n_ctrl control][n_word WordBuf refill for the frame's
    parity bank][n_pay - n_word Prg payload][rate pad]."""
    if features & FEATURE_VBLANK_CADENCE and fps == 24:
        numerators, modulus = (2002, 3003), 800
    elif features & FEATURE_VBLANK_CADENCE:
        numerators, modulus = (1001 * vsync_n,), 800
    else:
        numerators, modulus = (75,), fps
    accumulator = 0
    lead = 0
    cursor = 0
    controls = bytearray()
    payload = bytearray()
    word_refill = [bytearray(), bytearray()]
    for frame, (n_pay, n_ctrl, n_word) in enumerate(routes[1:], start=1):
        accumulator += numerators[(frame - 1) % len(numerators)]
        rated, accumulator = divmod(accumulator, modulus)
        actual = n_pay + n_ctrl
        sectors = max(actual, rated - lead)
        lead += sectors - rated
        slot = body[cursor:cursor + sectors * SECTOR]
        if len(slot) != sectors * SECTOR:
            raise AssertionError(f"frame {frame}: BODY slot is truncated")
        controls += slot[:n_ctrl * SECTOR]
        word_end = (n_ctrl + n_word) * SECTOR
        word_refill[frame & 1] += slot[n_ctrl * SECTOR:word_end]
        payload += slot[word_end:actual * SECTOR]
        if any(slot[actual * SECTOR:]):
            raise AssertionError(f"frame {frame}: rate padding is nonzero")
        cursor += len(slot)
    if cursor != len(body):
        raise AssertionError(f"BODY has {len(body) - cursor} unrouted bytes")
    return (
        bytes(controls), bytes(payload),
        (bytes(word_refill[0]), bytes(word_refill[1])),
    )


def bitmap_cells(bitmap: bytes, cells: int) -> list[int]:
    return [
        cell for cell in range(cells)
        if bitmap[cell >> 3] & (1 << (cell & 7))
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", type=Path, required=True)
    parser.add_argument("--body", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    args = parser.parse_args()

    header = args.header.read_bytes()
    body = args.body.read_bytes()
    if len(header) < SECTOR:
        raise SystemExit("HEADER.DAT is shorter than one sector")
    (
        magic, frames, cols, rows, cells, pool, base, _frame_sectors,
        nseg,
    ) = struct.unpack_from(">4s8H", header)
    if magic != b"CAVC" or cols * rows != cells:
        raise SystemExit(
            f"expected CAVC, got {magic!r} {cols}x{rows}/{cells}")
    prebuf_patterns, routing_sectors, prebuf_sectors, _ring_peak = struct.unpack_from(
        ">4L", header, 20)
    f0_ctrl_sectors, f0_pattern_sectors, paltab_sectors = struct.unpack_from(
        ">3L", header, 38)
    vsync_n, decoded_audio, fps, _audio_fd, audio_preload, features = struct.unpack_from(
        ">6H", header, 50)
    required_supply_features = (
        FEATURE_COLD_RUNS | FEATURE_PATTERN_SUPPLY
        | FEATURE_DICBUF_INDEXED_RUNS)
    if features & required_supply_features != required_supply_features:
        raise SystemExit(
            f"expected cold-run/pattern-supply/indexed-DicBuf features, "
            f"got 0x{features:04X}")
    if features & FEATURE_SHADOW_UPDATE_LISTS and not features & FEATURE_PATTERN_SUPPLY:
        raise SystemExit("shadow update lists require pattern supply")
    if vsync_n <= 0 or fps <= 0:
        raise SystemExit(f"invalid supply timing N={vsync_n} fps={fps}")
    audio_bytes = 4 + decoded_audio // 2
    signature = struct.unpack_from(">L", header, 192)[0]
    expected_signature = zlib.crc32(header[:62]) & 0xFFFFFFFF
    if signature != expected_signature:
        raise AssertionError(
            f"header signature 0x{signature:08X} != 0x{expected_signature:08X}")

    supply = struct.unpack_from(">4s11H", header, 196)
    magic_supply, supply_version, reserved = supply[:3]
    (wr0_count, wr1_count, dic_count, wr0_sec, wr1_sec, dic_sec,
     _cold_cap, wr0_load_bytes, wr1_load_bytes) = supply[3:]
    if magic_supply != b"PSUP" or supply_version != 4 or reserved:
        raise AssertionError(f"invalid pattern-supply extension: {supply!r}")
    status_offset = (
        WORD_RAM_BANK_BYTES
        - routing_sectors * SECTOR
        - PAD_SCR_BYTES
        - CTRL_SCR_BYTES
        - STATUS_BYTES
    )
    word_starts = (
        align_up(OUTPUT_HEADER_BYTES + wr0_load_bytes, PATTERN_BYTES),
        align_up(OUTPUT_HEADER_BYTES + wr1_load_bytes, PATTERN_BYTES),
    )
    word_ends = tuple(
        start + ((status_offset - start) // SECTOR) * SECTOR
        for start in word_starts
    )
    word_capacities = tuple(
        (end - start) // PATTERN_BYTES
        for start, end in zip(word_starts, word_ends, strict=True)
    )
    for label, count, sectors, capacity in (
        ("Wr0", wr0_count, wr0_sec, word_capacities[0]),
        ("Wr1", wr1_count, wr1_sec, word_capacities[1]),
        ("Dic", dic_count, dic_sec, DIC_CAPACITY),
    ):
        if count > capacity or sectors != (count + 63) // 64:
            raise AssertionError(
                f"{label}: count/sectors {count}/{sectors}, capacity={capacity}")

    cursor = SECTOR
    boot_stage = header[cursor:cursor + paltab_sectors * SECTOR]
    if len(boot_stage) != paltab_sectors * SECTOR:
        raise AssertionError("boot stage is truncated")
    # v25: no palette rides the boot stage; the sidecar regions are fixed.
    sidecar_vram = {}
    if boot_stage[0x0FC0:0x0FC4] == b"BVRM":
        region_counts = struct.unpack_from(">3H", boot_stage, 0x0FC4)
        region_offsets = (0x0000, 0x1000, 0x5000)
        for offset, count in zip(region_offsets, region_counts, strict=True):
            for index in range(count):
                record = offset + index * 34
                slot = struct.unpack_from(">H", boot_stage, record)[0]
                pattern = boot_stage[record + 2:record + 34]
                if len(pattern) != 32 or slot in sidecar_vram:
                    raise AssertionError("invalid/duplicate boot sidecar record")
                sidecar_vram[slot] = pattern
    cursor += len(boot_stage)
    dic_blob, cursor = take_region(
        header, cursor, dic_sec, dic_count * 32, "Dic")
    cursor += 5 * SECTOR
    wr0, cursor = take_region(header, cursor, wr0_sec, wr0_count * 32, "Wr0")
    wr1, cursor = take_region(header, cursor, wr1_sec, wr1_count * 32, "Wr1")

    routing_region = header[cursor:cursor + routing_sectors * SECTOR]
    if len(routing_region) != routing_sectors * SECTOR:
        raise AssertionError("routing is truncated")
    if routing_region[0] or any(routing_region[frames:]):
        raise AssertionError("routing frame 0 or sector padding is nonzero")
    routes = []
    for frame, encoded in enumerate(routing_region[:frames]):
        # bits 6-7 carry the WordBuf payload prefix; ctrl bit 2 is the
        # 4-sector escape (base 3 in the word field).
        n_word = (encoded >> 6) & 3
        ctrl_field = encoded & 7
        n_ctrl = ctrl_field
        if ctrl_field & 4:
            if n_word != 3:
                raise AssertionError(
                    f"frame {frame}: WordBuf-4 escape lacks base 3: 0x{encoded:02X}")
            n_ctrl = ctrl_field & 3
            n_word = 4
        total = (encoded >> 3) & 7
        if n_ctrl > total or total > 5 or n_word > total - n_ctrl:
            raise AssertionError(f"frame {frame}: invalid route 0x{encoded:02X}")
        routes.append((total - n_ctrl, n_ctrl, n_word))
    cursor += len(routing_region)
    prebuffer, cursor = take_region(
        header, cursor, prebuf_sectors, prebuf_patterns * 32, "Prg prebuffer")
    if cursor != len(header):
        raise AssertionError(f"HEADER has {len(header) - cursor} unparsed bytes")

    body_cursor = audio_preload * SECTOR
    f0_region = body[
        body_cursor:body_cursor + f0_ctrl_sectors * SECTOR
    ]
    if len(f0_region) != f0_ctrl_sectors * SECTOR:
        raise AssertionError("frame 0 control region is truncated")
    f0_len = struct.unpack_from(">H", f0_region)[0]
    f0_control = parse_control(f0_region[:f0_len], 0, cells, audio_bytes)
    if any(f0_region[f0_len:]):
        raise AssertionError("frame 0 control sector padding is nonzero")
    body_cursor += len(f0_region)
    f0_cold = sum(
        count for _slot, count, source, _dic_index in f0_control.runs
        if source == SOURCE_PRG)
    f0_patterns, body_cursor = take_region(
        body, body_cursor, f0_pattern_sectors, f0_cold * 32, "frame 0 patterns")

    control_stream, body_payload, word_refill = body_streams(
        body[body_cursor:], routes, fps, vsync_n, features)
    controls = [f0_control]
    control_cursor = 0
    for frame in range(1, frames):
        if control_cursor + 2 > len(control_stream):
            raise AssertionError(f"frame {frame}: missing control length")
        length = struct.unpack_from(">H", control_stream, control_cursor)[0]
        raw = control_stream[control_cursor:control_cursor + length]
        if len(raw) != length:
            raise AssertionError(f"frame {frame}: control is truncated")
        controls.append(parse_control(raw, frame, cells, audio_bytes))
        control_cursor += length
    if any(control_stream[control_cursor:]):
        raise AssertionError("nonzero bytes follow the final control")

    with args.decisions.open("rb") as source:
        decisions = pickle.load(source)
    decision_frames = decisions["frames"]
    if len(decision_frames) != frames:
        raise AssertionError(
            f"decision log has {len(decision_frames)} frames, stream has {frames}")
    raw_prefetch_per, expected_sidecar = raw_prefetch_expectations(
        decisions,
        frames,
        pool,
        bool(features & FEATURE_VRAM_RAW_PREFETCH),
    )
    expected_sidecar_vram = dict(expected_sidecar)
    if len(expected_sidecar_vram) != len(expected_sidecar):
        raise AssertionError("raw-prefetch boot sidecar has duplicate slots")
    if sidecar_vram != expected_sidecar_vram:
        raise AssertionError(
            "boot sidecar slots/patterns differ from raw-prefetch decisions")
    if bool(expected_sidecar) != bool(features & FEATURE_BOOT_VRAM_SIDECAR):
        raise AssertionError(
            "boot sidecar decision/header feature state differs")

    prg_count = sum(
        count for frame, control in enumerate(controls) if frame
        for _slot, count, source, _dic in control.runs if source == SOURCE_PRG)
    streamed_prg = prebuffer + body_payload
    useful_prg_bytes = prg_count * 32
    if len(streamed_prg) < useful_prg_bytes or any(streamed_prg[useful_prg_bytes:]):
        raise AssertionError("Prg payload length/padding does not match source-coded entries")

    # The parity WordBuf sequence is the boot preload followed by every timed
    # refill sector for that parity in arrival order. Refill sectors carry no
    # padding (pack fills each with complete patterns).
    if any(len(refill) % 32 for refill in word_refill):
        raise AssertionError("WordBuf refill stream is not pattern aligned")
    wr_seq = (wr0 + word_refill[0], wr1 + word_refill[1])
    sources = {
        "F0": deque(
            f0_patterns[pos:pos + 32] for pos in range(0, len(f0_patterns), 32)),
        "Prg": deque(
            streamed_prg[pos:pos + 32] for pos in range(0, useful_prg_bytes, 32)),
        "Wr0": deque(
            wr_seq[0][pos:pos + 32] for pos in range(0, len(wr_seq[0]), 32)),
        "Wr1": deque(
            wr_seq[1][pos:pos + 32] for pos in range(0, len(wr_seq[1]), 32)),
        "Dic": tuple(
            dic_blob[pos:pos + 32] for pos in range(0, len(dic_blob), 32)),
    }
    consumed = {name: 0 for name in sources}
    vram: dict[int, bytes] = dict(sidecar_vram)
    vram_v2: dict[int, bytes] = dict(sidecar_vram)
    word_ptrs = list(word_starts)
    loads_peaks = [0, 0]
    total_updates = 0
    total_cold = len(sidecar_vram)

    for frame, (decision_frame, control) in enumerate(
            zip(decision_frames, controls, strict=True)):
        ordered = sorted(decision_frame, key=lambda item: int(item[0]))
        cells_expected = [int(item[0]) for item in ordered]
        if bitmap_cells(control.bitmap, cells) != cells_expected:
            raise AssertionError(f"frame {frame}: bitmap cells differ from decisions")
        if len(ordered) != len(control.entries):
            raise AssertionError(f"frame {frame}: decision/update count differs")
        expected_prefetch_slots = tuple(
            (slot, SOURCE_PRG) for slot, _pattern in raw_prefetch_per[frame])
        actual_slots = tuple(
            (slot, source)
            for start, count, source, _dic in control.runs
            for slot in range(start, start + count))
        if expected_prefetch_slots:
            if actual_slots[-len(expected_prefetch_slots):] != (
                    expected_prefetch_slots):
                raise AssertionError(
                    f"frame {frame}: raw-prefetch run suffix differs")
            actual_update_slots = actual_slots[:-len(expected_prefetch_slots)]
        else:
            actual_update_slots = actual_slots
        if control.use_list:
            if actual_update_slots != tuple(sorted(actual_update_slots)):
                raise AssertionError(
                    f"frame {frame}: update runs are not in physical-slot order")
            entry_slots = {
                (entry & 0x07FF) - base for entry in control.entries
            }
            if any(slot not in entry_slots for slot, _source in actual_update_slots):
                raise AssertionError(
                    f"frame {frame}: update runs contain a non-update slot")
            expected_update_slots = actual_update_slots
        else:
            expected_update_slots = tuple(sorted(
                (
                    (entry & 0x07FF) - base,
                    (entry & SOURCE_MASK) >> SOURCE_SHIFT,
                )
                for entry in control.entries if entry & 0x8000
            ))
        expected_transfer_slots = (
            expected_update_slots + expected_prefetch_slots)
        if len({slot for slot, _source in expected_transfer_slots}) != len(
                expected_transfer_slots):
            raise AssertionError(
                f"frame {frame}: update/raw-prefetch slots overlap")
        if actual_slots != expected_transfer_slots:
            raise AssertionError(
                f"frame {frame}: source-coded update/prefetch runs differ")

        expected_by_slot = {}
        for item, entry in zip(ordered, control.entries, strict=True):
            expected_by_slot[(entry & 0x07FF) - base] = packed_pattern(bytes(item[2]))
        for slot, pattern in raw_prefetch_per[frame]:
            if slot in expected_by_slot:
                raise AssertionError(
                    f"frame {frame}: raw-prefetch overwrites update slot {slot}")
            expected_by_slot[slot] = pattern

        armed_slots = set()
        frame_transfers = []
        for run_slot, run_count, source_id, dic_index in control.runs:
            source_name = (
                "F0" if frame == 0 and source_id == SOURCE_PRG else
                "Prg" if source_id == SOURCE_PRG else
                ("Wr1" if frame & 1 else "Wr0") if source_id == SOURCE_WR else
                "Dic" if source_id == SOURCE_DIC else "reserved"
            )
            run_patterns = []
            for slot in range(run_slot, run_slot + run_count):
                if slot in armed_slots or slot not in expected_by_slot:
                    raise AssertionError(
                        f"frame {frame}: run arms invalid/duplicate slot {slot}")
                if source_name not in sources or not sources[source_name]:
                    raise AssertionError(
                        f"frame {frame}: {source_name} is empty before slot {slot}")
                if source_name == "Dic":
                    index = dic_index + (slot - run_slot)
                    if index >= len(sources["Dic"]):
                        raise AssertionError(
                            f"frame {frame}: Dic index {index} is out of range")
                    actual = sources["Dic"][index]
                else:
                    actual = sources[source_name].popleft()
                consumed[source_name] += 1
                if slot in expected_by_slot and actual != expected_by_slot[slot]:
                    raise AssertionError(
                        f"frame {frame}: {source_name} pattern differs at slot {slot}")
                vram[slot] = actual
                run_patterns.append(actual)
                armed_slots.add(slot)
                total_cold += 1
            frame_transfers.append(
                (run_slot, source_id, dic_index, tuple(run_patterns)))

        try:
            output_v2, external_v2 = encode_loads_v2(
                frame_transfers,
                parity=frame & 1,
                base=base,
                word_ptrs=word_ptrs,
                word_starts=word_starts,
                word_ends=word_ends,
            )
        except AssertionError as exc:
            raise AssertionError(f"frame {frame}: {exc}") from exc
        decoded_v2 = decode_loads_v2(
            output_v2,
            external_v2,
            base=base,
        )
        if decoded_v2 != tuple(frame_transfers):
            raise AssertionError(
                f"frame {frame}: O_LOADS v2 differs from descriptor replay")
        output_bytes = len(output_v2) - OUTPUT_HEADER_BYTES
        parity = frame & 1
        loads_peaks[parity] = max(loads_peaks[parity], output_bytes)
        declared_peak = (wr0_load_bytes, wr1_load_bytes)[parity]
        if output_bytes > declared_peak:
            raise AssertionError(
                f"frame {frame}: O_LOADS v2 uses {output_bytes} bytes, "
                f"declared parity peak is {declared_peak}")
        for run_slot, _source_id, _dic_index, patterns in decoded_v2:
            for offset, pattern in enumerate(patterns):
                vram_v2[run_slot + offset] = pattern
        if vram_v2 != vram:
            raise AssertionError(
                f"frame {frame}: descriptor and O_LOADS v2 VRAM states differ")

        for item, entry in zip(ordered, control.entries, strict=True):
            expected = packed_pattern(bytes(item[2]))
            palette = int(item[1])
            if ((entry & ENTRY_DISPLAY_MASK) >> 13) & 3 != palette:
                raise AssertionError(f"frame {frame}: palette entry differs from decisions")
            slot = (entry & 0x07FF) - base
            if not 0 <= slot < pool:
                raise AssertionError(f"frame {frame}: VRAM slot {slot} is outside the pool")
            if vram.get(slot) != expected:
                raise AssertionError(
                    f"frame {frame}: resident/reused pattern differs at slot {slot}")
            total_updates += 1

    leftovers = {
        name: len(queue) for name, queue in sources.items()
        if name != "Dic" and queue
    }
    if leftovers:
        raise AssertionError(f"unconsumed pattern supplies: {leftovers}")
    declared_peaks = (wr0_load_bytes, wr1_load_bytes)
    if tuple(loads_peaks) != declared_peaks:
        raise AssertionError(
            f"O_LOADS v2 peaks {tuple(loads_peaks)} differ from "
            f"PSUP {declared_peaks}")
    print(
        "pattern supply replay: OK "
        f"({frames} frames, {total_updates} updates, {total_cold} cold; "
        f"F0={consumed['F0']} Prg={consumed['Prg']} Wr0={consumed['Wr0']} "
        f"Wr1={consumed['Wr1']} Dic hits={consumed['Dic']} "
        f"Sidecar={len(sidecar_vram)})")
    print("VRAM resident/reuse equivalence: OK (every updated cell, every frame)")
    print(
        "O_LOADS v2 equivalence: OK "
        f"(descriptor replay == in-place records; peaks "
        f"Wr0={wr0_load_bytes} B, Wr1={wr1_load_bytes} B)")


if __name__ == "__main__":
    main()
