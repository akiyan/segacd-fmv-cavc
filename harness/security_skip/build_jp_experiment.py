#!/usr/bin/env python3
"""Build an isolated JP security experiment from an existing disc image.

The stock Japanese Mega-CD 2 BIOS compares the first 340 bytes of the security
program byte-for-byte.  The final 16-bit word is deliberately outside that
comparison and is written by the security program into Sub PRG-RAM address
0x0528.  This builder changes only that unchecked word and, when selected, the
code-defined 16-byte disc ID unless an explicit 32-KiB boot image is supplied.

The source ISO is never edited.  Each experiment gets a separate ISO, CUE and
TSV receipt under out/security-skip by default, so normal release/debug builds
cannot be overwritten during iteration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import tempfile
from pathlib import Path


DISC_IDS = {
    "disc": b"SEGADISC        ",
    "boot": b"SEGABOOTDISC    ",
    "data": b"SEGADATADISC    ",
    "system": b"SEGADISCSYSTEM  ",
}
SECURITY_CHECKED_DISC_IDS = {"boot", "system"}
BOOT_IMAGE_SIZE = 0x8000
SECURITY_OFFSET = 0x0200
SECURITY_CHECKED_SIZE = 0x0154
SECURITY_SIZE = 0x0156
SECURITY_TAIL_OFFSET = SECURITY_OFFSET + SECURITY_CHECKED_SIZE
STANDARD_TAIL_WORD = 0x6006
NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def parse_word(value: str) -> int:
    text = value.removeprefix("0x").removeprefix("0X")
    if not re.fullmatch(r"[0-9A-Fa-f]{4}", text):
        raise argparse.ArgumentTypeError(
            "tail word must be exactly four hexadecimal digits, such as 6006"
        )
    return int(text, 16)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_prefix(path: Path, size: int) -> bytes:
    with path.open("rb") as source:
        data = source.read(size)
    if len(data) != size:
        raise SystemExit(f"file is shorter than 0x{size:x} bytes: {path}")
    return data


def validate_boot_image(
    boot: bytes, canonical_security: bytes, *, label: str
) -> None:
    if len(boot) != BOOT_IMAGE_SIZE:
        raise SystemExit(
            f"{label} must be exactly 0x{BOOT_IMAGE_SIZE:x} bytes, "
            f"got 0x{len(boot):x}"
        )
    if boot[:16] not in DISC_IDS.values():
        raise SystemExit(f"{label} does not use a JP BIOS-recognized disc ID")
    candidate = boot[
        SECURITY_OFFSET:SECURITY_OFFSET + SECURITY_CHECKED_SIZE
    ]
    expected = canonical_security[:SECURITY_CHECKED_SIZE]
    if candidate != expected:
        mismatch = next(
            index for index, pair in enumerate(zip(candidate, expected, strict=True))
            if pair[0] != pair[1]
        )
        raise SystemExit(
            f"{label} changes a BIOS-checked security byte at "
            f"security+0x{mismatch:x}"
        )


def write_cue(path: Path, iso_name: str) -> None:
    path.write_text(
        f'FILE "{iso_name}" BINARY\n'
        "  TRACK 01 MODE1/2048\n"
        "    INDEX 01 00:00:00\n",
        encoding="ascii",
        newline="\n",
    )


def write_receipt(
    path: Path,
    *,
    name: str,
    source_iso: Path,
    output_iso: Path,
    source_sha256: str,
    output_sha256: str,
    tail_word: int,
    boot_image: Path | None,
    disc_id: str,
) -> None:
    fields = (
        "experiment",
        "source_iso",
        "output_iso",
        "source_sha256",
        "output_sha256",
        "bios_checked_bytes",
        "unchecked_tail_offset",
        "tail_word",
        "disc_id",
        "security_verifier",
        "boot_image",
    )
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(
            output, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerow(
            {
                "experiment": name,
                "source_iso": str(source_iso.resolve()),
                "output_iso": str(output_iso.resolve()),
                "source_sha256": source_sha256,
                "output_sha256": output_sha256,
                "bios_checked_bytes": SECURITY_CHECKED_SIZE,
                "unchecked_tail_offset": f"0x{SECURITY_TAIL_OFFSET:x}",
                "tail_word": f"0x{tail_word:04x}",
                "disc_id": DISC_IDS[disc_id].decode("ascii"),
                "security_verifier": (
                    "yes" if disc_id in SECURITY_CHECKED_DISC_IDS else "no"
                ),
                "boot_image": "" if boot_image is None else str(boot_image.resolve()),
            }
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_iso", type=Path)
    parser.add_argument(
        "--name",
        required=True,
        help="filesystem-safe experiment name used in isolated output paths",
    )
    parser.add_argument(
        "--tail-word",
        type=parse_word,
        default=STANDARD_TAIL_WORD,
        help="unchecked Sub-CPU patch word (four hex digits; default: 6006)",
    )
    parser.add_argument(
        "--disc-id",
        choices=tuple(DISC_IDS),
        default="system",
        help=(
            "JP BIOS-recognized 16-byte disc ID (default: system); only boot "
            "and system invoke the security verifier"
        ),
    )
    parser.add_argument(
        "--boot-image",
        type=Path,
        help="optional 32-KiB boot image; its BIOS-checked bytes must stay exact",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("out/security-skip"),
    )
    parser.add_argument(
        "--canonical-security",
        type=Path,
        default=Path("boot/sec_jp.bin"),
    )
    args = parser.parse_args()

    if not NAME_RE.fullmatch(args.name):
        raise SystemExit(
            "--name must contain only ASCII letters, digits, dot, underscore "
            "or hyphen, and must start with a letter or digit"
        )
    if not args.source_iso.is_file():
        raise SystemExit(f"source ISO not found: {args.source_iso}")

    canonical = args.canonical_security.read_bytes()
    if len(canonical) != SECURITY_SIZE:
        raise SystemExit(
            f"canonical JP security code must be 0x{SECURITY_SIZE:x} bytes, "
            f"got 0x{len(canonical):x}: {args.canonical_security}"
        )
    if int.from_bytes(canonical[-2:], "big") != STANDARD_TAIL_WORD:
        raise SystemExit(
            "canonical JP security code has an unexpected final word: "
            f"{canonical[-2:].hex()}"
        )

    source_boot = read_prefix(args.source_iso, BOOT_IMAGE_SIZE)
    validate_boot_image(source_boot, canonical, label=str(args.source_iso))

    replacement_boot: bytes | None = None
    if args.boot_image is not None:
        replacement_boot = args.boot_image.read_bytes()
        validate_boot_image(
            replacement_boot, canonical, label=str(args.boot_image)
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{args.source_iso.stem}_jpsec_{args.name}"
    output_iso = args.output_dir / f"{stem}.iso"
    output_cue = args.output_dir / f"{stem}.cue"
    output_receipt = args.output_dir / f"{stem}.tsv"

    source_digest = sha256(args.source_iso)
    temporary_fd, temporary_name = tempfile.mkstemp(
        prefix=f".{stem}.", suffix=".iso.tmp", dir=args.output_dir
    )
    os.close(temporary_fd)
    temporary_iso = Path(temporary_name)
    try:
        shutil.copyfile(args.source_iso, temporary_iso)
        with temporary_iso.open("r+b") as output:
            if replacement_boot is not None:
                output.seek(0)
                output.write(replacement_boot)
            output.seek(0)
            output.write(DISC_IDS[args.disc_id])
            output.seek(SECURITY_TAIL_OFFSET)
            output.write(args.tail_word.to_bytes(2, "big"))
        os.replace(temporary_iso, output_iso)
    finally:
        temporary_iso.unlink(missing_ok=True)

    built_boot = read_prefix(output_iso, BOOT_IMAGE_SIZE)
    validate_boot_image(built_boot, canonical, label=str(output_iso))
    actual_tail = int.from_bytes(
        built_boot[SECURITY_TAIL_OFFSET:SECURITY_TAIL_OFFSET + 2], "big"
    )
    if actual_tail != args.tail_word:
        raise SystemExit(
            f"built tail is 0x{actual_tail:04x}, expected 0x{args.tail_word:04x}"
        )

    output_digest = sha256(output_iso)
    write_cue(output_cue, output_iso.name)
    write_receipt(
        output_receipt,
        name=args.name,
        source_iso=args.source_iso,
        output_iso=output_iso,
        source_sha256=source_digest,
        output_sha256=output_digest,
        tail_word=args.tail_word,
        boot_image=args.boot_image,
        disc_id=args.disc_id,
    )

    print(f"checked_bytes=0x{SECURITY_CHECKED_SIZE:x}")
    print(f"tail_offset=0x{SECURITY_TAIL_OFFSET:x}")
    print(f"tail_word=0x{args.tail_word:04x}")
    print(f"disc_id={DISC_IDS[args.disc_id].decode('ascii')!r}")
    print(
        "security_verifier="
        f"{'yes' if args.disc_id in SECURITY_CHECKED_DISC_IDS else 'no'}"
    )
    print(f"iso={output_iso}")
    print(f"cue={output_cue}")
    print(f"receipt={output_receipt}")


if __name__ == "__main__":
    main()
