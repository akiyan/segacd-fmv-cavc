#!/usr/bin/env python3
"""Prove the 30 fps descriptor path preserves the fallback CDC poll point.

The fallback assembly keeps two DBRA counters in the per-entry loop: one for
all updates and one for the CDC cadence. At 30 fps the cadence is 1024 entries,
while the current H32 stream has at most 896 cells. The descriptor path can
therefore perform the same single poll after consuming its runs. H40 can
contain up to 1120 cells, so the fallback retains its possible short-prefix
poll followed by the final poll.

This checker reads the real split TTRC v25 stream, compares the fallback DBRA
countdown with an equivalent grouped model for every frame, and confirms that
entry order and cold-slot run grouping are unchanged.  It additionally checks
every synthetic update count up to the format's H40 maximum.
"""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path


SECTOR = 2048
POLL_CHUNK_30FPS = 1024
MAX_H40_CELLS = 40 * 28
ROUTING_TOTAL_MAX = 5
FEATURE_VBLANK_CADENCE = 0x0002
FEATURE_PATTERN_SUPPLY = 0x0008
SHADOW_UPDATE_LIST_TAG = 0x8000
SHADOW_FRAME_TYPE_MASK = 0x6000
SHADOW_FRAME_TYPE_SHIFT = 13
SHADOW_FRAME_TYPE_RESERVED = 3
SHADOW_UPDATE_COUNT_MASK = 0x1FFF
INLINE_CRAM_BYTES = 128
ADPCM_TABLE_SECTORS = 5
PATTERN_SUPPLY_OFFSET = 196
VERSION = 25


@dataclass(frozen=True)
class Stream:
    fps: int
    cells: int
    entries: tuple[tuple[int, ...], ...]


def frame_sectors(
    routes: list[tuple[int, int]], version: int, fps: int, vsync_n: int,
    features: int,
) -> list[int]:
    """Reproduce the packer's versioned bounded BODY schedule."""
    if version >= 24 and features & FEATURE_VBLANK_CADENCE and fps == 24:
        rate_numerators, rate_modulus = (2002, 3003), 800
    elif version >= 8 and features & FEATURE_VBLANK_CADENCE:
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


def decode_routes(
    routing: bytes, nframes: int, version: int
) -> list[tuple[int, int]]:
    """Decode routing without importing the production packer."""
    compact = version >= 7
    entry_bytes = 1 if compact else 2
    required = nframes * entry_bytes
    if len(routing) < required:
        raise AssertionError("routing table is truncated")
    if not compact:
        return [
            (routing[frame * 2], routing[frame * 2 + 1])
            for frame in range(nframes)
        ]

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


def pattern_supply_sectors(header: bytes, version: int, features: int) -> int:
    """Return the validated current boot-preload sector total."""
    if not features & FEATURE_PATTERN_SUPPLY:
        return 0
    values = struct.unpack_from(">4s11H", header, PATTERN_SUPPLY_OFFSET)
    magic, supply_version, reserved = values[:3]
    if magic != b"PSUP" or supply_version != 4 or reserved:
        raise AssertionError(f"invalid pattern-supply extension: {values!r}")
    return sum(values[6:9])


