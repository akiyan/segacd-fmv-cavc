#!/usr/bin/env python3
"""Verify the JP Mega-CD 2 security and launch path at byte level.

This checker intentionally emits no BIOS-derived files. It decompresses the
low Sub-CPU module in memory and asserts the exact instructions and data used
by the findings in this harness's README.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

from extract_jp_sub_bios import kosinski_decompress


LOW_MODULE_SOURCE = 0x16000
LOW_MODULE_DESTINATION = 0x00000
CLASSIFIER_OFFSET = 0x3ADA
CLASSIFIER = (
    b"SEGADISC        "
    b"SEGABOOTDISC    "
    b"SEGADATADISC    "
    b"SEGADISCSYSTEM  "
)
SECURITY_REFERENCE_OFFSET = 0x3DFA
SECURITY_CHECKED_SIZE = 0x154


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
        default=Path("boot/sec_jp.bin"),
    )
    args = parser.parse_args()

    bios = args.bios.read_bytes()
    if len(bios) != 0x20000:
        raise SystemExit(
            f"expected a 128-KiB Mega-CD BIOS, got 0x{len(bios):x} bytes"
        )
    security = args.canonical_security.read_bytes()
    if len(security) != 0x156:
        raise SystemExit(
            f"expected a 0x156-byte JP security program, got 0x{len(security):x}"
        )

    prg_ram = bytearray(0x80000)
    low_module, _ = kosinski_decompress(
        bios, LOW_MODULE_SOURCE, LOW_MODULE_DESTINATION, prg_ram
    )

    expect(low_module, CLASSIFIER_OFFSET, CLASSIFIER, "disc classifier")
    # Compare classifier indices 0 and 2 with the security reference. Indices
    # 1 and 3 branch around the verifier.
    expect(
        low_module,
        0x3BAC,
        bytes.fromhex("0c40000067060c4000026612"),
        "disc-ID verifier selection",
    )
    # move.w #0x00a9,d0 followed by cmpm.w/dbne compares 170 words.
    expect(
        low_module,
        0x3DE0,
        bytes.fromhex("43fa0018303c00a9b34856c8fffc"),
        "security comparison loop",
    )
    reference = low_module[
        SECURITY_REFERENCE_OFFSET:
        SECURITY_REFERENCE_OFFSET + SECURITY_CHECKED_SIZE
    ]
    if reference != security[:SECURITY_CHECKED_SIZE]:
        raise SystemExit("embedded JP security reference differs from sec_jp.bin")

    # The first-IP copy leaves d1.w at 0xffff, and the following code reaches
    # the continuation loader without replacing d1. That loader rounds d1 up
    # to 2048-byte sectors, yielding 32 sectors.
    expect(
        low_module,
        0x3D66,
        bytes.fromhex("323c005f20d920d920d920d951c9fff6"),
        "first-IP copy loop",
    )
    expect(
        low_module,
        0x3C04,
        bytes.fromhex(
            "206d5b3e22680030b3fc00000200660e"
            "0ca800000600003466046000000a61000058"
        ),
        "IP continuation dispatch",
    )
    expect(
        low_module,
        0x3C9A,
        bytes.fromhex("2001e088e688024107ff67025280"),
        "IP sector-count calculation",
    )

    expect(bios, 0x05E8, bytes.fromhex("4ef9ffff0000"), "Main IP launch")
    expect(bios, 0x0364, bytes.fromhex("60005cd6"), "licence entry stub")
    expect(security, 0x26, bytes.fromhex("4eb80364"), "licence call")
    expect(
        security,
        0x10E,
        b"PRODUCED BY OR UNDER LICENCE FROM\0",
        "first licence string",
    )
    expect(
        security,
        0x131,
        b"KABUSHIKI KAISHA SEGA ENTERPRISES.\xff",
        "second licence string",
    )
    expect(security, 0x154, bytes.fromhex("6006"), "unchecked tail word")
    expect(
        bios,
        0x60F2,
        bytes.fromhex("52470c4700b465dc"),
        "180-frame licence wait",
    )

    bios_digest = hashlib.sha256(bios).hexdigest()
    sub_digest = hashlib.sha256(low_module).hexdigest()
    print(f"bios_sha256={bios_digest}")
    print(f"sub_prg_00000_sha256={sub_digest}")
    print("disc_ids=disc,boot,data,system")
    print("security_verifier=boot,system")
    print(f"security_checked_bytes=0x{SECURITY_CHECKED_SIZE:x}")
    print("ip_continuation_sectors=32")
    print("main_launch=0xffff0000")
    print("licence_call=0x0364")
    print("licence_wait_frames=180")
    print("status=PASS")


if __name__ == "__main__":
    main()
