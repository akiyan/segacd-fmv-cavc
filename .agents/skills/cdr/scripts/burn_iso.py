#!/usr/bin/env python3
"""Burn one Sega CD disc image to CD-R for real hardware.

A CD-R is consumed on the first attempt, so this refuses anything it cannot
justify: an image that is not a Sega CD disc, a drive with no blank media, an
image larger than the medium, and a write speed the medium does not rate. It
prints the region byte and asks for an explicit confirmation flag before it
writes, because a disc whose security code does not match the console simply
will not boot and the medium is then wasted.

Disc-At-Once is not optional here. Track-At-Once leaves a two-second pregap
that a 1991-era Sega CD drive can fail to read past, so the burn always uses
SAO with a single data track.
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

SECTOR = 2048
SEGA_HEADERS = (b"SEGADISCSYSTEM  ", b"SEGABOOTDISC    ", b"SEGADATADISC    ")
REGION_OFFSET = 0x1F0
REGION_NAMES = {"J": "Japan", "U": "North America", "E": "Europe"}


def run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(command, text=True, capture_output=True, **kwargs)


def inspect_image(path: Path) -> dict:
    """Read the Sega CD boot sector and report what console it targets."""
    if not path.is_file():
        raise SystemExit(f"image not found: {path}")
    size = path.stat().st_size
    if size % SECTOR:
        raise SystemExit(
            f"{path}: {size} bytes is not a whole number of {SECTOR}-byte "
            "sectors; this is not a Mode1/2048 image")
    head = path.read_bytes()[:0x200]
    header = head[:16]
    if header not in SEGA_HEADERS:
        raise SystemExit(
            f"{path}: boot sector says {header!r}, which is not a Sega CD "
            "disc header; refusing to spend a CD-R on it")
    region_field = head[REGION_OFFSET:REGION_OFFSET + 16].decode(
        "latin1", "replace")
    region = region_field.strip()[:1] or "?"
    return {
        "size": size,
        "sectors": size // SECTOR,
        "header": header.decode("latin1"),
        "volume": head[16:27].decode("latin1", "replace").strip(),
        "system": head[0x100:0x110].decode("latin1", "replace").strip(),
        "name": head[0x120:0x150].decode("latin1", "replace").strip(),
        "region": region,
        "region_name": REGION_NAMES.get(region, "unknown"),
    }


def probe_media(device: str) -> dict:
    """Return the drive and blank-medium facts cdrskin reports."""
    result = run(["cdrskin", f"dev={device}", "-atip"])
    text = result.stdout + result.stderr
    if "BURN_DISC_EMPTY" in text or "no disc at all" in text:
        raise SystemExit(f"{device}: no disc in the drive; insert a blank CD-R")
    blank = "burn_disc_blank" in text or "blank disc" in text
    erasable = "Is erasable" in text
    lead_out = re.search(r"start of lead out:\s*(\d+)", text)
    low = re.search(r"1T speed low:\s*(\d+)", text)
    high = re.search(r"1T speed high:\s*(\d+)", text)
    producer = re.search(r"Producer:\s*(.+)", text)
    return {
        "blank": blank,
        "erasable": erasable,
        "capacity_sectors": int(lead_out.group(1)) if lead_out else None,
        "speed_low": int(low.group(1)) if low else None,
        "speed_high": int(high.group(1)) if high else None,
        "producer": producer.group(1).strip() if producer else "unknown",
        "raw": text,
    }


def choose_speed(requested: int | None, media: dict) -> int:
    """Pick a write speed the medium actually rates.

    Modern high-speed dye is calibrated for its rated range. Writing below the
    ATIP minimum does not produce a "safer" burn; it produces a worse one, so
    the ATIP floor wins over a lower request.
    """
    low, high = media["speed_low"], media["speed_high"]
    if requested is None:
        return low or 8
    if low and requested < low:
        print(f"  note: requested {requested}x is below this medium's rated "
              f"{low}x floor; using {low}x")
        return low
    if high and requested > high:
        print(f"  note: requested {requested}x is above this medium's rated "
              f"{high}x ceiling; using {high}x")
        return high
    return requested


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Burn a Sega CD image to CD-R for real hardware.")
    parser.add_argument("image", type=Path, help="Mode1/2048 .iso to burn")
    parser.add_argument("--device", default="/dev/sr0")
    parser.add_argument("--speed", type=int,
                        help="write speed; clamped to the medium's ATIP range")
    parser.add_argument("--expect-region", choices=sorted(REGION_NAMES),
                        help="fail unless the image targets this console region")
    parser.add_argument("--burn", action="store_true",
                        help="actually write; without it this only reports")
    parser.add_argument("--eject", action="store_true",
                        help="eject when the burn finishes")
    args = parser.parse_args(argv)

    if shutil.which("cdrskin") is None:
        raise SystemExit("cdrskin is not installed (apt install cdrskin)")

    image = inspect_image(args.image)
    print(f"image   : {args.image}")
    print(f"  header: {image['header']}  volume: {image['volume']}")
    print(f"  system: {image['system']}")
    print(f"  name  : {image['name']}")
    print(f"  size  : {image['size']} bytes ({image['sectors']} sectors)")
    print(f"  region: {image['region']} ({image['region_name']})")

    if args.expect_region and image["region"] != args.expect_region:
        raise SystemExit(
            f"image targets region {image['region']!r} but "
            f"--expect-region {args.expect_region!r} was given; a mismatched "
            "security code will not boot and the CD-R would be wasted")

    media = probe_media(args.device)
    print(f"medium  : {args.device}")
    print(f"  blank : {media['blank']}  erasable: {media['erasable']}")
    print(f"  make  : {media['producer']}")
    print(f"  rated : {media['speed_low']}x-{media['speed_high']}x")
    print(f"  space : {media['capacity_sectors']} sectors")

    if not media["blank"]:
        raise SystemExit(
            f"{args.device}: the disc is not blank; this tool only writes a "
            "single-session disc to fresh media")
    if media["capacity_sectors"] and image["sectors"] > media["capacity_sectors"]:
        raise SystemExit(
            f"image needs {image['sectors']} sectors but the medium holds "
            f"{media['capacity_sectors']}")

    speed = choose_speed(args.speed, media)
    command = ["cdrskin", f"dev={args.device}", "-v", f"speed={speed}",
               "-sao", "driveropts=burnfree", str(args.image)]
    if args.eject:
        command.insert(-1, "-eject")

    if not args.burn:
        print()
        print("dry run; nothing was written. To burn, repeat with --burn:")
        print("  " + " ".join(command))
        return 0

    print()
    print(f"burning at {speed}x in SAO, single data track ...")
    result = subprocess.run(command)
    if result.returncode != 0:
        raise SystemExit(f"cdrskin failed with status {result.returncode}")
    print("burn complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