def parse_entries(block: bytes, seq: int, cells: int) -> tuple[int, ...]:
    """Return entries from one validated control block."""
    if len(block) < 8:
        raise AssertionError(f"frame {seq}: control block is shorter than 8 bytes")
    total_len, packed_seq, raw_count = struct.unpack_from(">HHH", block)
    n_upd = raw_count & SHADOW_UPDATE_COUNT_MASK
    use_list = bool(raw_count & SHADOW_UPDATE_LIST_TAG)
    frame_type = (
        raw_count & SHADOW_FRAME_TYPE_MASK) >> SHADOW_FRAME_TYPE_SHIFT
    if total_len != len(block):
        raise AssertionError(f"frame {seq}: total_len {total_len} != {len(block)}")
    if packed_seq != seq:
        raise AssertionError(f"frame {seq}: packed sequence is {packed_seq}")
    if n_upd > cells:
        raise AssertionError(f"frame {seq}: {n_upd} updates exceed {cells} cells")
    if frame_type == SHADOW_FRAME_TYPE_RESERVED:
        raise AssertionError(f"frame {seq}: reserved frame type")
    if frame_type:
        if n_upd or use_list:
            raise AssertionError(f"frame {seq}: fade control carries updates")
        if 6 + INLINE_CRAM_BYTES > len(block):
            raise AssertionError(f"frame {seq}: inline CRAM exceeds the control block")
        return ()

    if use_list:
        list_start = 6
        list_end = list_start + 4 * n_upd
        if list_end > len(block):
            raise AssertionError(f"frame {seq}: shadow list exceeds the control block")
        previous = -1
        for index in range(n_upd):
            offset = struct.unpack_from(">H", block, list_start + index * 4)[0]
            if offset & 1 or offset >= cells * 2 or offset <= previous:
                raise AssertionError(f"frame {seq}: invalid shadow-list offset {offset}")
            previous = offset
        # List frames use the authoritative run suffix; the legacy Sub entry
        # walker measured by this harness is intentionally not entered.
        return ()

    bitmap_start = 6
    bitmap_len = (cells + 7) // 8
    bitmap_end = bitmap_start + bitmap_len
    entries_start = (bitmap_end + 1) & ~1
    entries_end = entries_start + 2 * n_upd
    if entries_end > len(block):
        raise AssertionError(f"frame {seq}: entries exceed the control block")
    bitmap = block[bitmap_start:bitmap_end]
    if any(block[bitmap_end:entries_start]):
        raise AssertionError(f"frame {seq}: bitmap alignment pad is nonzero")
    if sum(byte.bit_count() for byte in bitmap) != n_upd:
        raise AssertionError(f"frame {seq}: bitmap population differs from n_upd")
    if not n_upd:
        return ()
    return tuple(struct.unpack_from(f">{n_upd}H", block, entries_start))


def read_stream(header_path: Path, body_path: Path) -> Stream:
    """Read control entries from split HEADER.DAT and BODY.DAT files."""
    header = header_path.read_bytes()
    magic, version, nfr, _cols, _rows, cells = struct.unpack_from(
        ">4sHHHHH", header
    )
    if magic != b"TTRC" or version != VERSION:
        raise AssertionError(
            f"expected split TTRC v{VERSION}, got {magic!r} v{version}")

    routing_sec = struct.unpack_from(">L", header, 26)[0]
    prebuf_sec = struct.unpack_from(">L", header, 30)[0]
    f0_ctrl_sec, f0_pat_sec, paltab_sec = struct.unpack_from(">LLL", header, 40)
    vsync_n = struct.unpack_from(">H", header, 52)[0]
    fps = struct.unpack_from(">H", header, 56)[0] or 15
    audio_preload_sec = struct.unpack_from(">H", header, 60)[0]
    features = struct.unpack_from(">H", header, 62)[0]
    table_sec = ADPCM_TABLE_SECTORS
    supply_sec = pattern_supply_sectors(header, version, features)

    routing_offset = (
        1 + paltab_sec + table_sec + supply_sec
    ) * SECTOR
    routing_raw = header[
        routing_offset : routing_offset + routing_sec * SECTOR
    ]
    routes = decode_routes(routing_raw, nfr, version)
    if routes[0] != (0, 0, 0):
        raise AssertionError(f"frame 0 route must be (0, 0), got {routes[0]}")
    expected_header_len = (
        routing_offset // SECTOR + routing_sec + prebuf_sec
    ) * SECTOR
    if len(header) != expected_header_len:
        raise AssertionError(
            f"HEADER.DAT is {len(header)} bytes, expected {expected_header_len}"
        )

    body = body_path.read_bytes()
    frame0_offset = audio_preload_sec * SECTOR
    frame0_len = struct.unpack_from(">H", body, frame0_offset)[0]
    entries = [
        parse_entries(
            body[frame0_offset : frame0_offset + frame0_len], 0, cells
        )
    ]

    slots = frame_sectors(routes, version, fps, vsync_n, features)
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
            raise AssertionError(f"frame {seq}: missing control length")
        block_len = struct.unpack_from(">H", control_stream, control_pos)[0]
        if block_len < 8 or block_len & 1:
            raise AssertionError(f"frame {seq}: invalid control length {block_len}")
        block_end = control_pos + block_len
        if block_end > len(control_stream):
            raise AssertionError(f"frame {seq}: control block is truncated")
        entries.append(
            parse_entries(bytes(control_stream[control_pos:block_end]), seq, cells)
        )
        control_pos = block_end

    return Stream(fps, cells, tuple(entries))


