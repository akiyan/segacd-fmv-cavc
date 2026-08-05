#!/usr/bin/env python3
"""Check a YouTube title and description against YOUTUBE.md before uploading.

Every rule here exists because it was violated in practice: a description went
out at 5,122 characters, four titles lost their `eN.pM` suffix to the 100-
character cut, links were duplicated into the Japanese half, and a playback
description named analysis panels that are not on its screen. Prose rules did
not prevent any of that, so they are checked mechanically instead.

The checker never edits the text. It reports every failure at once so one pass
is enough, and exits non-zero when any failure remains.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# YouTube's own limits.
DESCRIPTION_MAX = 5000
DESCRIPTION_TARGET = 4800
TITLE_MAX = 100

# The two halves of a description are separated by this line.
LANGUAGE_SEPARATOR = "----"

PROJECT_URL = "https://github.com/akiyan/segacd-fmv-cavc"
CODEC_NAME = "Sega CD Constraint-Aware Video Codec"

BUILD_VERSION = re.compile(r"\b\d{8}\.e\d+\.p\d+\b")
BUILD_LINE = re.compile(r"^Build:\s*(\d{8}\.e\d+\.p\d+)\s*$", re.MULTILINE)
URL = re.compile(r"https?://\S+")

# Wording that turns a standalone description into a changelog. Matched
# case-insensitively on word boundaries where the term is a word.
CHANGELOG_TERMS = [
    r"\bno longer\b",
    r"\bpreviously\b",
    r"\binstead of before\b",
    r"\bimproved\b",
    r"\bregressed\b",
    r"\bthis version (?:adds|fixes|changes)\b",
    r"\bcompared (?:to|with) the (?:previous|earlier)\b",
    r"以前(?:は|の)",
    r"これまで(?:は|の)",
    r"改善(?:し|さ)",
    r"ようになりました",
    r"なくなりました",
]

# Analysis-only vocabulary. A playback video has none of these on screen.
ANALYSIS_ONLY_TERMS = [
    "category map",
    "category legend",
    "whole-clip totals",
    "timeline",
    "waveform",
    "spectrum",
    "status bar",
    "meters",
    "category map",
    "積層timeline",
    "波形",
]

# Facts every description must carry.
REQUIRED_SUBSTRINGS = [
    (CODEC_NAME, "public codec name"),
    (PROJECT_URL, "project link"),
]
CRAM_PATTERNS = [
    re.compile(r"CRAM\)? switches:\s*\d+", re.IGNORECASE),
    re.compile(r"CRAM\)?\s*switch(?:は)?\s*\d+回"),
]


def split_languages(text: str) -> tuple[str, str]:
    """Return the English and Japanese halves around the separator line."""
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip() == LANGUAGE_SEPARATOR:
            return "\n".join(lines[:index]), "\n".join(lines[index + 1:])
    return text, ""


def check_title(title: str, expected: str | None, failures: list[str],
                notes: list[str]) -> None:
    length = len(title)
    notes.append(f"title characters: {length}/{TITLE_MAX}")
    if length > TITLE_MAX:
        failures.append(
            f"title is {length} characters; YouTube cuts it at {TITLE_MAX}")
    if re.search(r"\bv\d{2,}\b", title):
        failures.append("title carries a sequence version (vNNN)")
    if BUILD_VERSION.search(title):
        failures.append(
            "title carries a build version; it belongs on the description's "
            "closing Build line, not in the title")
    if expected is not None and title.strip() != expected.strip():
        failures.append(
            "title does not match the profile [youtube] title:\n"
            f"        profile: {expected}\n"
            f"        given  : {title}")


def check_description(text: str, kind: str, expected_build: str | None,
                      failures: list[str], warnings: list[str],
                      notes: list[str]) -> None:
    length = len(text)
    notes.append(f"description characters: {length}/{DESCRIPTION_MAX}")
    if length > DESCRIPTION_MAX:
        failures.append(
            f"description is {length} characters; the hard limit is "
            f"{DESCRIPTION_MAX}")
    elif length > DESCRIPTION_TARGET:
        warnings.append(
            f"description is {length} characters, above the {DESCRIPTION_TARGET} "
            "target; shorten explanatory prose")

    for bracket in ("<", ">"):
        if bracket in text:
            failures.append(
                f"description contains {bracket!r}; YouTube rejects it with "
                "invalidDescription (HTTP 400)")

    english, japanese = split_languages(text)
    if not japanese.strip():
        failures.append(
            f"description has no {LANGUAGE_SEPARATOR!r} separator followed by "
            "a Japanese section")

    japanese_urls = URL.findall(japanese)
    if japanese_urls:
        failures.append(
            f"{len(japanese_urls)} URL(s) in the Japanese section; URLs belong "
            f"only to the English section (first: {japanese_urls[0]})")
    notes.append(
        f"URLs: english {len(URL.findall(english))}, japanese "
        f"{len(japanese_urls)}")

    for needle, label in REQUIRED_SUBSTRINGS:
        if needle not in text:
            failures.append(f"description is missing the {label}: {needle}")

    if not any(pattern.search(text) for pattern in CRAM_PATTERNS):
        failures.append(
            "description does not state the CRAM palette switch count")

    build = BUILD_LINE.search(english)
    if not build:
        failures.append(
            "description has no closing 'Build: YYYYMMDD.eN.pM' line in the "
            "English section; the title carries no version, so this line is "
            "the only record of which build the video shows")
    else:
        notes.append(f"build line: {build.group(1)}")
        if english.rstrip().splitlines()[-1].strip() != build.group(0).strip():
            failures.append("the Build line is not the last line of the English section")
        if expected_build is not None and build.group(1) != expected_build:
            failures.append(
                f"Build line says {build.group(1)} but the current build is "
                f"{expected_build}")

    for pattern in CHANGELOG_TERMS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            failures.append(
                f"changelog wording {match.group(0)!r} at offset "
                f"{match.start()}; describe this build absolutely")

    if kind == "playback":
        lowered = text.lower()
        for term in ANALYSIS_ONLY_TERMS:
            if term.lower() in lowered:
                failures.append(
                    f"playback description names the analysis-only element "
                    f"{term!r}, which is not on its screen")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate YouTube upload text against YOUTUBE.md.")
    parser.add_argument("description", type=Path,
                        help="UTF-8 description file to check")
    parser.add_argument("--kind", required=True, choices=("analysis", "playback"),
                        help="which kind of codec video this text belongs to")
    parser.add_argument("--title", help="title string to check as well")
    parser.add_argument("--profile-title",
                        help="expected title from the profile [youtube] section")
    parser.add_argument("--build",
                        help="current build version, e.g. 20260805.e190.p152")
    parser.add_argument("--cross-link",
                        help="URL of the other kind for the same encode; "
                             "required unless --allow-missing-cross-link")
    parser.add_argument("--allow-missing-cross-link", action="store_true",
                        help="skip the cross-link requirement (first upload of "
                             "an encode, before its counterpart exists)")
    args = parser.parse_args(argv)

    if not args.description.is_file():
        parser.error(f"description not found: {args.description}")
    text = args.description.read_text(encoding="utf-8")

    failures: list[str] = []
    warnings: list[str] = []
    notes: list[str] = []

    if args.title is not None:
        check_title(args.title, args.profile_title, failures, notes)
    check_description(text, args.kind, args.build, failures, warnings, notes)

    if args.cross_link:
        if args.cross_link not in text:
            failures.append(
                f"description does not link its counterpart: {args.cross_link}")
    elif not args.allow_missing_cross_link:
        failures.append(
            "no --cross-link given; pass the other kind's URL, or "
            "--allow-missing-cross-link when it does not exist yet")

    for note in notes:
        print(f"  {note}")
    for warning in warnings:
        print(f"WARN  {warning}")
    for failure in failures:
        print(f"FAIL  {failure}")

    verdict = "FAIL" if failures else ("WARN" if warnings else "PASS")
    print(f"youtube description check: {verdict}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
