#!/usr/bin/env python3
"""Check the region release zips before anything is uploaded.

Every check reads the built artifact rather than the build inputs, so a zip
that passes here is one whose bytes say what the release page will claim.

Per zip:

1. it holds exactly the three expected members, named after the zip itself;
2. the cue sheet's FILE line names the ISO packed beside it;
3. the ISO is a Sega CD disc (`SEGADISCSYSTEM` at offset 0);
4. the disc header's hardware type and region field are the region's;
5. the boot area carries that region's security code, once, byte for byte.

Across two regions of one profile:

6. HEADER.DAT and BODY.DAT are byte-identical, which is the proof that the
   regions differ only in the boot area and that both discs play the same
   encode.

Usage::

    tools/python.sh harness/regions/verify_release.py out/releases/*.zip
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "tools"))

import disc_region  # noqa: E402

BOOT_AREA_BYTES = 32768
SECTOR_BYTES = 2048
STREAM_FILES = ("HEADER.DAT", "BODY.DAT")

# <profile-stem>_<REGION>_<date>.e<N>.p<M>.zip
ASSET_RE = re.compile(
    r"^(?P<stem>[A-Za-z0-9][A-Za-z0-9._-]*?)"
    r"_(?P<tag>[A-Z]{2})"
    r"_(?P<date>\d{8})\.(?P<version>e\d+\.p\d+)\.zip$")


class CheckFailed(Exception):
    pass


@dataclass
class Zip:
    path: Path
    stem: str
    tag: str
    date: str
    version: str
    region: disc_region.DiscRegion


def parse_asset_name(path: Path) -> Zip:
    match = ASSET_RE.match(path.name)
    if not match:
        raise CheckFailed(
            f"{path.name}: not a release asset name "
            "(<profile-stem>_<REGION>_<date>.eN.pM.zip)")
    tag = match.group("tag")
    for region in disc_region.REGIONS.values():
        if region.tag == tag:
            break
    else:
        raise CheckFailed(f"{path.name}: unknown region tag {tag}")
    if not region.releasable:
        raise CheckFailed(
            f"{path.name}: {region.name_en} is not a release target")
    return Zip(path=path, stem=match.group("stem"), tag=tag,
               date=match.group("date"), version=match.group("version"),
               region=region)


def check_members(archive: zipfile.ZipFile, asset: Zip) -> None:
    names = f"{asset.stem}_{asset.tag}"
    expected = {f"{names}.iso", f"{names}.cue", "README.txt"}
    found = set(archive.namelist())
    if found != expected:
        missing = sorted(expected - found)
        extra = sorted(found - expected)
        raise CheckFailed(
            f"{asset.path.name}: member mismatch; "
            f"missing={missing or 'none'} unexpected={extra or 'none'}")


def check_cue(archive: zipfile.ZipFile, asset: Zip) -> None:
    names = f"{asset.stem}_{asset.tag}"
    text = archive.read(f"{names}.cue").decode("utf-8")
    first = text.splitlines()[0].strip()
    expected = f'FILE "{names}.iso" BINARY'
    if first != expected:
        raise CheckFailed(
            f"{asset.path.name}: cue FILE line is {first!r}, "
            f"expected {expected!r}")


def check_disc_header(boot: bytes, asset: Zip) -> None:
    if boot[:14] != b"SEGADISCSYSTEM":
        raise CheckFailed(
            f"{asset.path.name}: not a Sega CD disc; the image does not start "
            "with SEGADISCSYSTEM")
    fields = (
        ("hardware type", disc_region.HARDWARE_TYPE_OFFSET,
         asset.region.hardware_type),
        ("region field", disc_region.REGION_FIELD_OFFSET,
         asset.region.region_field),
    )
    for label, offset, expected in fields:
        actual = boot[offset:offset + disc_region.FIELD_LENGTH].decode(
            "ascii", "replace")
        if actual != expected:
            raise CheckFailed(
                f"{asset.path.name}: {label} at 0x{offset:X} is {actual!r}, "
                f"expected {expected!r} for {asset.region.name_en}")


def check_security_code(boot: bytes, asset: Zip) -> None:
    """The console validates this, so it must be the region's own bytes.

    Requiring exactly one occurrence also catches a build that kept the
    previous region's code beside the new one.
    """

    for code_region in disc_region.REGIONS.values():
        code = (PROJECT_ROOT / "boot" / f"sec_{code_region.code}.bin"
                ).read_bytes()
        occurrences = boot.count(code)
        wanted = 1 if code_region.code == asset.region.code else 0
        if occurrences != wanted:
            raise CheckFailed(
                f"{asset.path.name}: found the {code_region.tag} security code "
                f"{occurrences} time(s) in the boot area, expected {wanted}")


def iso_files(image: bytes) -> dict[str, bytes]:
    """Read the ISO 9660 root directory and return each file's contents.

    The disc has one flat directory of a few files, so the primary volume
    descriptor's root record is all that has to be walked. Doing it here keeps
    the check independent of whichever isoinfo happens to be installed.
    """

    pvd = image[16 * SECTOR_BYTES:17 * SECTOR_BYTES]
    if pvd[0] != 1 or pvd[1:6] != b"CD001":
        raise CheckFailed("not an ISO 9660 image: no primary volume descriptor")
    root = pvd[156:156 + 34]
    extent = int.from_bytes(root[2:6], "little")
    length = int.from_bytes(root[10:14], "little")
    directory = image[extent * SECTOR_BYTES:extent * SECTOR_BYTES + length]

    files: dict[str, bytes] = {}
    offset = 0
    while offset < len(directory):
        record_length = directory[offset]
        if record_length == 0:
            # The rest of this sector is padding; step to the next one.
            offset = (offset // SECTOR_BYTES + 1) * SECTOR_BYTES
            continue
        record = directory[offset:offset + record_length]
        name_length = record[32]
        name = record[33:33 + name_length].decode("ascii", "replace")
        if name not in ("\x00", "\x01"):
            file_extent = int.from_bytes(record[2:6], "little")
            file_length = int.from_bytes(record[10:14], "little")
            start = file_extent * SECTOR_BYTES
            files[name.split(";")[0]] = image[start:start + file_length]
        offset += record_length
    return files


def check_stream_identity(assets: list[tuple[Zip, dict[str, bytes]]]) -> None:
    """Both regions of one profile must carry the same packed stream."""

    reference_asset, reference_files = assets[0]
    for asset, files in assets[1:]:
        for name in STREAM_FILES:
            if name not in reference_files or name not in files:
                raise CheckFailed(
                    f"{asset.path.name}: the disc has no {name}")
            left = hashlib.sha256(reference_files[name]).hexdigest()
            right = hashlib.sha256(files[name]).hexdigest()
            if left != right:
                raise CheckFailed(
                    f"{reference_asset.tag} and {asset.tag} {name} differ "
                    f"({left[:12]} vs {right[:12]}); the regions must differ "
                    "only in the boot area")


def verify(paths: list[Path]) -> int:
    by_stem: dict[str, list[tuple[Zip, dict[str, bytes]]]] = defaultdict(list)
    failures: list[str] = []
    checks = 0

    for path in sorted(paths):
        try:
            asset = parse_asset_name(path)
            with zipfile.ZipFile(path) as archive:
                bad = archive.testzip()
                if bad is not None:
                    raise CheckFailed(f"{path.name}: corrupt member {bad}")
                check_members(archive, asset)
                check_cue(archive, asset)
                image = archive.read(f"{asset.stem}_{asset.tag}.iso")
            check_disc_header(image[:BOOT_AREA_BYTES], asset)
            check_security_code(image[:BOOT_AREA_BYTES], asset)
            files = iso_files(image)
            by_stem[asset.stem].append((asset, files))
        except CheckFailed as exc:
            failures.append(str(exc))
            print(f"FAIL {path.name}: {exc}", flush=True)
            continue
        checks += 1
        print(f"PASS {path.name}: {asset.region.name_en}, "
              f"{len(image) / (1024 * 1024):.1f} MiB image", flush=True)

    for stem, assets in sorted(by_stem.items()):
        if len(assets) < 2:
            print(f"NOTE {stem}: only {assets[0][0].tag} present; the "
                  "cross-region stream check needs both", flush=True)
            continue
        try:
            check_stream_identity(assets)
        except CheckFailed as exc:
            failures.append(str(exc))
            print(f"FAIL {stem}: {exc}", flush=True)
            continue
        tags = "/".join(item[0].tag for item in assets)
        print(f"PASS {stem}: {tags} HEADER.DAT and BODY.DAT are identical",
              flush=True)

    if failures:
        print(f"\n{len(failures)} check(s) failed", flush=True)
        return 1
    print(f"\nall checks passed ({checks} zip(s))", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("zips", nargs="+", type=Path)
    args = parser.parse_args(argv)
    return verify(args.zips)


if __name__ == "__main__":
    raise SystemExit(main())
