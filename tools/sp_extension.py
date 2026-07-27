#!/usr/bin/env python3
"""Generate and verify the HEADER-preloaded Sub player extension contract."""

from __future__ import annotations

import argparse
import dataclasses
import re
import zlib
from pathlib import Path

import av_config


@dataclasses.dataclass(frozen=True)
class ExtensionMetadata:
    load_base: int
    exec_base: int
    size: int
    longs: int
    crc32: int


def metadata(binary: bytes) -> ExtensionMetadata:
    """Return the checked load/execute contract for one extension binary."""
    size = len(binary)
    if size <= 0:
        raise ValueError("Sub extension binary is empty")
    if size & 3:
        raise ValueError(
            f"Sub extension size must be a multiple of four bytes, got {size}")
    if size > av_config.SUB_BOOT_EXTENSION_MAX_BYTES:
        raise ValueError(
            f"Sub extension is {size} bytes, exceeds marker-verified capacity "
            f"{av_config.SUB_BOOT_EXTENSION_MAX_BYTES}")
    return ExtensionMetadata(
        load_base=av_config.SUB_BOOT_EXTENSION_LOAD_BASE,
        exec_base=av_config.SUB_BOOT_EXTENSION_EXEC_BASE,
        size=size,
        longs=size // 4,
        crc32=zlib.crc32(binary) & 0xFFFFFFFF,
    )


def adpcm_preload_image(
        table: bytes, binary: bytes, sector_bytes: int = 2048) -> bytes:
    """Embed extension code after the table in its existing sector padding."""
    if sector_bytes <= 0:
        raise ValueError(f"sector size must be positive, got {sector_bytes}")
    values = metadata(binary)
    table_bytes = bytes(table)
    capacity = (
        (len(table_bytes) + sector_bytes - 1) // sector_bytes
    ) * sector_bytes
    if len(table_bytes) + values.size > capacity:
        raise ValueError(
            f"Sub extension needs {values.size} bytes but the ADPCM preload "
            f"has only {capacity - len(table_bytes)} padding bytes")
    return (table_bytes + binary).ljust(capacity, b"\0")


def render_include(values: ExtensionMetadata) -> str:
    """Render constants consumed by the resident Sub base image."""
    def runtime_address(offset: int) -> str:
        address = av_config.SUB_RUNTIME_DIAG_BASE + offset
        return f"0x{address:08X}"

    return "\n".join((
        "/* Generated from movieplay_sp_ext.bin. Do not edit. */",
        f".equ SP_EXTENSION_LOAD_BASE, 0x{values.load_base:08X}",
        f".equ SP_EXTENSION_EXEC_BASE, 0x{values.exec_base:08X}",
        f".equ SP_EXTENSION_BYTES, 0x{values.size:04X}",
        f".equ SP_EXTENSION_LONGS, 0x{values.longs:04X}",
        f".equ SP_EXTENSION_CRC32, 0x{values.crc32:08X}",
        f".equ SP_RUNTIME_DIAG_BASE, 0x{av_config.SUB_RUNTIME_DIAG_BASE:08X}",
        ".equ SP_RUNTIME_DIAG_SAMPLE, "
        f"{runtime_address(av_config.SUB_RUNTIME_DIAG_SAMPLE_OFFSET)}",
        ".equ SP_RUNTIME_DIAG_RESET, "
        f"{runtime_address(av_config.SUB_RUNTIME_DIAG_RESET_OFFSET)}",
        ".equ SP_RUNTIME_DIAG_FRAME_START, "
        f"{runtime_address(av_config.SUB_RUNTIME_DIAG_FRAME_START_OFFSET)}",
        ".equ SP_RUNTIME_DIAG_GET, "
        f"{runtime_address(av_config.SUB_RUNTIME_DIAG_GET_OFFSET)}",
        ".equ SP_RUNTIME_DIAG_LAST, "
        f"{runtime_address(av_config.SUB_RUNTIME_DIAG_LAST_OFFSET)}",
        ".equ SP_RUNTIME_DIAG_MAX, "
        f"{runtime_address(av_config.SUB_RUNTIME_DIAG_MAX_OFFSET)}",
        f".equ SP_RUNTIME_DIAG_BYTES, 0x{av_config.SUB_RUNTIME_DIAG_BYTES:04X}",
        "",
    ))


def parse_include(text: str) -> ExtensionMetadata:
    """Parse a generated include for independent build-time verification."""
    values: dict[str, int] = {}
    for name in (
            "LOAD_BASE", "EXEC_BASE", "BYTES", "LONGS", "CRC32"):
        match = re.search(
            rf"^\.equ SP_EXTENSION_{name},\s*(0x[0-9A-Fa-f]+|\d+)\s*$",
            text,
            re.MULTILINE,
        )
        if not match:
            raise ValueError(f"missing SP_EXTENSION_{name}")
        values[name] = int(match.group(1), 0)
    return ExtensionMetadata(
        load_base=values["LOAD_BASE"],
        exec_base=values["EXEC_BASE"],
        size=values["BYTES"],
        longs=values["LONGS"],
        crc32=values["CRC32"],
    )


def generate(binary_path: Path, output_path: Path) -> ExtensionMetadata:
    """Write a stable include and return the verified binary metadata."""
    values = metadata(binary_path.read_bytes())
    rendered = render_include(values)
    if not output_path.is_file() or output_path.read_text() != rendered:
        output_path.write_text(rendered)
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("binary", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    values = generate(args.binary, args.output)
    print(
        f"sp_extension: {args.output} preload=0x{values.load_base:05X} "
        f"exec=0x{values.exec_base:05X} bytes={values.size} "
        f"crc32=0x{values.crc32:08X}")


if __name__ == "__main__":
    main()
