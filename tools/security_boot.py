#!/usr/bin/env python3
"""Stage the skip copy and verify either single-video BIOS-screen mode.

The Sega CD BIOS validates the region's original security program before it
runs the Main IP.  The single-video disc keeps those bytes untouched at disc
offset 0x200.  Its declared IP load is one 256-KiB Word-RAM wrap plus one
32-KiB IP slot, so a second copy of the IP overwrites the executable slot only
after validation.  The second copy differs solely at the BIOS licence-screen
call.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import disc_region


SECTOR_BYTES = 2048
WORD_RAM_BYTES = 0x40000
IP_DISC_OFFSET = 0x200
ALT_IP_DISC_OFFSET = IP_DISC_OFFSET + WORD_RAM_BYTES
IP_SLOT_BYTES = 0x8000
BIOS_IP_LOAD_BYTES = WORD_RAM_BYTES + IP_SLOT_BYTES

# A four-file ISO 9660 root made by genisoimage puts the alphabetically first
# regular file immediately after the root directory at LBA 24.  Verification
# rejects the image if that construction changes.
ALT_FILE_NAME = "AIP.BIN;1"
ALT_FILE_LBA = 24
ALT_FILE_BYTES = WORD_RAM_BYTES
ALT_IP_FILE_OFFSET = ALT_IP_DISC_OFFSET - ALT_FILE_LBA * SECTOR_BYTES

DISPLAY_CALL = bytes.fromhex("4e b8 03 64")  # jsr $0364
NOP_PAIR = bytes.fromhex("4e 71 4e 71")
DISPLAY_CALL_OFFSETS = {
    "jp": 0x26,
    "us": 0x04,
    "eu": 0x04,
}


@dataclass(frozen=True)
class IsoFile:
    lba: int
    size: int


def _fail(message: str) -> ValueError:
    return ValueError(f"security boot: {message}")


def _patch_slot(slot: bytes, security: bytes, region_code: str) -> bytes:
    """Patch one complete post-header boot window."""

    region = disc_region.region(region_code)
    try:
        call_offset = DISPLAY_CALL_OFFSETS[region.code]
    except KeyError as exc:
        raise _fail(f"no display-call location for region {region.code}") from exc
    if len(slot) != IP_SLOT_BYTES:
        raise _fail(
            f"alternate slot is {len(slot)} bytes; expected {IP_SLOT_BYTES}")
    if not slot.startswith(security):
        raise _fail(f"{region.code} slot does not start with its security code")
    if call_offset + len(DISPLAY_CALL) > len(security):
        raise _fail(
            f"{region.code} display call falls outside its security code")
    if security[call_offset:call_offset + len(DISPLAY_CALL)] != DISPLAY_CALL:
        found = security[call_offset:call_offset + len(DISPLAY_CALL)].hex()
        raise _fail(
            f"{region.code} security display call is {found}, expected "
            f"{DISPLAY_CALL.hex()}")
    alternate = bytearray(slot)
    alternate[call_offset:call_offset + len(NOP_PAIR)] = NOP_PAIR
    return bytes(alternate)


def alternate_slot(
    boot: bytes,
    ip: bytes,
    security: bytes,
    region_code: str,
) -> bytes:
    """Return the post-header boot window with only the display call replaced."""

    region = disc_region.region(region_code)
    if not ip.startswith(security):
        raise _fail(f"{region.code} IP does not start with its security code")
    if len(boot) != IP_SLOT_BYTES:
        raise _fail(
            f"boot image is {len(boot)} bytes; expected {IP_SLOT_BYTES} bytes")
    if len(ip) > IP_SLOT_BYTES - IP_DISC_OFFSET:
        raise _fail(f"IP is too large for the disc system area: {len(ip)} bytes")
    if boot[IP_DISC_OFFSET:IP_DISC_OFFSET + len(ip)] != ip:
        raise _fail("boot image does not contain the supplied IP at +0x200")
    # The 32-KiB post-wrap source begins at disc +0x40200, matching the
    # original source beginning at +0x200.  It therefore contains the Main IP,
    # the padding up to +0x6000, and the BIOS-loaded Sub SP source.  The final
    # 512 bytes have no counterpart in the 32-KiB system area and stay zero.
    alternate = bytearray(boot[IP_DISC_OFFSET:])
    alternate.extend(b"\0" * IP_DISC_OFFSET)
    return _patch_slot(bytes(alternate), security, region.code)


def wrap_file(
    boot: bytes,
    ip: bytes,
    security: bytes,
    region_code: str,
) -> bytes:
    """Return the fixed-size ISO file that supplies the post-wrap IP."""

    alternate = alternate_slot(boot, ip, security, region_code)
    end = ALT_IP_FILE_OFFSET + len(alternate)
    if ALT_IP_FILE_OFFSET < 0 or end > ALT_FILE_BYTES:
        raise _fail("alternate IP does not fit in AIP.BIN")
    staged = bytearray(ALT_FILE_BYTES)
    staged[ALT_IP_FILE_OFFSET:end] = alternate
    return bytes(staged)


def _write_if_changed(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)


def stage(
    ip_path: Path,
    boot_path: Path,
    security_path: Path,
    output_path: Path,
    region_code: str,
) -> None:
    ip = ip_path.read_bytes()
    boot = boot_path.read_bytes()
    security = security_path.read_bytes()
    data = wrap_file(boot, ip, security, region_code)
    _write_if_changed(output_path, data)
    call_offset = DISPLAY_CALL_OFFSETS[disc_region.region(region_code).code]
    print(
        f"security boot: staged {output_path} ({len(data)} bytes), "
        f"alternate IP at file +0x{ALT_IP_FILE_OFFSET:X}, "
        f"display call +0x{call_offset:X} -> NOP")


def _both_endian_u32(record: bytes, offset: int, label: str) -> int:
    little = int.from_bytes(record[offset:offset + 4], "little")
    big = int.from_bytes(record[offset + 4:offset + 8], "big")
    if little != big:
        raise _fail(f"ISO 9660 {label} endian copies disagree")
    return little


def iso_root_files(image: bytes) -> dict[str, IsoFile]:
    """Read regular-file extents from the primary ISO 9660 root directory."""

    pvd_offset = 16 * SECTOR_BYTES
    pvd = image[pvd_offset:pvd_offset + SECTOR_BYTES]
    if len(pvd) != SECTOR_BYTES or pvd[:7] != b"\x01CD001\x01":
        raise _fail("missing ISO 9660 primary volume descriptor")
    root_len = pvd[156]
    root = pvd[156:156 + root_len]
    if len(root) < 34:
        raise _fail("invalid ISO 9660 root directory record")
    root_lba = _both_endian_u32(root, 2, "root LBA")
    root_size = _both_endian_u32(root, 10, "root size")
    start = root_lba * SECTOR_BYTES
    directory = image[start:start + root_size]
    if len(directory) != root_size:
        raise _fail("truncated ISO 9660 root directory")

    files: dict[str, IsoFile] = {}
    position = 0
    while position < len(directory):
        record_len = directory[position]
        if record_len == 0:
            position = ((position // SECTOR_BYTES) + 1) * SECTOR_BYTES
            continue
        record = directory[position:position + record_len]
        if len(record) != record_len or record_len < 34:
            raise _fail("truncated ISO 9660 directory record")
        name_len = record[32]
        name_bytes = record[33:33 + name_len]
        if name_bytes not in (b"\x00", b"\x01"):
            try:
                name = name_bytes.decode("ascii")
            except UnicodeDecodeError as exc:
                raise _fail("non-ASCII ISO 9660 filename") from exc
            files[name] = IsoFile(
                lba=_both_endian_u32(record, 2, f"{name} LBA"),
                size=_both_endian_u32(record, 10, f"{name} size"),
            )
        position += record_len
    return files


def _verify_header_and_security(
    image: bytes,
    security: bytes,
    region_code: str,
) -> disc_region.DiscRegion:
    region = disc_region.region(region_code)
    if image[:16] != b"SEGADISCSYSTEM  ":
        raise _fail("disc header does not start with SEGADISCSYSTEM")
    hardware = image[
        disc_region.HARDWARE_TYPE_OFFSET:
        disc_region.HARDWARE_TYPE_OFFSET + disc_region.FIELD_LENGTH]
    if hardware != region.hardware_type.encode("ascii"):
        raise _fail(f"disc hardware field does not match {region.code}")
    region_field = image[
        disc_region.REGION_FIELD_OFFSET:
        disc_region.REGION_FIELD_OFFSET + disc_region.FIELD_LENGTH]
    if region_field != region.region_field.encode("ascii"):
        raise _fail(f"disc region field does not match {region.code}")
    if image[IP_DISC_OFFSET:IP_DISC_OFFSET + len(security)] != security:
        raise _fail(f"original {region.code} security code changed")
    return region


def verify_image(image: bytes, security: bytes, region_code: str) -> IsoFile:
    """Verify the skip construction using only published ISO bytes."""

    region = _verify_header_and_security(image, security, region_code)
    declared_ip = int.from_bytes(image[0x34:0x38], "big")
    if declared_ip != BIOS_IP_LOAD_BYTES:
        raise _fail(
            f"declared IP load is 0x{declared_ip:X}, expected "
            f"0x{BIOS_IP_LOAD_BYTES:X}")

    files = iso_root_files(image)
    alt_file = files.get(ALT_FILE_NAME)
    if alt_file is None:
        raise _fail(f"ISO root has no {ALT_FILE_NAME}")
    if alt_file != IsoFile(lba=ALT_FILE_LBA, size=ALT_FILE_BYTES):
        raise _fail(
            f"{ALT_FILE_NAME} is LBA {alt_file.lba}, {alt_file.size} bytes; "
            f"expected LBA {ALT_FILE_LBA}, {ALT_FILE_BYTES} bytes")

    original_slot = (
        image[IP_DISC_OFFSET:IP_SLOT_BYTES] + b"\0" * IP_DISC_OFFSET)
    alternate = _patch_slot(original_slot, security, region.code)
    expected_wrap = bytearray(ALT_FILE_BYTES)
    expected_wrap[
        ALT_IP_FILE_OFFSET:ALT_IP_FILE_OFFSET + IP_SLOT_BYTES] = alternate
    alt_file_start = alt_file.lba * SECTOR_BYTES
    if image[alt_file_start:alt_file_start + alt_file.size] != expected_wrap:
        raise _fail(
            f"{ALT_FILE_NAME} differs from the original boot window outside "
            "the display-call patch")
    if image[ALT_IP_DISC_OFFSET:ALT_IP_DISC_OFFSET + IP_SLOT_BYTES] != alternate:
        raise _fail("post-wrap IP is not at absolute disc offset 0x40200")

    body = files.get("BODY.DAT;1")
    first_safe_lba = ALT_FILE_LBA + ALT_FILE_BYTES // SECTOR_BYTES
    if body is None:
        raise _fail("ISO root has no BODY.DAT;1")
    if body.lba < first_safe_lba:
        raise _fail(
            f"BODY.DAT starts at LBA {body.lba}; must be at or after "
            f"LBA {first_safe_lba}")
    return body


def verify_original_image(
    image: bytes,
    security: bytes,
    region_code: str,
    expected_ip_size: int | None = None,
) -> IsoFile:
    """Verify the ordinary BIOS-screen construction from published bytes."""

    region = _verify_header_and_security(image, security, region_code)
    declared_ip = int.from_bytes(image[0x34:0x38], "big")
    if not 0 < declared_ip <= IP_SLOT_BYTES - IP_DISC_OFFSET:
        raise _fail(
            f"declared original IP load 0x{declared_ip:X} does not fit the "
            "disc system area")
    if expected_ip_size is not None and declared_ip != expected_ip_size:
        raise _fail(
            f"declared original IP load is 0x{declared_ip:X}, expected "
            f"0x{expected_ip_size:X}")
    call_offset = DISPLAY_CALL_OFFSETS[region.code]
    if security[call_offset:call_offset + len(DISPLAY_CALL)] != DISPLAY_CALL:
        raise _fail(
            f"original {region.code} security display call is not present")

    files = iso_root_files(image)
    if ALT_FILE_NAME in files:
        raise _fail(
            f"ordinary BIOS-screen ISO unexpectedly contains {ALT_FILE_NAME}")
    body = files.get("BODY.DAT;1")
    if body is None:
        raise _fail("ISO root has no BODY.DAT;1")
    return body


def verify_image_mode(
    image: bytes,
    security: bytes,
    region_code: str,
) -> tuple[str, IsoFile]:
    """Verify either supported construction and report its screen mode."""

    declared_ip = int.from_bytes(image[0x34:0x38], "big")
    if declared_ip == BIOS_IP_LOAD_BYTES:
        return "skipped", verify_image(image, security, region_code)
    return "shown", verify_original_image(image, security, region_code)


def verify_iso(
    iso_path: Path,
    ip_path: Path,
    boot_path: Path,
    security_path: Path,
    region_code: str,
) -> None:
    image = iso_path.read_bytes()
    ip = ip_path.read_bytes()
    boot = boot_path.read_bytes()
    security = security_path.read_bytes()
    region = disc_region.region(region_code)
    alternate = alternate_slot(boot, ip, security, region.code)
    expected_wrap = wrap_file(boot, ip, security, region.code)
    body = verify_image(image, security, region.code)
    if image[IP_DISC_OFFSET:IP_DISC_OFFSET + len(ip)] != ip:
        raise _fail("original IP bytes at disc offset 0x200 changed")

    files = iso_root_files(image)
    alt_file = files.get(ALT_FILE_NAME)
    assert alt_file is not None
    alt_file_start = alt_file.lba * SECTOR_BYTES
    if image[alt_file_start:alt_file_start + alt_file.size] != expected_wrap:
        raise _fail(f"{ALT_FILE_NAME} contents do not match the alternate IP")
    if image[ALT_IP_DISC_OFFSET:ALT_IP_DISC_OFFSET + IP_SLOT_BYTES] != alternate:
        raise _fail("post-wrap IP is not at absolute disc offset 0x40200")

    call_offset = DISPLAY_CALL_OFFSETS[region.code]
    print(
        f"security boot: PASS {region.code} {iso_path}; original security "
        f"{len(security)} bytes unchanged, display call +0x{call_offset:X} "
        f"replaced after wrap, BODY LBA {body.lba}")


def verify_original_iso(
    iso_path: Path,
    ip_path: Path,
    boot_path: Path,
    security_path: Path,
    region_code: str,
) -> None:
    image = iso_path.read_bytes()
    ip = ip_path.read_bytes()
    boot = boot_path.read_bytes()
    security = security_path.read_bytes()
    region = disc_region.region(region_code)
    if len(boot) != IP_SLOT_BYTES:
        raise _fail(
            f"boot image is {len(boot)} bytes; expected {IP_SLOT_BYTES} bytes")
    if boot[IP_DISC_OFFSET:IP_DISC_OFFSET + len(ip)] != ip:
        raise _fail("boot image does not contain the supplied IP at +0x200")
    body = verify_original_image(
        image, security, region.code, expected_ip_size=len(ip))
    if image[IP_DISC_OFFSET:IP_DISC_OFFSET + len(ip)] != ip:
        raise _fail("original IP bytes at disc offset 0x200 changed")
    print(
        f"security boot: PASS {region.code} {iso_path}; original security "
        f"{len(security)} bytes unchanged, BIOS licence screen retained, "
        f"BODY LBA {body.lba}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    stage_parser = sub.add_parser("stage", help="write the fixed AIP.BIN")
    stage_parser.add_argument("--region", required=True)
    stage_parser.add_argument("--boot", required=True, type=Path)
    stage_parser.add_argument("--ip", required=True, type=Path)
    stage_parser.add_argument("--security", required=True, type=Path)
    stage_parser.add_argument("--output", required=True, type=Path)

    verify_parser = sub.add_parser("verify", help="verify the built ISO")
    verify_parser.add_argument("--region", required=True)
    verify_parser.add_argument("--iso", required=True, type=Path)
    verify_parser.add_argument("--boot", required=True, type=Path)
    verify_parser.add_argument("--ip", required=True, type=Path)
    verify_parser.add_argument("--security", required=True, type=Path)

    original_parser = sub.add_parser(
        "verify-original", help="verify an ISO that retains the BIOS screen")
    original_parser.add_argument("--region", required=True)
    original_parser.add_argument("--iso", required=True, type=Path)
    original_parser.add_argument("--boot", required=True, type=Path)
    original_parser.add_argument("--ip", required=True, type=Path)
    original_parser.add_argument("--security", required=True, type=Path)

    args = parser.parse_args()
    if args.command == "stage":
        stage(args.ip, args.boot, args.security, args.output, args.region)
    elif args.command == "verify":
        verify_iso(args.iso, args.ip, args.boot, args.security, args.region)
    else:
        verify_original_iso(
            args.iso, args.ip, args.boot, args.security, args.region)


if __name__ == "__main__":
    main()