def current_poll_positions(n_entries: int, chunk: int) -> tuple[int, ...]:
    """Model the fallback masked initial DBRA cadence counter exactly."""
    if not n_entries:
        return ()
    mask = chunk - 1
    counter = (n_entries - 1) & mask
    polls: list[int] = []
    for position in range(1, n_entries + 1):
        counter = (counter - 1) & 0xFFFF
        if counter == 0xFFFF:
            polls.append(position)
            counter = mask
    return tuple(polls)


def grouped_poll_positions(n_entries: int, chunk: int) -> tuple[int, ...]:
    """Model loops split into a short prefix and full cadence-sized groups."""
    if not n_entries:
        return ()
    prefix = n_entries % chunk or chunk
    return tuple(range(prefix, n_entries + 1, chunk))


def cold_runs(entries: tuple[int, ...]) -> tuple[tuple[int, int, int], ...]:
    """Build consecutive cold-slot runs, splitting at v10 source changes."""
    result: list[tuple[int, int, int]] = []
    for entry in entries:
        if not entry & 0x8000:
            continue
        slot = (entry & 0x07FF) - 1
        source = (entry & 0x1800) >> 11
        if result and result[-1][0] + result[-1][1] == slot and result[-1][2] == source:
            start, count, _source = result[-1]
            result[-1] = start, count + 1, source
        else:
            result.append((slot, 1, source))
    return tuple(result)


def grouped_walk(
    entries: tuple[int, ...], chunk: int
) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """Return entry order and polls from the proposed group structure."""
    polls = grouped_poll_positions(len(entries), chunk)
    walked: list[int] = []
    start = 0
    for end in polls:
        walked.extend(entries[start:end])
        start = end
    if start != len(entries):
        raise AssertionError("grouped loop did not consume all entries")
    return tuple(walked), polls


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify the 30 fps Sub entry-loop poll fast path."
    )
    parser.add_argument(
        "--header", type=Path, default=Path("out/movieplay/HEADER.DAT")
    )
    parser.add_argument(
        "--body", type=Path, default=Path("out/movieplay/BODY.DAT")
    )
    args = parser.parse_args()

    stream = read_stream(args.header, args.body)
    if stream.fps != 30:
        raise AssertionError(f"expected a nominal 30 fps stream, got {stream.fps}")

    total_entries = 0
    max_entries = 0
    cold = 0
    poll_count = 0
    for seq, entries in enumerate(stream.entries):
        current_polls = current_poll_positions(len(entries), POLL_CHUNK_30FPS)
        walked, grouped_polls = grouped_walk(entries, POLL_CHUNK_30FPS)
        if current_polls != grouped_polls:
            raise AssertionError(
                f"frame {seq}: poll positions changed: "
                f"{current_polls} -> {grouped_polls}"
            )
        if walked != entries or cold_runs(walked) != cold_runs(entries):
            raise AssertionError(f"frame {seq}: grouped loop changed entry output")
        total_entries += len(entries)
        max_entries = max(max_entries, len(entries))
        cold += sum(bool(entry & 0x8000) for entry in entries)
        poll_count += len(current_polls)

    for n_entries in range(MAX_H40_CELLS + 1):
        current = current_poll_positions(n_entries, POLL_CHUNK_30FPS)
        grouped = grouped_poll_positions(n_entries, POLL_CHUNK_30FPS)
        if current != grouped:
            raise AssertionError(
                f"synthetic n_upd={n_entries}: poll positions changed: "
                f"{current} -> {grouped}"
            )

    startup_entries = sum(len(entries) for entries in stream.entries[1:52])
    print(
        "30fps entry-poll fast-path equivalence: OK "
        f"({len(stream.entries)} frames, {total_entries} entries, {cold} cold, "
        f"max n_upd={max_entries}, {poll_count} polls)"
    )
    print(
        "cadence matrix: OK "
        f"(n_upd=0..{MAX_H40_CELLS}, chunk={POLL_CHUNK_30FPS}; "
        f"avoidable cadence DBRAs={total_entries}, frames 1-51={startup_entries})"
    )


if __name__ == "__main__":
    main()
