#!/usr/bin/env python3
"""Extract the three Sub-CPU modules embedded in the US Sega CD 1.10 BIOS.

The US BIOS uses the same Kosinski decoder as the Japanese Mega-CD 2 BIOS,
but its compressed sources begin at different ROM offsets:

    ROM 0x15800 -> PRG-RAM 0x00000
    ROM 0x13400 -> PRG-RAM 0x06000
    ROM 0x19800 -> PRG-RAM 0x18000

The decoder is shared with ``extract_jp_sub_bios.py``. This script writes
BIOS-derived data only to the explicitly supplied output directory; generated
modules must not be committed or distributed.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from extract_jp_sub_bios import kosinski_decompress


MODULES = (
    (0x15800, 0x00000, "sub_prg_00000.bin"),
    (0x13400, 0x06000, "sub_prg_06000.bin"),
    (0x19800, 0x18000, "sub_prg_18000.bin"),
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bios", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()

    bios = args.bios.read_bytes()
    if len(bios) != 0x20000:
        raise SystemExit(
            f"expected a 128-KiB Sega CD BIOS, got {len(bios)} bytes"
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
