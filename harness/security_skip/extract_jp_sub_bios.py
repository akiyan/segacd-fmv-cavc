#!/usr/bin/env python3
"""Extract the three Sub-CPU modules embedded in the JP Mega-CD 2 BIOS.

The stock BIOS routine at Main-CPU address 0x06A4 calls its Kosinski decoder
at 0x07D8 three times.  The source and PRG-RAM destination pairs are:

    ROM 0x16000 -> PRG-RAM 0x00000
    ROM 0x13400 -> PRG-RAM 0x06000
    ROM 0x1A000 -> PRG-RAM 0x18000

This script is a byte-for-byte Python transcription of that decoder, including
its little-endian 16-bit description fields and signed back references.
"""

from __future__ import annotations

import argparse
import hashlib
from dataclasses import dataclass
from pathlib import Path


MODULES = (
    (0x16000, 0x00000, "sub_prg_00000.bin"),
    (0x13400, 0x06000, "sub_prg_06000.bin"),
    (0x1A000, 0x18000, "sub_prg_18000.bin"),
)


@dataclass
class BitReader:
    source: bytes
    position: int
    description: int = 0
    remaining: int = 0

    def byte(self) -> int:
        if self.position >= len(self.source):
            raise ValueError("compressed stream ran past the BIOS image")
        value = self.source[self.position]
        self.position += 1
        return value

    def bit(self) -> int:
        if self.remaining == 0:
            self.refill()
        value = self.description & 1
        self.description >>= 1
        self.remaining -= 1
        # The BIOS reloads immediately after consuming a descriptor's final
        # bit, before it reads any literal or back-reference bytes belonging
        # to that token. Delaying this until the next bit would swap those
        # interleaved bytes with the next description word.
        if self.remaining == 0:
            self.refill()
        return value

    def refill(self) -> None:
        low = self.byte()
        high = self.byte()
        self.description = low | (high << 8)
        self.remaining = 16


def signed_offset_8(value: int) -> int:
    # moveq #-1 followed by move.b leaves the index word as 0xFFxx, so this
    # short-form displacement is always in the preceding 256-byte window.
    return value - 0x100


def signed_offset_13(low: int, high_and_length: int) -> int:
    value = ((high_and_length & 0xF8) << 5) | low
    # The 68000 routine starts d2 at -1 before replacing its low byte and
    # shifting the low word, so bits 13..15 remain set. Kosinski's long-form
    # displacement is therefore always a negative 13-bit value.
    return value - 0x2000


def append_byte(
    output: bytearray, prg_ram: bytearray, destination: int, value: int
) -> None:
    prg_offset = destination + len(output)
    if prg_offset >= len(prg_ram):
        raise ValueError(f"decoded module runs past PRG-RAM at 0x{prg_offset:x}")
    output.append(value)
    prg_ram[prg_offset] = value


def copy_back_reference(
    output: bytearray,
    offset: int,
    length: int,
    *,
    bios: bytes,
    prg_ram: bytearray,
    destination: int,
) -> None:
    if offset >= 0:
        raise ValueError(f"non-negative Kosinski offset: {offset}")
    for _ in range(length):
        source_prg_offset = destination + len(output) + offset
        if source_prg_offset >= 0:
            value = prg_ram[source_prg_offset]
        else:
            # The first module starts at Main address 0x020000. Its earliest
            # back references cross that boundary into the BIOS ROM's 0xFF
            # tail, exactly as the real 68000 indexed read does.
            bios_offset = 0x20000 + source_prg_offset
            if bios_offset < 0:
                raise ValueError(
                    f"back reference precedes BIOS ROM: 0x{bios_offset:x}"
                )
            value = bios[bios_offset]
        append_byte(output, prg_ram, destination, value)


def kosinski_decompress(
    source: bytes,
    start: int,
    destination: int,
    prg_ram: bytearray,
) -> tuple[bytes, int]:
    reader = BitReader(source, start)
    output = bytearray()
    while True:
        if reader.bit():
            append_byte(output, prg_ram, destination, reader.byte())
            continue

        if not reader.bit():
            length_code = (reader.bit() << 1) | reader.bit()
            offset = signed_offset_8(reader.byte())
            copy_back_reference(
                output, offset, length_code + 2,
                bios=source, prg_ram=prg_ram, destination=destination,
            )
            continue

        low = reader.byte()
        high_and_length = reader.byte()
        offset = signed_offset_13(low, high_and_length)
        length_code = high_and_length & 7
        if length_code:
            copy_back_reference(
                output, offset, length_code + 2,
                bios=source, prg_ram=prg_ram, destination=destination,
            )
            continue

        extended_length = reader.byte()
        if extended_length == 0:
            return bytes(output), reader.position - start
        if extended_length == 1:
            continue
        copy_back_reference(
            output, offset, extended_length + 1,
            bios=source, prg_ram=prg_ram, destination=destination,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bios", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    bios = args.bios.read_bytes()
    if len(bios) != 0x20000:
        raise SystemExit(
            f"expected a 128-KiB Mega-CD BIOS, got {len(bios)} bytes"
        )
    args.output_dir.mkdir(parents=True, exist_ok=True)

    prg_ram = bytearray(0x80000)
    for source_offset, destination, name in MODULES:
        decoded, consumed = kosinski_decompress(
            bios, source_offset, destination, prg_ram
        )
        path = args.output_dir / name
        path.write_bytes(decoded)
        digest = hashlib.sha256(decoded).hexdigest()
        print(
            f"rom=0x{source_offset:05x} consumed=0x{consumed:x} "
            f"prg=0x{destination:05x} bytes=0x{len(decoded):x} "
            f"sha256={digest} path={path}"
        )


if __name__ == "__main__":
    main()
