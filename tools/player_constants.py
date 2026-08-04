#!/usr/bin/env python3
"""Generate assembler constants bound to one packed ``HEADER.DAT``.

Bytes 4 through 61 are the complete fixed player contract.  The four-byte
magic is identifying data only.  The packer stores the contract CRC-32 in the
otherwise reserved first sector at offset 192.  Both Main
and Sub objects include the generated file; the Sub compares the stored value
before accepting the disc, so a player cannot silently run with another
profile's HEADER.DAT.
"""

from __future__ import annotations

import argparse
import dataclasses
import struct
import zlib
from pathlib import Path

import cavc_routing
import ima_adpcm
import pattern_supply
import av_config


SECTOR = 2048
FIXED_HEADER_BYTES = 62
HEADER_SIGNATURE_OFFSET = 192
HEADER_STRUCT = struct.Struct(">4s8H4LBB3L6H")
PATTERN_SUPPLY_OFFSET = HEADER_SIGNATURE_OFFSET + 4
PATTERN_SUPPLY_MAGIC = b"PSUP"
PATTERN_SUPPLY_VERSION = 4
PATTERN_SUPPLY_STRUCT = struct.Struct(">4s11H")

MODE_SPECS = {
    0: ("H32", 32, 2800),
    1: ("H40", 40, 3200),
}


def header_signature(fixed_header: bytes) -> int:
    """Return the deterministic build signature for contract bytes 4..61."""
    if len(fixed_header) != FIXED_HEADER_BYTES:
        raise ValueError(
            f"fixed header must be {FIXED_HEADER_BYTES} bytes, got {len(fixed_header)}")
    return zlib.crc32(fixed_header[4:]) & 0xFFFFFFFF


def stamp_header_sector(sector: bytes) -> bytes:
    """Write the fixed-header signature into a complete first sector."""
    if len(sector) != SECTOR:
        raise ValueError(f"header sector must be {SECTOR} bytes, got {len(sector)}")
    out = bytearray(sector)
    struct.pack_into(
        ">L", out, HEADER_SIGNATURE_OFFSET,
        header_signature(bytes(out[:FIXED_HEADER_BYTES])))
    return bytes(out)


@dataclasses.dataclass(frozen=True)
class PlayerConstants:
    signature: int
    frames: int
    tcols: int
    trows: int
    cells: int
    bmbytes: int
    pool: int
    base: int
    frame_sectors: int
    nseg: int
    prebuf_pat: int
    routing_sec: int
    prebuf_sec: int
    ring_peak: int
    mode: int
    screen_cols: int
    screen_rows: int
    col0: int
    row0: int
    vbudget: int
    font_vtile: int
    font_addr: int
    f0_ctrl_sec: int
    f0_pat_sec: int
    paltab_sec: int
    vsync_n: int
    audio_bytes: int
    audio_control_bytes: int
    adpcm_table_sectors: int
    fps_int: int
    audio_fd: int
    audio_preload_sec: int
    body_arm_sec: int
    features: int
    cadence_period: int
    vsync_alt: int
    pump_mask: int
    wave_pump_mask: int
    sec_num: int
    sec_mod: int
    sec_base: int
    sec_rem: int
    sec_alt_num: int
    sec_alt_base: int
    sec_alt_rem: int
    prg_buf_cap_patterns: int
    prg_delivery_cap_patterns: int
    jitter_headroom_kb: int
    wr0_patterns: int
    wr1_patterns: int
    dic_patterns: int
    wr0_sectors: int
    wr1_sectors: int
    dic_sectors: int
    cold_cap: int
    wr0_load_bytes: int
    wr1_load_bytes: int
    routing_bytes: int
    routing_offset: int
    routing_copy_longs: int
    status_offset: int
    ctrl_scr_offset: int
    pad_scr_offset: int
    wr0_offset: int
    wr0_end: int
    wr0_capacity: int
    wr1_offset: int
    wr1_end: int
    wr1_capacity: int


