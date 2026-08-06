#!/usr/bin/env python3
"""Manifest and generated-data helpers for the separate multi-video build.

The normal disc build remains one specialized player per profile.  A
multi-video disc gives each of those players a short ISO filename prefix and
uses this module to generate the menu and launcher include files around them.
"""
from __future__ import annotations

import dataclasses
import re
import tomllib
from pathlib import Path
from typing import Iterable, Sequence


SCHEMA_VERSION = 1
MAX_VIDEOS = 10_000
ASCII_MIN = 32
ASCII_MAX = 126
MENU_LINE_WIDTH = 36
MENU_DETAIL_WIDTH = 38


@dataclasses.dataclass(frozen=True)
class MenuVideo:
    index: int
    profile: Path
    title: str

    @property
    def prefix(self) -> str:
        return f"V{self.index:04d}"

    @property
    def header_name(self) -> str:
        return f"{self.prefix}HDR.DAT"

    @property
    def body_name(self) -> str:
        return f"{self.prefix}BOD.DAT"

    @property
    def ip_name(self) -> str:
        return f"{self.prefix}IP.BIN"

    @property
    def sp_name(self) -> str:
        return f"{self.prefix}SP.BIN"


@dataclasses.dataclass(frozen=True)
class MenuManifest:
    path: Path
    title: str
    subtitle: str
    output_stem: str
    videos: tuple[MenuVideo, ...]


@dataclasses.dataclass(frozen=True)
class BuiltVideo:
    video: MenuVideo
    frames: int
    tcols: int
    trows: int
    fps: int
    header_bytes: int
    body_bytes: int
    ip_bytes: int
    sp_bytes: int

    @property
    def total_bytes(self) -> int:
        return self.header_bytes + self.body_bytes

    @property
    def duration_seconds(self) -> float:
        return self.frames / self.fps

    @property
    def list_text(self) -> str:
        return self.video.title

    @property
    def detail_title(self) -> str:
        return self.video.title

    @property
    def detail_specs(self) -> str:
        return f"H40 {self.tcols * 8}x{self.trows * 8}  {self.tcols}x{self.trows} tiles"

    @property
    def detail_timing(self) -> str:
        duration = f"{self.duration_seconds:.1f}s"
        megabytes = f"{self.total_bytes / 1_000_000:.1f}MB"
        return f"{self.fps}fps ADPCM22 {duration} {self.frames}fr {megabytes}"


