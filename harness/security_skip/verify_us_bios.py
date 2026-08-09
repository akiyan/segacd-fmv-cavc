#!/usr/bin/env python3
"""Verify the US Sega CD 1.10 security and launch path at byte level.

This checker emits no BIOS-derived files. It decompresses the low Sub-CPU
module in memory and asserts the exact instructions and data described in this
harness's README.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from extract_jp_sub_bios import kosinski_decompress


LOW_MODULE_SOURCE = 0x15800
LOW_MODULE_DESTINATION = 0x00000
CLASSIFIER_OFFSET = 0x3F46
CLASSIFIER = (
    b"SEGADISC        "
    b"SEGABOOTDISC    "
    b"SEGADATADISC    "
    b"SEGADISCSYSTEM  "
)
SECURITY_REFERENCE_OFFSET = 0x423C
SECURITY_CHECKED_SIZE = 0x584


def expect(image: bytes, offset: int, expected: bytes, label: str) -> None:
    actual = image[offset:offset + len(expected)]
    if actual != expected:
        raise SystemExit(
            f"{label} differs at 0x{offset:x}: expected {expected.hex()}, "
            f"got {actual.hex()}"
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("bios", type=Path)
    parser.add_argument(
        "--canonical-security",
        type=Path,
        default=Path("boot/sec_us.bin"),
    )
    args = parser.parse_args()

    bios = args.bios.read_bytes()
    if len(bios) != 0x20000:
        raise SystemExit(
            f"expected a 128-KiB Sega CD BIOS, got 0x{len(bios):x} bytes"
        )
    security = args.canonical_security.read_bytes()
    if len(security) != SECURITY_CHECKED_SIZE:
        raise SystemExit(
            "expected a 0x584-byte US security program, "
            f"got 0x{len(security):x}"
        )

    prg_ram = bytearray(0x80000)
    low_module, _ = kosinski_decompress(
        bios, LOW_MODULE_SOURCE, LOW_MODULE_DESTINATION, prg_ram
    )

    expect(low_module, CLASSIFIER_OFFSET, CLASSIFIER, "disc classifier")
    expect(
        low_module,
        0x4010,
        bytes.fromhex("0c40000067060c4000026612"),
        "disc-ID verifier selection",
    )
    # move.w #0x02c1,d0 followed by cmpm.w/dbne compares 706 words,
    # covering all 1412 bytes of the canonical US security program.
    expect(
        low_module,
        0x4222,
        bytes.fromhex("43fa0018303c02c1b34856c8fffc"),
        "security comparison loop",
    )
    reference = low_module[
        SECURITY_REFERENCE_OFFSET:
        SECURITY_REFERENCE_OFFSET + SECURITY_CHECKED_SIZE
    ]
    if reference != security:
        raise SystemExit("embedded US security reference differs from sec_us.bin")

    # The first-IP copy leaves d1.w at 0xffff. The continuation loader rounds
    # that byte count up to sectors, producing the fixed 32-sector read.
    expect(
        low_module,
        0x419C,
        bytes.fromhex("226d5b68d2fc0200323c005f20d920d920d920d951c9fff6"),
        "first-IP copy loop",
    )
    expect(
        low_module,
        0x4068,
        bytes.fromhex(
            "206d5b6822680030b3fc00000200660e"
            "0ca800000600003466046000000661000050"
        ),
        "IP continuation dispatch",
    )
    expect(
        low_module,
        0x40F6,
        bytes.fromhex("2001e088e688024107ff67025280214000043b405b66"),
        "IP sector-count calculation",
    )

    expect(bios, 0x05E6, bytes.fromhex("4ef9ffff0000"), "Main IP launch")
    expect(bios, 0x0364, bytes.fromhex("60004eb4"), "licence entry stub")
    expect(
        bios,
        0x51E2,
        bytes.fromhex(
            "303c1fff43f9ffff000041f90020000022d851c8fffc"
            "72ff6100c2b670144efab44a"
        ),
        "Word-RAM copy and launch-state selection",
    )
    expect(
        bios,
        0x521A,
        bytes.fromhex("2f38fd083f38fd062f0950f8fe28"),
        "licence routine entry",
    )
    expect(security, 0x04, bytes.fromhex("4eb80364"), "licence call")
    expect(
        security,
        0x469,
        b"PRODUCED BY OR UNDER LICENSE\0\0",
        "first licence string",
    )
    expect(
        security,
        0x487,
        b" FROM SEGA ENTERPRISES, LTD.\xff",
        "second licence string",
    )
    expect(
        bios,
        0x534A,
        bytes.fromhex("3e3c00f03f074eb80a0c"),
        "final licence hold loop setup",
    )
    expect(
        bios,
        0x5366,
        bytes.fromhex("3e 1f 51 cf ff e4"),
        "final licence hold loop branch",
    )

    bios_digest = hashlib.sha256(bios).hexdigest()
    sub_digest = hashlib.sha256(low_module).hexdigest()
    print(f"bios_sha256={bios_digest}")
    print(f"sub_prg_00000_sha256={sub_digest}")
    print("disc_ids=disc,boot,data,system")
    print("security_verifier=boot,system")
    print(f"security_checked_bytes=0x{SECURITY_CHECKED_SIZE:x}")
    print("security_unchecked_bytes=0")
    print("ip_continuation_sectors=32")
    print("main_launch=0xffff0000")
    print("licence_call=0x0364")
    print("licence_final_hold_iterations=241")
    print("status=PASS")


if __name__ == "__main__":
    main()