def parse_header_sector(sector: bytes) -> PlayerConstants:
    """Validate one packed first sector and derive its hot player constants."""
    if len(sector) != SECTOR:
        raise ValueError(f"header sector must be {SECTOR} bytes, got {len(sector)}")
    values = HEADER_STRUCT.unpack_from(sector)
    (
        _magic, frames, tcols, trows, cells, pool, base,
        frame_sectors, nseg, prebuf_pat, routing_sec, prebuf_sec, ring_peak,
        mode, pad, f0_ctrl_sec, f0_pat_sec, paltab_sec, vsync_n,
        audio_bytes, fps_int, audio_fd, audio_preload_sec, features,
    ) = values

    if pad != 0:
        raise ValueError(f"HEADER.DAT offset 37 must be zero, got {pad}")
    if (prebuf_pat * 32) % SECTOR:
        raise ValueError(
            f"prebuffer {prebuf_pat} patterns is not a whole number of CD "
            "sectors; the player's ring tail would be half-sector-misaligned")
    if not 0 < frames <= cavc_routing.MAX_FRAMES:
        raise ValueError(f"invalid frame count: {frames}")
    if tcols <= 0 or trows <= 0 or cells != tcols * trows:
        raise ValueError(
            f"invalid tile geometry: {tcols}x{trows} cells={cells}")
    if not 0 < nseg <= av_config.PALTAB_MAX_SEG:
        raise ValueError(
            f"palette segments {nseg} exceed the fixed "
            f"{av_config.PALTAB_MAX_SEG}-segment PALTAB")
    if mode not in MODE_SPECS:
        raise ValueError(f"player constants do not support display mode {mode}")
    _mode_name, screen_cols, vbudget = MODE_SPECS[mode]
    screen_rows = 28
    if tcols > screen_cols or trows > screen_rows:
        raise ValueError(
            f"tile grid {tcols}x{trows} exceeds {screen_cols}x{screen_rows} display")
    if base + pool > av_config.VRAM_HUD_FONT_TILE:
        raise ValueError(
            f"resident pool base {base} + {pool} tiles overlaps "
            f"HUD font tile {av_config.VRAM_HUD_FONT_TILE}")
    expected_routing_sec = cavc_routing.routing_sector_count(frames)
    if routing_sec != expected_routing_sec:
        raise ValueError(
            f"routing_sec={routing_sec} != ceil({frames}/2048)={expected_routing_sec}")
    if frame_sectors != cavc_routing.FRAME_SECTORS:
        raise ValueError(
            f"frame_sectors={frame_sectors} != {cavc_routing.FRAME_SECTORS}")
    expected_paltab_sec = av_config.PALTAB_STAGE_KB * 1024 // SECTOR
    if paltab_sec != expected_paltab_sec:
        raise ValueError(
            f"paltab_sec={paltab_sec} != fixed boot-stage size "
            f"{expected_paltab_sec}")
    if audio_bytes <= 0 or fps_int <= 0 or vsync_n <= 0 or audio_fd <= 0:
        raise ValueError(
            f"invalid timing: vsync_n={vsync_n} audio={audio_bytes} "
            f"fps={fps_int} fd={audio_fd}")
    if f0_ctrl_sec <= 0 or f0_pat_sec <= 0 or audio_preload_sec <= 0:
        raise ValueError(
            "BODY arm regions must be non-empty: "
            f"audio={audio_preload_sec} control={f0_ctrl_sec} "
            f"patterns={f0_pat_sec}")

    signature = struct.unpack_from(">L", sector, HEADER_SIGNATURE_OFFSET)[0]
    expected_signature = header_signature(sector[:FIXED_HEADER_BYTES])
    if signature != expected_signature:
        raise ValueError(
            f"HEADER.DAT signature 0x{signature:08X} != expected "
            f"0x{expected_signature:08X}")

    vblank_cadence = bool(features & cavc_routing.FEATURE_VBLANK_CADENCE)
    known_features = (
        cavc_routing.FEATURE_COLD_RUNS
        | cavc_routing.FEATURE_VBLANK_CADENCE
        | cavc_routing.FEATURE_PATTERN_SUPPLY
        | cavc_routing.FEATURE_SHADOW_UPDATE_LISTS
        | cavc_routing.FEATURE_VRAM_RAW_PREFETCH
        | cavc_routing.FEATURE_DICBUF_INDEXED_RUNS
        | cavc_routing.FEATURE_BOOT_VRAM_SIDECAR
        | cavc_routing.FEATURE_WORDBUF_RING
    )
    unknown_features = features & ~known_features
    if unknown_features:
        raise ValueError(
            f"HEADER.DAT uses reserved feature bits 0x{unknown_features:04X}")
    pattern_supply_enabled = bool(features & cavc_routing.FEATURE_PATTERN_SUPPLY)
    indexed_dicbuf = bool(features & cavc_routing.FEATURE_DICBUF_INDEXED_RUNS)
    if audio_bytes & 1:
        raise ValueError(f"ADPCM decoded audio_bytes must be even, got {audio_bytes}")
    audio_control_bytes = ima_adpcm.encoded_bytes(audio_bytes)
    adpcm_table_sectors = (
        ima_adpcm.FULL_TABLE_BYTES + SECTOR - 1) // SECTOR
    if vblank_cadence:
        cadence = av_config.vblank_cadence_pattern(fps_int)
        if cadence is None:
            raise ValueError(
                f"VBlank-cadence header has no qualified schedule for fps={fps_int}")
        if cadence[0] != vsync_n:
            raise ValueError(
                f"VBlank-cadence header vsync_n={vsync_n} disagrees with "
                f"fps={fps_int} (expected {cadence[0]})")
        sec_steps, sec_mod = av_config.cd_sector_rate_steps(fps_int)
    else:
        cadence = ()
        sec_steps, sec_mod = (75,), fps_int
    cadence_period = len(cadence)
    vsync_alt = cadence[1] if len(cadence) > 1 else vsync_n
    sec_num = sec_steps[0]
    sec_alt_num = sec_steps[1] if len(sec_steps) > 1 else sec_num
    sec_base, sec_rem = divmod(sec_num, sec_mod)
    sec_alt_base, sec_alt_rem = divmod(sec_alt_num, sec_mod)
    fast_poll = fps_int >= 24

    supply_values = PATTERN_SUPPLY_STRUCT.unpack_from(sector, PATTERN_SUPPLY_OFFSET)
    (
        supply_magic, supply_version, supply_reserved,
        wr0_patterns, wr1_patterns, dic_patterns,
        wr0_sectors, wr1_sectors, dic_sectors,
        cold_cap,
        wr0_load_bytes, wr1_load_bytes,
    ) = supply_values
    if pattern_supply_enabled:
        if not indexed_dicbuf:
            raise ValueError("current pattern supply requires indexed DicBuf runs")
        if supply_magic != PATTERN_SUPPLY_MAGIC:
            raise ValueError(f"bad pattern-supply magic: {supply_magic!r}")
        if supply_version != PATTERN_SUPPLY_VERSION or supply_reserved != 0:
            raise ValueError(
                f"invalid pattern-supply header: version={supply_version} "
                f"reserved={supply_reserved}")
        if cold_cap <= 0:
            raise ValueError(f"invalid pattern-supply cold cap: {cold_cap}")
        wordram = pattern_supply.word_ram_layout(
            frames,
            cells,
            cold_cap,
            wr0_load_bytes=wr0_load_bytes,
            wr1_load_bytes=wr1_load_bytes,
        )
        capacities = (
            ("Wr0", wr0_patterns, wordram.wr0_patterns, wr0_sectors),
            ("Wr1", wr1_patterns, wordram.wr1_patterns, wr1_sectors),
            ("Dic", dic_patterns, pattern_supply.DIC_BUF_PATTERNS, dic_sectors),
        )
        for name, count, capacity, sectors in capacities:
            if not 0 <= count <= capacity:
                raise ValueError(
                    f"{name} preload count {count} exceeds capacity {capacity}")
            expected_sectors = (count + 63) // 64
            if sectors != expected_sectors:
                raise ValueError(
                    f"{name} preload sectors {sectors} != {expected_sectors} for {count} patterns")
    else:
        if supply_magic != b"\0\0\0\0" or any(supply_values[1:]):
            raise ValueError("pattern-supply extension is present while feature bit 3 is clear")
        wr0_patterns = wr1_patterns = dic_patterns = 0
        wr0_sectors = wr1_sectors = dic_sectors = 0
        wr0_load_bytes = wr1_load_bytes = 0
        # A header without pattern supply carries no cold-cap field. Its empty
        # WordBuf layout uses the full grid only as a conservative size input.
        cold_cap = cells
        wordram = pattern_supply.word_ram_layout(frames, cells, cold_cap)

    return PlayerConstants(
        signature=signature,
        frames=frames,
        tcols=tcols,
        trows=trows,
        cells=cells,
        bmbytes=(cells + 7) // 8,
        pool=pool,
        base=base,
        frame_sectors=frame_sectors,
        nseg=nseg,
        prebuf_pat=prebuf_pat,
        routing_sec=routing_sec,
        prebuf_sec=prebuf_sec,
        ring_peak=ring_peak,
        mode=mode,
        screen_cols=screen_cols,
        screen_rows=screen_rows,
        col0=(screen_cols - tcols) // 2,
        row0=(screen_rows - trows) // 2,
        vbudget=vbudget,
        font_vtile=av_config.VRAM_HUD_FONT_TILE,
        font_addr=av_config.VRAM_HUD_FONT_TILE * 32,
        f0_ctrl_sec=f0_ctrl_sec,
        f0_pat_sec=f0_pat_sec,
        paltab_sec=paltab_sec,
        vsync_n=vsync_n,
        audio_bytes=audio_bytes,
        audio_control_bytes=audio_control_bytes,
        adpcm_table_sectors=adpcm_table_sectors,
        fps_int=fps_int,
        audio_fd=audio_fd,
        audio_preload_sec=audio_preload_sec,
        body_arm_sec=audio_preload_sec + f0_ctrl_sec + f0_pat_sec,
        features=features,
        cadence_period=cadence_period,
        vsync_alt=vsync_alt,
        pump_mask=0x03FF if fast_poll else 0x003F,
        wave_pump_mask=0x01FF if fast_poll else 0x00FF,
        sec_num=sec_num,
        sec_mod=sec_mod,
        sec_base=sec_base,
        sec_rem=sec_rem,
        sec_alt_num=sec_alt_num,
        sec_alt_base=sec_alt_base,
        sec_alt_rem=sec_alt_rem,
        prg_buf_cap_patterns=(
            av_config.prg_buf_cap_kb(fps_int) * 1024 // 32),
        prg_delivery_cap_patterns=(
            av_config.scheduled_delivery_cap_kb(fps_int) * 1024 // 32),
        jitter_headroom_kb=av_config.ring_jitter_headroom_kb(fps_int),
        wr0_patterns=wr0_patterns,
        wr1_patterns=wr1_patterns,
        dic_patterns=dic_patterns,
        wr0_sectors=wr0_sectors,
        wr1_sectors=wr1_sectors,
        dic_sectors=dic_sectors,
        cold_cap=cold_cap,
        wr0_load_bytes=wordram.wr0_load_bytes,
        wr1_load_bytes=wordram.wr1_load_bytes,
        routing_bytes=wordram.routing_bytes,
        routing_offset=wordram.routing_offset,
        routing_copy_longs=wordram.routing_copy_longs,
        status_offset=wordram.status_offset,
        ctrl_scr_offset=wordram.ctrl_scr_offset,
        pad_scr_offset=wordram.pad_scr_offset,
        wr0_offset=wordram.wr0_offset,
        wr0_end=wordram.wr0_end,
        wr0_capacity=wordram.wr0_patterns,
        wr1_offset=wordram.wr1_offset,
        wr1_end=wordram.wr1_end,
        wr1_capacity=wordram.wr1_patterns,
    )


INCLUDE_ORDER = (
    "signature", "frames", "mode", "screen_cols", "screen_rows",
    "tcols", "trows", "cells", "bmbytes", "col0", "row0", "vbudget",
    "pool", "base", "font_vtile", "font_addr", "frame_sectors", "nseg",
    "prebuf_pat", "routing_sec", "prebuf_sec", "ring_peak", "f0_ctrl_sec",
    "f0_pat_sec", "paltab_sec", "vsync_n", "audio_bytes",
    "audio_control_bytes", "adpcm_table_sectors", "fps_int",
    "audio_fd", "audio_preload_sec", "body_arm_sec", "features",
    "cadence_period", "vsync_alt", "pump_mask", "wave_pump_mask",
    "sec_num", "sec_mod", "sec_base", "sec_rem",
    "sec_alt_num", "sec_alt_base", "sec_alt_rem",
    "prg_buf_cap_patterns", "prg_delivery_cap_patterns",
    "jitter_headroom_kb",
    "wr0_patterns", "wr1_patterns", "dic_patterns",
    "wr0_sectors", "wr1_sectors", "dic_sectors",
    "cold_cap", "wr0_load_bytes", "wr1_load_bytes",
    "routing_bytes", "routing_offset", "routing_copy_longs",
    "status_offset", "ctrl_scr_offset", "pad_scr_offset",
    "wr0_offset", "wr0_end", "wr0_capacity",
    "wr1_offset", "wr1_end", "wr1_capacity",
)


def render_include(constants: PlayerConstants) -> str:
    """Render a stable GNU assembler include."""
    lines = [
        "/* Generated from HEADER.DAT by tools/player_constants.py. Do not edit. */",
    ]
    for name in INCLUDE_ORDER:
        value = getattr(constants, name)
        width = 8 if value > 0xFFFF or name in {"signature", "font_addr"} else 4
        lines.append(f".equ PC_{name.upper()}, 0x{value:0{width}X}")
    lines.append("")
    return "\n".join(lines)


def generate_include(header_path: Path, output_path: Path) -> PlayerConstants:
    """Generate the include, preserving mtime when its bytes are unchanged."""
    with header_path.open("rb") as src:
        sector = src.read(SECTOR)
    constants = parse_header_sector(sector)
    rendered = render_include(constants)
    if not output_path.exists() or output_path.read_text() != rendered:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(rendered)
    return constants


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("header", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    constants = generate_include(args.header, args.output)
    print(
        f"player_constants: {args.output} signature=0x{constants.signature:08X} "
        f"{constants.tcols}x{constants.trows} {constants.fps_int}fps "
        f"audio={constants.audio_bytes} cadence={constants.cadence_period} "
        f"SP-rate={constants.sec_num}/{constants.sec_mod}"
        + (
            f",{constants.sec_alt_num}/{constants.sec_mod}"
            if constants.cadence_period > 1 else ""
        ))


if __name__ == "__main__":
    main()
