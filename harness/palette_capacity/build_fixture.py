#!/usr/bin/env python3
"""Build a synthetic DEBUG disc exercising every palette and DicBuf's tail."""

from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import av_config
import ima_adpcm
import pack_stream
import pattern_supply
import player_constants
import sp_extension
from harness.player_constants.verify import find_tool, run


def fixture_log(segments: int, fps: int) -> dict:
    frames = segments * 4
    palettes = []
    for segment in range(segments):
        palette = np.full((4, 15, 3), 3, np.uint8)
        palette[:, 1] = (segment % 8, (segment // 8) % 8, 3)
        palette[0, 0] = 0
        palette[0, 14] = 7
        palettes.append(palette)
    # Keep all 512 entries occupied; the last movie frame reads entry 511.
    dictionary = tuple(
        struct.pack(">H", index) + bytes([0x22]) * 30
        for index in range(512))
    packed_tail = np.frombuffer(dictionary[-1], np.uint8)
    tail_key = np.column_stack((packed_tail >> 4, packed_tail & 15)).tobytes()
    updates = [[] for _ in range(frames)]
    updates[0] = [(cell, cell % 4, bytes([2]) * 64) for cell in range(40 * 28)]
    updates[-1] = [(0, 0, tail_key)]
    rate, pcm, control = av_config.audio_frame_layout(fps)
    return {
        "frames": updates,
        "frame_seg": np.repeat(np.arange(segments), 4),
        "seg_pals": palettes,
        "geom": (40, 28, 40 * 28, 8),
        "fps": fps,
        "vram_tiles": av_config.VRAM_PATTERN_POOL_TILES,
        "max_cold": 190,
        "config": {"audio": {
            "rate": rate, "pcm_bytes": pcm, "control_bytes": control,
            "checkpoint_bytes": av_config.IMA_CHECKPOINT_BYTES,
        }},
        "pattern_supply": {
            "schema_version": 5,
            "sources": [
                [pattern_supply.SOURCE_PRG] * len(frame) if i == 0
                else [pattern_supply.SOURCE_DIC] * len(frame)
                for i, frame in enumerate(updates)
            ],
            "dic_dictionary": dictionary,
        },
    }


def pack_fixture(directory: Path, log: dict, extension: bytes) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    pack_stream.configure_from_log(log)
    pack_stream.require_canonical_p0_debug_colours(log)
    per, prefetch, orders, loads, updates, _pal, patterns, tearing = (
        pack_stream.resolve(log, log["vram_tiles"]))
    assert tearing == 0
    supply = pattern_supply.plan_supply(
        log, per, patterns, prefetch_per=prefetch, transfer_orders=orders)
    assert len(supply.dic_patterns) == 512
    assert supply.dic_indices[-1] == (511,)
    _tiles, runs = pack_stream.run_stats(
        per, supply.sources, prefetch, supply.dic_indices, orders)
    wr0, wr1 = pattern_supply.output_load_peaks(supply.prg_loads, runs)
    layout = pattern_supply.word_ram_layout(
        len(per), pack_stream.C_CELLS, log["max_cold"],
        wr0_load_bytes=wr0.bytes, wr1_load_bytes=wr1.bytes)
    silence, _state = ima_adpcm.encode_chunk(
        np.zeros(pack_stream.AUDIO_PCM, np.int16))
    # Supply exact silent PCM/ADPCM fixture bytes without creating audio media.
    with patch.object(pack_stream, "build_audio_chunks", return_value=(
            [silence] * len(per), [bytes(pack_stream.AUDIO_PCM)] * len(per))):
        blocks, pcm = pack_stream.build_control(
            log, per, updates, None, supply.sources,
            prefetch_per=prefetch, dic_indices=supply.dic_indices,
            transfer_orders=orders)
    schedule = pack_stream.schedule(per, supply.prg_loads, blocks)
    pack_stream.decode_verify(log, per, blocks, supply, schedule)
    pack_stream.write_stream(
        directory / "MOVIE.DAT", log, per, blocks, pcm, supply,
        layout, schedule, log["vram_tiles"], sp_extension_bytes=extension)
    table = (directory / "paltab.bin").read_bytes()
    index = (directory / "palidx.bin").read_bytes()
    assert len(table) == len(log["seg_pals"]) * 128
    assert len(index) == av_config.PALIDX_BYTES
    cursor = segment = 0
    for frame, expected in enumerate(log["frame_seg"]):
        while struct.unpack_from(">H", index, cursor)[0] <= frame:
            segment = struct.unpack_from(">H", index, cursor + 2)[0]
            cursor += 4
        assert segment == expected
        assert table[segment * 128:(segment + 1) * 128] == (
            pack_stream.pals_to_bytes_128(log["seg_pals"][expected]))
    assert struct.unpack_from(">HH", index, cursor) == (0xFFFF, 0)


def build(directory: Path, fps: int, segments: int, generic: bool) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    assembler, linker, objcopy, objdump = (
        find_tool("m68k-elf-" + name) for name in ("as", "ld", "objcopy", "objdump"))
    common = [str(assembler), "-m68000", "--register-prefix-optional", "--bitwise-or"]
    includes = ["-I", str(directory), "-I", str(ROOT / "boot")]
    run(common + includes + [str(ROOT / "boot/movieplay_sp_ext.s"),
                            "-o", str(directory / "movieplay_sp_ext.o")])
    extension = directory / "movieplay_sp_ext.bin"
    run([str(linker), "-nostdlib", "--oformat", "binary",
         "-T", str(ROOT / "cfg/sp_ext.ld"), "-o", str(extension),
         str(directory / "movieplay_sp_ext.o")])
    sp_extension.generate(extension, directory / "sp_extension.inc")
    pack_fixture(directory, fixture_log(segments, fps), extension.read_bytes())
    player_constants.generate_include(
        directory / "HEADER.DAT", directory / "player_constants.inc")
    run([sys.executable, str(ROOT / "tools/check_player_ring.py"),
         "--constants", str(directory / "player_constants.inc"),
         "--extension", str(extension),
         "--extension-constants", str(directory / "sp_extension.inc")])
    shutil.copyfile(ROOT / "boot/sec_jp.bin", directory / "security.bin")
    shutil.copyfile(ROOT / "boot/region_jp.inc", directory / "disc_region.inc")
    run([sys.executable, str(ROOT / "tools/gen_debugfont.py"),
         "--output", str(directory / "dbgfont.bin")])
    flags = ["--defsym", "DEBUG=1", "--defsym", "MAIN_CODEGEN=1"]
    if not generic:
        flags += ["--defsym", "PLAYER_SPECIALIZED=1"]
    for domain in ("ip", "sp"):
        obj = directory / f"movieplay_{domain}.o"
        binary = obj.with_suffix(".bin")
        run(common + flags + includes + [str(ROOT / f"boot/movieplay_{domain}.s"),
                                        "-o", str(obj)])
        run([str(linker), "-nostdlib", "--oformat", "binary",
             "-T", str(ROOT / f"cfg/{domain}.ld"), "-o", str(binary), str(obj)])
        (directory / f"{domain}-disassembly.txt").write_text(run([
            str(objdump), "-m", "68000", "-b", "binary", "-D", str(binary)]))
        if domain == "ip":
            assert binary.stat().st_size <= 18944
    boot_obj = directory / "movieplay_boot.o"
    boot_bin = boot_obj.with_suffix(".bin")
    run(common + includes + [str(ROOT / "boot/movieplay_boot.s"), "-o", str(boot_obj)])
    run([str(objcopy), "-O", "binary", str(boot_obj), str(boot_bin)])
    disc = directory / "disc"
    disc.mkdir(exist_ok=True)
    for name in ("HEADER.DAT", "BODY.DAT"):
        shutil.copyfile(directory / name, disc / name)
    iso = directory / "palette.iso"
    mkisofs = shutil.which("mkisofs") or shutil.which("genisoimage")
    if mkisofs is None:
        raise SystemExit("mkisofs or genisoimage is required")
    run([mkisofs, "-iso-level", "1", "-G", str(boot_bin), "-pad",
         "-V", "PALETTE", "-o", str(iso), str(disc)])
    cue = iso.with_suffix(".cue")
    cue.write_text('FILE "palette.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n')
    return cue


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=int, choices=(15, 30), required=True)
    parser.add_argument("--segments", type=int, default=64)
    parser.add_argument("--generic", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.segments <= av_config.PALTAB_MAX_SEG:
        parser.error("segments must fit the configured palette capacity")
    print(build(args.output.resolve(), args.fps, args.segments, args.generic))
