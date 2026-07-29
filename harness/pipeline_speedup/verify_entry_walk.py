#!/usr/bin/env python3
"""Prove that the Sub CPU can consume update entries without re-walking bitmap.

The Main CPU still needs the bitmap to map entries to cells.  The Sub CPU only
needs cold entries in stream order to pop patterns and build DMA runs.  This
checker walks every real control block in the packed TTRC files both ways and
verifies that the entry stream, cold-slot order and run grouping are identical.

For current v22 it prefers the on-disc HEADER.DAT + BODY.DAT pair, verifies
that each frame's control block and cold patterns are ready before that frame
can run, and also accepts the off-disc MOVIE.DAT compatibility concatenation.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import av_config  # noqa: E402
import player_constants  # noqa: E402


SECTOR = 2048
ROUTING_TOTAL_MAX = 5
FEATURE_FIXED_N = 0x0002
FEATURE_PATTERN_SUPPLY = 0x0008
ADPCM_TABLE_SECTORS = 5
SOURCE_PRG = 0
SOURCE_WR = 1
SOURCE_DIC = 2
DIC_RUN_BLOCK = 256
DIC_CAPACITY = 512
VERSION = 22
CONTROL_SUFFIX_HEADER_BYTES = 2


def frame_sectors(
    routes: list[tuple[int, int]], version: int, fps: int, vsync_n: int,
    features: int,
) -> list[int]:
    """Return the v4+ bounded-accumulator sector schedule for frames 1+."""
    if version >= 8 and features & FEATURE_FIXED_N:
        rate_numerator, rate_modulus = av_config.fixed_cd_sector_rate(vsync_n)
    else:
        rate_numerator, rate_modulus = 75, fps
    acc = 0
    lead = 0
    out = [0]
    for n_pay, n_ctrl, _n_word in routes[1:]:
        acc += rate_numerator
        ratedelta, acc = divmod(acc, rate_modulus)
        actual = n_pay + n_ctrl
        fsec = max(actual, ratedelta - lead)
        lead += fsec - ratedelta
        out.append(fsec)
    return out


def decode_routes(
    routing: bytes, nframes: int, version: int
) -> list[tuple[int, int]]:
    """Decode routing without importing the production packer."""
    compact = version >= 7
    entry_bytes = 1 if compact else 2
    required = nframes * entry_bytes
    if len(routing) < required:
        raise AssertionError("truncated routing table")
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


def runs(entries: list[int]) -> list[tuple[int, int, int]]:
    """Model consecutive cold-slot runs, including v10 source boundaries."""
    out: list[tuple[int, int, int]] = []
    for entry in entries:
        if not entry & 0x8000:
            continue
        slot = (entry & 0x07FF) - 1
        source = (entry & 0x1800) >> 11
        if out and out[-1][0] + out[-1][1] == slot and out[-1][2] == source:
            start, count, _source = out[-1]
            out[-1] = start, count + 1, source
        else:
            out.append((slot, 1, source))
    return out


def pattern_supply_layout(
    header: bytes, version: int, features: int,
) -> tuple[int, int]:
    """Return the validated boot-preload sector total and Dic pattern count."""
    if not features & FEATURE_PATTERN_SUPPLY:
        return 0, 0
    values = player_constants.PATTERN_SUPPLY_STRUCT.unpack_from(
        header, player_constants.PATTERN_SUPPLY_OFFSET)
    magic, supply_version, reserved = values[:3]
    if (magic != player_constants.PATTERN_SUPPLY_MAGIC
            or supply_version not in (
                1, 2, player_constants.PATTERN_SUPPLY_VERSION)
            or reserved):
        raise AssertionError(f"invalid pattern-supply extension: {values!r}")
    dic_patterns = values[5]
    if dic_patterns > DIC_CAPACITY:
        raise AssertionError(
            f"Dic preload {dic_patterns} exceeds {DIC_CAPACITY} patterns")
    return sum(values[6:9]), dic_patterns


def verify_block(
    block: bytes, seq: int, cells: int, pool: int, audio_bytes: int,
    dic_patterns: int,
) -> tuple[int, int, int]:
    if len(block) < 8:
        raise AssertionError(f"frame {seq}: short control block")
    total_len, frame_seq, raw_count = struct.unpack_from(">HHH", block)
    n_upd = raw_count & 0x7FFF
    use_list = bool(raw_count & 0x8000)
    if total_len != len(block):
        raise AssertionError(f"frame {seq}: total_len {total_len} != {len(block)}")
    if frame_seq != seq:
        raise AssertionError(f"frame {seq}: frame_seq is {frame_seq}")
    if n_upd > cells:
        raise AssertionError(f"frame {seq}: n_upd {n_upd} exceeds {cells} cells")

    bitmap_off = 6
    if use_list:
        list_end = bitmap_off + n_upd * 4
        if list_end > len(block):
            raise AssertionError(f"frame {seq}: shadow list exceeds control block")
        previous = -1
        for index in range(n_upd):
            offset = struct.unpack_from(">H", block, bitmap_off + index * 4)[0]
            if offset & 1 or offset >= cells * 2 or offset <= previous:
                raise AssertionError(f"frame {seq}: invalid shadow-list offset {offset}")
            previous = offset
        # v11 list frames bypass the legacy Sub entry walk and consume the
        # authoritative run suffix instead. Count that suffix so the delivery
        # proof below retains its exact Prg demand.
        suffix = list_end + audio_bytes
        suffix = (suffix + 1) & ~1
        if suffix + CONTROL_SUFFIX_HEADER_BYTES > len(block):
            raise AssertionError(f"frame {seq}: missing run suffix")
        n_runs = struct.unpack_from(">H", block, suffix)[0]
        suffix += CONTROL_SUFFIX_HEADER_BYTES
        if suffix + n_runs * 4 != len(block):
            raise AssertionError(f"frame {seq}: invalid run suffix length")
        cold = 0
        prg_cold = 0
        for index in range(n_runs):
            slot_word, encoded = struct.unpack_from(
                ">HH", block, suffix + index * 4)
            slot = slot_word & 0x07FF
            count = encoded & 0x07FF
            raw_source = encoded >> 14
            local_dic = ((slot_word >> 11) << 3) | ((encoded >> 11) & 7)
            invalid = not count or slot + count > pool
            if raw_source >= SOURCE_DIC:
                dic_index = (
                    local_dic
                    + (raw_source - SOURCE_DIC) * DIC_RUN_BLOCK
                )
                invalid = invalid or (
                    local_dic + count > DIC_RUN_BLOCK
                    or dic_index + count > dic_patterns
                )
            else:
                invalid = invalid or bool(local_dic)
            if invalid:
                raise AssertionError(f"frame {seq}: invalid run descriptor")
            cold += count
            if raw_source == SOURCE_PRG:
                prg_cold += count
        return n_upd, cold, prg_cold
    bitmap_len = (cells + 7) // 8
    bitmap_end = bitmap_off + bitmap_len
    entries_off = (bitmap_end + 1) & ~1
    entries_end = entries_off + 2 * n_upd
    if entries_end > len(block):
        raise AssertionError(f"frame {seq}: entries exceed control block")
    bitmap = block[bitmap_off:bitmap_end]
    if any(block[bitmap_end:entries_off]):
        raise AssertionError(f"frame {seq}: bitmap alignment pad is nonzero")
    direct = list(struct.unpack_from(f">{n_upd}H", block, entries_off)) if n_upd else []

    old: list[int] = []
    entry_i = 0
    for cell in range(cells):
        if bitmap[cell >> 3] & (1 << (cell & 7)):
            if entry_i >= len(direct):
                raise AssertionError(f"frame {seq}: bitmap has more updates than n_upd")
            old.append(direct[entry_i])
            entry_i += 1
    if entry_i != n_upd:
        raise AssertionError(
            f"frame {seq}: bitmap consumed {entry_i} entries, header says {n_upd}"
        )
    for cell in range(cells, bitmap_len * 8):
        if bitmap[cell >> 3] & (1 << (cell & 7)):
            raise AssertionError(f"frame {seq}: padding bitmap bit {cell} is set")

    if old != direct or runs(old) != runs(direct):
        raise AssertionError(f"frame {seq}: direct entry walk differs from bitmap walk")
    for entry in direct:
        if entry & 0x8000:
            slot_plus_one = entry & 0x07FF
            source = (entry & 0x1800) >> 11
            if not 1 <= slot_plus_one <= pool:
                raise AssertionError(
                    f"frame {seq}: cold slot+1 {slot_plus_one} outside pool {pool}"
                )
            if source > SOURCE_DIC:
                raise AssertionError(
                    f"frame {seq}: name-table entry uses invalid source {source}")
    cold = sum(bool(entry & 0x8000) for entry in direct)
    prg_cold = sum(
        bool(entry & 0x8000) and not entry & 0x1800 for entry in direct)
    return n_upd, cold, prg_cold


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify direct entry walking and the packed TTRC delivery order."
    )
    parser.add_argument(
        "stream",
        nargs="?",
        help="HEADER.DAT or combined MOVIE.DAT (default: on-disc pair if present)",
    )
    parser.add_argument(
        "body",
        nargs="?",
        help="BODY.DAT when the first argument is a standalone v6+ HEADER.DAT",
    )
    args = parser.parse_args()

    if args.stream:
        stream_path = Path(args.stream)
    else:
        header_path = Path("out/movieplay/HEADER.DAT")
        body_path = Path("out/movieplay/BODY.DAT")
        stream_path = (
            header_path
            if header_path.exists() and body_path.exists()
            else Path("out/movieplay/MOVIE.DAT")
        )
    data = stream_path.read_bytes()

    magic, version, nfr, _cols, _rows, cells, pool = struct.unpack_from(
        ">4sHHHHHH", data, 0
    )
    if magic != b"TTRC" or version != VERSION:
        raise SystemExit(
            f"expected TTRC v{VERSION}, got {magic!r} v{version}")
    prebuf_pat = struct.unpack_from(">L", data, 22)[0]
    routing_sec = struct.unpack_from(">L", data, 26)[0]
    prebuf_sec = struct.unpack_from(">L", data, 30)[0]
    f0_ctrl_sec, f0_pat_sec, paltab_sec = struct.unpack_from(">LLL", data, 40)
    vsync_n = struct.unpack_from(">H", data, 52)[0]
    fps = struct.unpack_from(">H", data, 56)[0] or 15
    audio_preload_sec = struct.unpack_from(">H", data, 60)[0]
    features = struct.unpack_from(">H", data, 62)[0]
    decoded_audio_bytes = struct.unpack_from(">H", data, 54)[0]
    audio_bytes = 4 + decoded_audio_bytes // 2
    table_sec = ADPCM_TABLE_SECTORS
    supply_sec, dic_patterns = pattern_supply_layout(data, version, features)

    routing_off = (
        1 + paltab_sec + table_sec + supply_sec
    ) * SECTOR
    routing_raw = data[routing_off : routing_off + routing_sec * SECTOR]
    routes = decode_routes(routing_raw, nfr, version)
    if routes[0] != (0, 0, 0):
        raise AssertionError(f"frame 0 BODY-arm route must be zero, got {routes[0]}")
    fsecs = frame_sectors(routes, version, fps, vsync_n, features)

    frames_off = (routing_off // SECTOR + routing_sec + prebuf_sec) * SECTOR
    if len(data) < frames_off:
        raise AssertionError(
            f"truncated boot prefix: {len(data)} bytes, expected {frames_off}"
        )
    if version >= 6:
        if args.body:
            if len(data) != frames_off:
                raise AssertionError(
                    "an explicit BODY.DAT requires a standalone HEADER.DAT"
                )
            body_path = Path(args.body)
            frames = body_path.read_bytes()
        elif len(data) == frames_off:
            body_path = stream_path.with_name("BODY.DAT")
            if not body_path.exists():
                raise AssertionError(f"missing v6+ body file: {body_path}")
            frames = body_path.read_bytes()
        else:
            body_path = None
            frames = data[frames_off:]
    else:
        if args.body:
            raise AssertionError("separate HEADER.DAT/BODY.DAT requires TTRC v6+")
        body_path = None
        frames = data[frames_off:]

    f0_off = audio_preload_sec * SECTOR
    f0_len = struct.unpack_from(">H", frames, f0_off)[0]
    controls = [frames[f0_off : f0_off + f0_len]]
    cursor = (
        audio_preload_sec + f0_ctrl_sec + f0_pat_sec
    ) * SECTOR
    control_stream = bytearray()
    for i in range(1, nfr):
        n_pay, n_ctrl, _n_word = routes[i]
        frame_len = fsecs[i] * SECTOR
        frame = frames[cursor : cursor + frame_len]
        if len(frame) != frame_len:
            raise AssertionError(f"frame {i}: truncated sector slot")
        if version >= 6:
            control_stream += frame[: n_ctrl * SECTOR]
        else:
            control_stream += frame[n_pay * SECTOR : (n_pay + n_ctrl) * SECTOR]
        cursor += frame_len
    if cursor != len(frames):
        raise AssertionError(
            f"body length {len(frames)} does not match routed frame slots {cursor}"
        )

    control_pos = 0
    for seq in range(1, nfr):
        if control_pos + 2 > len(control_stream):
            raise AssertionError(f"frame {seq}: missing control length")
        total_len = struct.unpack_from(">H", control_stream, control_pos)[0]
        if total_len == 0 or total_len & 1:
            raise AssertionError(f"frame {seq}: invalid total_len {total_len}")
        controls.append(bytes(control_stream[control_pos : control_pos + total_len]))
        control_pos += total_len

    updates = 0
    cold = 0
    prg_by_frame = []
    for seq, block in enumerate(controls):
        frame_updates, frame_cold, frame_prg = verify_block(
            block, seq, cells, pool, audio_bytes, dic_patterns)
        updates += frame_updates
        cold += frame_cold
        prg_by_frame.append(frame_prg)

    if version >= 6:
        control_delivered = 0
        control_needed = 0
        payload_delivered = prebuf_pat
        payload_needed = 0
        for seq in range(1, nfr):
            n_pay, n_ctrl, n_word = routes[seq]
            control_delivered += n_ctrl * SECTOR
            control_needed += len(controls[seq])
            if control_delivered < control_needed:
                raise AssertionError(
                    f"frame {seq}: control is not ready "
                    f"({control_delivered} delivered, {control_needed} needed)"
                )

            # v10 boot-preloaded Wr/Main patterns are already armed. Only Prg
            # patterns consume the timed prebuffer/BODY payload delivery.
            payload_needed += prg_by_frame[seq]
            if payload_delivered < payload_needed:
                raise AssertionError(
                    f"frame {seq}: cold payload is not armed before control "
                    f"({payload_delivered} patterns delivered, {payload_needed} needed)"
                )
            # WordBuf refill sectors ride the payload prefix and do not
            # deliver Prg patterns.
            payload_delivered += (n_pay - n_word) * (SECTOR // 32)

    print(
        f"entry-walk equivalence: OK (v{version}, {nfr} frames, {updates} entries, "
        f"{cold} cold, {cells} cells)"
    )


if __name__ == "__main__":
    main()
