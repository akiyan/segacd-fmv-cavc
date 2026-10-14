#!/usr/bin/env python3
"""Inspect little-endian GPGX 1.7.6 snapshots from the pinned LOGVDP core."""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path


def core_state(path):
    raw = path.read_bytes()
    if raw[:8] == b"#RZIPv\x01#":
        expected = struct.unpack_from("<Q", raw, 12)[0]
        offset, chunks = 20, []
        while offset < len(raw):
            size = struct.unpack_from("<I", raw, offset)[0]
            offset += 4
            if offset + size > len(raw):
                raise ValueError("truncated RZIP chunk")
            chunks.append(zlib.decompress(raw[offset:offset + size]))
            offset += size
        raw = b"".join(chunks)
        if len(raw) != expected:
            raise ValueError("RZIP length mismatch")
    if raw[:8] != b"RASTATE\x01":
        raise ValueError("expected a RetroArch RASTATE version 1 snapshot")
    offset = 8
    while offset + 8 <= len(raw):
        name = raw[offset:offset + 4]
        size = struct.unpack_from("<I", raw, offset + 4)[0]
        offset += 8
        if offset + size > len(raw):
            raise ValueError("truncated RASTATE chunk")
        if name == b"MEM ":
            data = raw[offset:offset + size]
            if data[:16] != b"GENPLUS-GX 1.7.6":
                raise ValueError("snapshot is not from the expected GPGX version")
            return data
        offset += (size + 7) // 8 * 8
    raise ValueError("missing core state")


def words(data):
    """GPGX's x86 RAM arrays store the low byte first in each 68000 word."""
    if len(data) % 2:
        raise ValueError("odd RAM image")
    result = bytearray(len(data))
    result[::2], result[1::2] = data[1::2], data[::2]
    return bytes(result)


def inspect(path, sp_module=None, menu_ip=None, menu_sp=None):
    data = core_state(path)
    main = words(data[16:16 + 65536])
    magic, index, reserved, cycle, visit = struct.unpack_from(">IHHII", main, 0xB1D0)
    if magic != 0x504C5354:
        raise ValueError("no playlist state signature")
    result = dict(state=str(path.resolve()),
                  state_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  playlist=dict(index=index, cycle=cycle, visit=visit))
    if menu_ip:
        expected = menu_ip.read_bytes()
        result["main_menu_matches"] = main[:len(expected)] == expected
        result["main_menu_shifted_one_sector"] = main[2048:len(expected)] == expected[:-2048]
    if sp_module:
        # state.c/scd.c store PRG followed by both Word-RAM banks. Locate the
        # BIOS module's fixed header in that section, then check its full RAM
        # bounds. Using the explicit module avoids guessing a CPU's memory map.
        scd = data.index(b"SCD!") + 4
        location = data.find(words(sp_module.read_bytes()[:64]), scd)
        prg = location - 0x6000
        if location < 0 or prg < scd or prg + 0xC0000 + 106 > len(data):
            raise ValueError("selected Sub module not found in the CD state")
        sub = words(data[prg:prg + 0x80000])
        result["menu_info"] = sub[0x7F20:0x7F50].hex()
        result["bank_stub"] = sub[0x7F50:0x7F66].hex()
        # Two cpu_idle_t records (12 bytes each), a 2-byte H-INT vector,
        # then D0-D7/A0-A7/PC as native uint32 values in scd_context_save.
        result["sub_pc"] = hex(struct.unpack_from("<I", data, prg + 0xC0000 + 26 + 64)[0])
        result["communication"] = {hex(i): hex(struct.unpack_from("<H", data, scd + i)[0])
                                   for i in (0x10, 0x12, 0x20, 0x22)}
        if menu_sp:
            expected = menu_sp.read_bytes()[:64]
            word_ram = words(data[prg + 0x80000:prg + 0xC0000])
            result["word_bank_menu_offsets"] = [
                word_ram[i * 0x20000:(i + 1) * 0x20000].find(expected) for i in (0, 1)]
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("state", type=Path)
    parser.add_argument("--sp-module", type=Path)
    parser.add_argument("--menu-ip", type=Path)
    parser.add_argument("--menu-sp", type=Path)
    args = parser.parse_args()
    print(json.dumps(inspect(args.state, args.sp_module, args.menu_ip, args.menu_sp), indent=2))
