#!/usr/bin/env python3
"""Read packed controls for cycle and shadow-list diagnostics."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path


SECTOR = 2048
ROUTING_TOTAL_MAX = 5
FEATURE_VBLANK_CADENCE = 0x0002
FEATURE_PATTERN_SUPPLY = 0x0008
FEATURE_SHADOW_UPDATE_LISTS = 0x0010
ADPCM_TABLE_SECTORS = 5
PATTERN_SUPPLY_OFFSET = 196
NAME_ENTRY_MASK = 0x67FF
SHADOW_UPDATE_LIST_TAG = 0x8000
SHADOW_FRAME_TYPE_MASK = 0x6000
SHADOW_FRAME_TYPE_SHIFT = 13
SHADOW_FRAME_TYPE_RESERVED = 3
SHADOW_UPDATE_COUNT_MASK = 0x1FFF
INLINE_CRAM_BYTES = 128


@dataclass(frozen=True)
class ControlBlock:
    seq: int
    bitmap: bytes
    entries: tuple[int, ...]
    use_list: bool
    total_len: int


@dataclass(frozen=True)
class Stream:
    cols: int
    rows: int
    cells: int
    controls: tuple[ControlBlock, ...]


def frame_sectors(
    routes: list[tuple[int, int]], fps: int, vsync_n: int,
    features: int,
) -> list[int]:
    """Reproduce the packer's versioned bounded accumulator for BODY slots."""
    if features & FEATURE_VBLANK_CADENCE and fps == 24:
        rate_numerators, rate_modulus = (2002, 3003), 800
    elif features & FEATURE_VBLANK_CADENCE:
        rate_numerators, rate_modulus = (1001 * vsync_n,), 800
    else:
        rate_numerators, rate_modulus = (75,), fps
    accumulator = 0
    lead = 0
    out = [0]
    for index, (n_pay, n_ctrl, _n_word) in enumerate(routes[1:]):
        accumulator += rate_numerators[index % len(rate_numerators)]
        rated, accumulator = divmod(accumulator, rate_modulus)
        actual = n_pay + n_ctrl
        sectors = max(actual, rated - lead)
        lead += sectors - rated
        out.append(sectors)
    return out


def decode_routes(routing: bytes, nframes: int) -> list[tuple[int, int]]:
    """Decode routing without depending on the production packer."""
    required = nframes
    if len(routing) < required:
        raise AssertionError("routing table is truncated")
    expected_bytes = ((nframes + SECTOR - 1) // SECTOR) * SECTOR
    if len(routing) != expected_bytes:
        raise AssertionError(
            f"v7+ routing region is {len(routing)} bytes, expected {expected_bytes}"
        )
    if not nframes or routing[0] != 0:
        raise AssertionError("v7+ frame 0 routing entry must be zero")
    if any(routing[nframes:]):
        raise AssertionError("v7+ routing sector padding must be zero")

    routes = []
    for frame, packed in enumerate(routing[:nframes]):
        # bits 6-7 carry the WordBuf payload prefix; ctrl bit 2 is the
        # 4-sector escape (base 3 in the word field).
        n_word = (packed >> 6) & 3
        ctrl_field = packed & 0x07
        n_ctrl = ctrl_field
        if ctrl_field & 4:
            if n_word != 3:
                raise AssertionError(
                    f"frame {frame}: WordBuf-4 escape lacks base 3 in 0x{packed:02X}"
                )
            n_ctrl = ctrl_field & 3
            n_word = 4
        total = (packed >> 3) & 0x07
        if total > ROUTING_TOTAL_MAX:
            raise AssertionError(
                f"frame {frame}: routing total {total} exceeds "
                f"{ROUTING_TOTAL_MAX} sectors"
            )
        if n_ctrl > total or n_word > total - n_ctrl:
            raise AssertionError(
                f"frame {frame}: routing control {n_ctrl} exceeds total {total}"
            )
        routes.append((total - n_ctrl, n_ctrl, n_word))
    return routes


def pattern_supply_sectors(header: bytes, features: int) -> int:
    """Return the validated current boot-preload sector total."""
    if not features & FEATURE_PATTERN_SUPPLY:
        return 0
    values = struct.unpack_from(">4s11H", header, PATTERN_SUPPLY_OFFSET)
    magic, supply_version, reserved = values[:3]
    if magic != b"PSUP" or supply_version != 4 or reserved:
        raise AssertionError(f"invalid pattern-supply extension: {values!r}")
    return sum(values[6:9])


def parse_control(raw: bytes, seq: int, cells: int) -> ControlBlock:
    if len(raw) < 8:
        raise AssertionError(f"frame {seq}: control block is shorter than 8 bytes")
    total_len, packed_seq, raw_count = struct.unpack_from(">HHH", raw)
    n_upd = raw_count & SHADOW_UPDATE_COUNT_MASK
    use_list = bool(raw_count & SHADOW_UPDATE_LIST_TAG)
    frame_type = (
        raw_count & SHADOW_FRAME_TYPE_MASK) >> SHADOW_FRAME_TYPE_SHIFT
    if total_len != len(raw):
        raise AssertionError(f"frame {seq}: total_len {total_len} != {len(raw)}")
    if packed_seq != (seq & 0xFFFF):
        raise AssertionError(f"frame {seq}: packed sequence is {packed_seq}")
    if n_upd > cells:
        raise AssertionError(f"frame {seq}: {n_upd} updates exceed {cells} cells")

    bitmap_start = 6
    bitmap_len = (cells + 7) // 8
    if frame_type == SHADOW_FRAME_TYPE_RESERVED:
        raise AssertionError(f"frame {seq}: reserved frame type")
    if frame_type:
        if n_upd or use_list:
            raise AssertionError(f"frame {seq}: fade control carries updates")
        if bitmap_start + INLINE_CRAM_BYTES > len(raw):
            raise AssertionError(f"frame {seq}: inline CRAM exceeds the control block")
        return ControlBlock(
            seq, bytes(bitmap_len), (), False, total_len)
    bitmap_end = bitmap_start + bitmap_len
    entries_start = (bitmap_end + 1) & ~1
    entries_end = entries_start + n_upd * 2
    if use_list:
        entries_start = bitmap_start
        entries_end = entries_start + n_upd * 4
    if entries_end > len(raw):
        raise AssertionError(f"frame {seq}: entries extend beyond the control block")
    if use_list:
        bitmap_mut = bytearray(bitmap_len)
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
            struct.unpack_from(f">{n_upd}H", raw, entries_start) if n_upd else ()
        )
    if sum(byte.bit_count() for byte in bitmap) != n_upd:
        raise AssertionError(f"frame {seq}: bitmap population differs from n_upd")
    for cell in range(cells, bitmap_len * 8):
        if bitmap[cell >> 3] & (1 << (cell & 7)):
            raise AssertionError(f"frame {seq}: padding bitmap bit {cell} is set")
    return ControlBlock(seq, bitmap, tuple(entries), use_list, total_len)


