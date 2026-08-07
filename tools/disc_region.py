#!/usr/bin/env python3
"""Release regions of a Sega CD disc.

This mirrors `boot/region_<code>.inc` and `boot/sec_<code>.bin` on the Python
side, so the packaging tool and the verification harness read the same values
the assembler wrote. Keep the strings identical to the include files.

The codec's player is NTSC only: its frame pacing, audio sync, and CD deadline
model are all built on a 60 Hz field rate. Europe therefore has a buildable
region but is not a release target.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DiscRegion:
    code: str
    """Lowercase build knob, as in `make SECURITY_REGION=<code>`."""

    tag: str
    """Uppercase name used in artifact and asset filenames."""

    hardware_type: str
    """The 16-byte disc-header field at 0x100."""

    region_field: str
    """The 16-byte disc-header field at 0x1F0."""

    name_en: str
    name_ja: str
    releasable: bool


REGIONS: dict[str, DiscRegion] = {
    "jp": DiscRegion(
        code="jp",
        tag="JP",
        hardware_type="SEGA MEGA DRIVE ",
        region_field="J               ",
        name_en="Japan (Mega-CD, NTSC)",
        name_ja="日本 (メガCD、NTSC)",
        releasable=True,
    ),
    "us": DiscRegion(
        code="us",
        tag="US",
        hardware_type="SEGA GENESIS    ",
        region_field="U               ",
        name_en="North America (Sega CD, NTSC)",
        name_ja="北米 (Sega CD、NTSC)",
        releasable=True,
    ),
    "eu": DiscRegion(
        code="eu",
        tag="EU",
        hardware_type="SEGA MEGA DRIVE ",
        region_field="E               ",
        name_en="Europe (Mega-CD, PAL)",
        name_ja="欧州 (メガCD、PAL)",
        releasable=False,
    ),
}

RELEASE_REGIONS: tuple[str, ...] = tuple(
    code for code, region in REGIONS.items() if region.releasable)

HARDWARE_TYPE_OFFSET = 0x100
REGION_FIELD_OFFSET = 0x1F0
FIELD_LENGTH = 16


def region(code: str) -> DiscRegion:
    key = str(code).strip().lower()
    if key not in REGIONS:
        known = ", ".join(sorted(REGIONS))
        raise KeyError(f"unknown disc region {code!r}; known regions: {known}")
    return REGIONS[key]


def release_region(code: str) -> DiscRegion:
    found = region(code)
    if not found.releasable:
        raise ValueError(
            f"{found.code}: {found.name_en} is not a release target; this "
            "player is NTSC only")
    return found


def suffix(code: str) -> str:
    """Artifact-name suffix. Japan keeps the plain, unsuffixed name."""

    found = region(code)
    return "" if found.code == "jp" else f"_{found.code}"