def _validate_ascii(value: object, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty ASCII string")
    if len(value) > maximum:
        raise ValueError(f"{field} is {len(value)} characters; maximum is {maximum}")
    unsupported = sorted({char for char in value
                          if not ASCII_MIN <= ord(char) <= ASCII_MAX})
    if unsupported:
        rendered = ", ".join(repr(char) for char in unsupported)
        raise ValueError(f"{field} contains unsupported ASCII characters: {rendered}")
    return value


def _validate_stem(value: object, field: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise ValueError(
            f"{field} must match [A-Za-z0-9][A-Za-z0-9._-]*")
    return value


def load_manifest(path: str | Path) -> MenuManifest:
    """Load and validate one multi-video menu manifest."""
    manifest_path = Path(path).resolve()
    try:
        data = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"menu manifest does not exist: {manifest_path}") from exc
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(
            f"menu schema_version must be {SCHEMA_VERSION}")
    menu = data.get("menu")
    if not isinstance(menu, dict):
        raise ValueError("menu manifest requires a [menu] table")
    title = _validate_ascii(
        menu.get("title", "SCFMV VIDEO SELECT"), "menu.title", 38)
    subtitle = _validate_ascii(
        menu.get("subtitle", "SELECT A MOVIE"), "menu.subtitle", 38)
    output_stem = _validate_stem(
        menu.get("output", manifest_path.stem), "menu.output")

    raw_videos = data.get("videos")
    if not isinstance(raw_videos, list) or not raw_videos:
        raise ValueError("menu manifest requires at least one [[videos]] entry")
    if len(raw_videos) > MAX_VIDEOS:
        raise ValueError(f"menu manifest has more than {MAX_VIDEOS} videos")
    videos: list[MenuVideo] = []
    for index, raw in enumerate(raw_videos):
        if not isinstance(raw, dict):
            raise ValueError(f"videos[{index}] must be a table")
        profile_value = raw.get("profile")
        if not isinstance(profile_value, str) or not profile_value:
            raise ValueError(f"videos[{index}].profile is required")
        profile = (manifest_path.parent / profile_value).resolve()
        if not profile.is_file():
            raise ValueError(f"videos[{index}].profile does not exist: {profile}")
        title_value = raw.get("title", profile.stem)
        title_value = _validate_ascii(title_value, f"videos[{index}].title", MENU_LINE_WIDTH)
        videos.append(MenuVideo(index=index, profile=profile, title=title_value))
    return MenuManifest(
        path=manifest_path,
        title=title,
        subtitle=subtitle,
        output_stem=output_stem,
        videos=tuple(videos),
    )


def _asm_bytes(label: str, value: bytes, width: int = 16) -> list[str]:
    lines = [f"{label}:"]
    for offset in range(0, len(value), width):
        chunk = value[offset:offset + width]
        values = ",".join(f"0x{byte:02X}" for byte in chunk)
        lines.append(f"\t.byte\t{values}")
    return lines


def _asm_string(label: str, value: str) -> list[str]:
    return _asm_bytes(label, value.encode("ascii") + b"\0")


def _asm_long_table(label: str, entries: Iterable[str]) -> list[str]:
    values = list(entries)
    lines = ["\t.align\t2", f"{label}:"]
    if values:
        lines.append("\t.long\t" + ",".join(values))
    return lines


def _asm_word_table(label: str, values: Iterable[int]) -> list[str]:
    numbers = list(values)
    lines = ["\t.align\t2", f"{label}:"]
    if numbers:
        lines.append("\t.word\t" + ",".join(f"0x{value:04X}" for value in numbers))
    return lines


def render_menu_include(manifest: MenuManifest, built: Sequence[BuiltVideo]) -> str:
    """Render menu text, metadata, and IP-size tables for Main."""
    if len(built) != len(manifest.videos):
        raise ValueError("built video count does not match menu manifest")
    for item in built:
        for field, value, maximum in (
                ("title", item.list_text, MENU_LINE_WIDTH),
                ("detail_title", item.detail_title, MENU_DETAIL_WIDTH),
                ("detail_specs", item.detail_specs, MENU_DETAIL_WIDTH),
                ("detail_timing", item.detail_timing, MENU_DETAIL_WIDTH)):
            if len(value) > maximum:
                raise ValueError(
                    f"video {item.video.index} {field} is {len(value)} characters; "
                    f"maximum is {maximum}")
    lines = [
        "/* Generated by tools/multimovie.py. Do not edit. */",
        f".equ MENU_COUNT, {len(built)}",
        f".equ MENU_LIST_WIDTH, {MENU_LINE_WIDTH}",
        "",
        "\t.data",
    ]
    lines += _asm_string("menu_title", manifest.title)
    lines += _asm_string("menu_subtitle", manifest.subtitle)
    lines += _asm_long_table(
        "menu_list_ptrs",
        (f"menu_list_{item.video.index}" for item in built))
    lines += _asm_long_table(
        "menu_detail_title_ptrs",
        (f"menu_detail_title_{item.video.index}" for item in built))
    lines += _asm_long_table(
        "menu_detail_specs_ptrs",
        (f"menu_detail_specs_{item.video.index}" for item in built))
    lines += _asm_long_table(
        "menu_detail_timing_ptrs",
        (f"menu_detail_timing_{item.video.index}" for item in built))
    lines += _asm_word_table("menu_ip_sizes", (item.ip_bytes for item in built))
    lines.append("")
    for item in built:
        lines += _asm_string(f"menu_list_{item.video.index}", item.list_text)
        lines += _asm_string(
            f"menu_detail_title_{item.video.index}", item.detail_title)
        lines += _asm_string(
            f"menu_detail_specs_{item.video.index}", item.detail_specs)
        lines += _asm_string(
            f"menu_detail_timing_{item.video.index}", item.detail_timing)
    lines.append("")
    return "\n".join(lines)


def render_player_include(video: MenuVideo) -> str:
    """Render constants for one resident-SP player module."""
    def asm_file(label: str, name: str) -> list[str]:
        return _asm_string(label, name)

    lines = [
        "/* Generated by tools/multimovie.py. Do not edit. */",
        ".equ MULTI_MENU, 1",
        ".equ MULTI_MENU_IP_BYTES, 0x5000",
        ".equ MULTI_MENU_IP_SECTORS, 10",
        ".equ MULTI_MENU_SP_SECTORS, 3",
        ".equ MULTI_PLAYER_SP_BASE, 0x00006000",
        ".equ MULTI_MENU_IMAGE_OFF, 0x00000000",
        ".equ MULTI_PLAYER_IP_STAGE_OFF, 0x00005000",
        ".equ MULTI_MENU_WORD_OFF, 0x0001E000",
        ".equ MULTI_MENU_WORD_ENTRY, 0x000DE000",
        ".equ MULTI_PLAYER_BSS_BASE, 0x00FF6700",
        ".equ MULTI_PLAYER_BSS_BYTES, 0x2100",
        ".equ MULTI_MENU_INFO_ADDR, 0x00007F20",
        ".equ MULTI_LOOP_FLAG_ADDR, 0x00007F40",
        ".equ MULTI_LOOP_FLAG_MAIN, 0x00FFB1F0",
        ".equ MULTI_RESTORE_CODE_ADDR, 0x00FF8880",
        ".equ MULTI_STAT_MENU_READY, 0x8005",
        ".equ MULTI_STAT_MENU_IP_READY, 0x8006",
        ".equ MULTI_STAT_PLAYER_READY, 0x8007",
        ".equ MULTI_CMD_MENU_LOAD, 0x0052",
        "",
        "\t.data",
    ]
    lines.append("")
    return "\n".join(lines)


def render_launcher_include(manifest: MenuManifest) -> str:
    """Render file-name tables for the resident Sub launcher."""
    lines = [
        "/* Generated by tools/multimovie.py. Do not edit. */",
        f".equ MENU_COUNT, {len(manifest.videos)}",
        ".equ MENU_IP_IMAGE_BYTES, 0x5000",
        ".equ MENU_IP_IMAGE_SECTORS, 10",
        ".equ MENU_SP_WORD_SECTORS, 3",
        ".equ MENU_IMAGE_OFF, 0x00000000",
        ".equ PLAYER_IP_STAGE_OFF, 0x00005000",
        ".equ MENU_SP_WORD_OFF, 0x0001E000",
        ".equ MENU_SP_WORD_ENTRY, 0x000DE000",
        ".equ MULTI_MENU_INFO_ADDR, 0x00007F20",
        ".equ MULTI_SELECTED_SP_INFO_ADDR, 0x00007F42",
        ".equ MULTI_WORD_SWAP_STUB, 0x00007F50",
        ".equ MULTI_MENU_RUNTIME_ADDR, 0x00007F70",
        ".equ PLAYER_SP_BASE, 0x00006000",
        ".equ MULTI_PLAYER_ENTRY, 0x00006040",
        ".equ MULTI_LOOP_FLAG_ADDR, 0x00007F40",
        ".equ CMD_MENU_LOAD, 0x0052",
        ".equ STAT_MENU_READY, 0x8005",
        ".equ STAT_MENU_IP_READY, 0x8006",
        ".equ STAT_PLAYER_READY, 0x8007",
        "",
        "\t.data",
    ]
    lines += _asm_string("menu_ip_file", "MENUIP.BIN")
    lines += _asm_string("menu_sp_file", "MENUSP.BIN")
    lines += _asm_long_table(
        "menu_player_ip_names",
        (f"menu_player_ip_name_{item.index}" for item in manifest.videos))
    lines += _asm_long_table(
        "menu_player_sp_names",
        (f"menu_player_sp_name_{item.index}" for item in manifest.videos))
    lines += _asm_long_table(
        "menu_player_header_names",
        (f"menu_player_header_name_{item.index}" for item in manifest.videos))
    lines += _asm_long_table(
        "menu_player_body_names",
        (f"menu_player_body_name_{item.index}" for item in manifest.videos))
    lines.append("")
    for item in manifest.videos:
        lines += _asm_string(f"menu_player_ip_name_{item.index}", item.ip_name)
        lines += _asm_string(f"menu_player_sp_name_{item.index}", item.sp_name)
        lines += _asm_string(
            f"menu_player_header_name_{item.index}", item.header_name)
        lines += _asm_string(
            f"menu_player_body_name_{item.index}", item.body_name)
    lines.append("")
    return "\n".join(lines)


def render_manifest_summary(manifest: MenuManifest) -> str:
    """Return a stable human-readable summary used by build logs and tests."""
    return "\n".join(
        [f"{manifest.title} ({len(manifest.videos)} videos)"]
        + [f"{item.index}: {item.title} -> {item.prefix}"
           for item in manifest.videos]
    )


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--print-stem", action="store_true")
    parser.add_argument("--print-summary", action="store_true")
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    if args.print_stem:
        print(manifest.output_stem)
    elif args.print_summary:
        print(render_manifest_summary(manifest))
    else:
        print(render_manifest_summary(manifest))


if __name__ == "__main__":
    main()