def read_stream(header_path: Path, body_path: Path) -> Stream:
    header = header_path.read_bytes()
    magic, nfr, cols, rows, cells, _pool = struct.unpack_from(
        ">4sHHHHH", header
    )
    nfr |= header[37] << 16
    if magic != b"CAVC":
        raise AssertionError(f"expected split CAVC, got {magic!r}")
    if cols * rows != cells:
        raise AssertionError(f"grid {cols}x{rows} does not equal {cells} cells")

    routing_sec = struct.unpack_from(">L", header, 24)[0]
    prebuf_sec = struct.unpack_from(">L", header, 28)[0]
    f0_ctrl_sec, f0_pat_sec, paltab_sec = struct.unpack_from(">LLL", header, 38)
    vsync_n = struct.unpack_from(">H", header, 50)[0]
    fps = struct.unpack_from(">H", header, 54)[0] or 15
    audio_preload_sec = struct.unpack_from(">H", header, 58)[0]
    features = struct.unpack_from(">H", header, 60)[0]
    if features & FEATURE_SHADOW_UPDATE_LISTS \
            and not features & FEATURE_PATTERN_SUPPLY:
        raise AssertionError("shadow update lists require pattern supply")
    table_sec = ADPCM_TABLE_SECTORS
    supply_sec = pattern_supply_sectors(header, features)

    routing_offset = (
        1 + paltab_sec + table_sec + supply_sec
    ) * SECTOR
    routing_raw = header[
        routing_offset : routing_offset + routing_sec * SECTOR
    ]
    routes = decode_routes(routing_raw, nfr)
    if routes[0] != (0, 0, 0):
        raise AssertionError(f"frame 0 route must be (0, 0), got {routes[0]}")
    expected_header_len = (routing_offset // SECTOR + routing_sec + prebuf_sec) * SECTOR
    if len(header) != expected_header_len:
        raise AssertionError(
            f"HEADER.DAT is {len(header)} bytes, expected {expected_header_len}"
        )

    body = body_path.read_bytes()
    frame0_offset = audio_preload_sec * SECTOR
    frame0_len = struct.unpack_from(">H", body, frame0_offset)[0]
    controls = [
        parse_control(
            body[frame0_offset : frame0_offset + frame0_len], 0, cells
        )
    ]
    slots = frame_sectors(routes, fps, vsync_n, features)
    body_pos = (
        audio_preload_sec + f0_ctrl_sec + f0_pat_sec
    ) * SECTOR
    control_stream = bytearray()
    for seq in range(1, nfr):
        slot_len = slots[seq] * SECTOR
        slot = body[body_pos : body_pos + slot_len]
        if len(slot) != slot_len:
            raise AssertionError(f"frame {seq}: BODY.DAT slot is truncated")
        n_ctrl = routes[seq][1]
        control_stream += slot[: n_ctrl * SECTOR]
        body_pos += slot_len
    if body_pos != len(body):
        raise AssertionError(
            f"BODY.DAT has {len(body) - body_pos} unrouted trailing bytes"
        )

    control_pos = 0
    for seq in range(1, nfr):
        if control_pos + 2 > len(control_stream):
            raise AssertionError(f"frame {seq}: missing control block length")
        block_len = struct.unpack_from(">H", control_stream, control_pos)[0]
        if block_len < 8 or block_len & 1:
            raise AssertionError(f"frame {seq}: invalid control length {block_len}")
        end = control_pos + block_len
        if end > len(control_stream):
            raise AssertionError(f"frame {seq}: control block is truncated")
        controls.append(parse_control(bytes(control_stream[control_pos:end]), seq, cells))
        control_pos = end

    return Stream(cols, rows, cells, tuple(controls))


def bitmap_cells(bitmap: bytes, cells: int) -> list[int]:
    return [
        cell
        for cell in range(cells)
        if bitmap[cell >> 3] & (1 << (cell & 7))
    ]
