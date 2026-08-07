#!/usr/bin/env python3
"""Render a YouTube description from a checked-in template.

Descriptions used to be written by hand for every upload, against prose rules.
That produced a steady stream of avoidable defects: an over-limit description,
stale buffer counts, a wrong dictionary size, internal build vocabulary, and
links duplicated into the Japanese half. The wording now lives in
``templates/youtube/`` and only the per-video values are substituted, so a
description cannot drift from the agreed text and a number cannot be
mistyped: every one is read from the encode that produced the video.

Every placeholder must resolve. An unknown or missing one is an error rather
than an empty string, because a silently blank spec line reads as if the value
were zero.
"""

from __future__ import annotations

import argparse
import csv
import pickle
import re
import string
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import encode_config  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates" / "youtube"
VERSION_FILE = Path(__file__).resolve().parent / "av_version.txt"
CD_1X_BYTES = 153600
EMULATOR = "Genesis Plus GX"

# Placeholders each kind needs from the caller rather than from the encode.
URL_FIELDS = {
    "analysis": ("timeline_url", "playback_url"),
    "playback": ("analysis_url",),
    "verification": (),
    # The comparison video's wording and its links are per-source, so both come
    # from the profile's [comparison.youtube] rather than from a shared
    # template and from the command line.
    "comparison": (),
}


class StrictFormatter(string.Formatter):
    """A formatter that refuses to leave a placeholder unresolved."""

    def get_value(self, key, args, kwargs):
        if isinstance(key, str) and key not in kwargs:
            raise KeyError(key)
        return super().get_value(key, args, kwargs)


def build_version() -> str:
    values = {}
    for line in VERSION_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith(("date=", "e=", "p=")):
            name, _, value = line.partition("=")
            values[name] = value.strip()
    missing = {"date", "e", "p"} - set(values)
    if missing:
        raise SystemExit(f"{VERSION_FILE}: missing {sorted(missing)}")
    return f"{values['date']}.e{values['e']}.p{values['p']}"


def encoder_change_note() -> str:
    """Return the current encoder version's own history entry, verbatim.

    A verification upload records what the build changed. Reading it from
    av_version.txt keeps that text identical to the repository's own record
    instead of a paraphrase written at upload time.
    """
    lines = VERSION_FILE.read_text(encoding="utf-8").splitlines()
    version = build_version().split(".e")[1].split(".p")[0]
    head = f"#   e{version}:"
    try:
        start = next(i for i, line in enumerate(lines) if line.startswith(head))
    except StopIteration:
        raise SystemExit(f"{VERSION_FILE}: no history entry for e{version}")
    collected = []
    for line in lines[start:]:
        if not line.startswith("#"):
            break
        if collected and re.match(r"^#\s+[ep]\d+:", line):
            break
        collected.append(re.sub(r"^#\s{0,9}", "", line))
    return "\n".join(collected).replace(f"e{version}: ", "", 1)


def comparison_template(profile) -> str:
    """Assemble the comparison video's template from its profile section.

    The comparison frame's own wording already lives in [comparison]; its
    upload text does too, so one video's text sits in one place. Only the prose
    is stored - every figure stays a placeholder resolved from the encode. The
    links are a table, so they are emitted in the order they were written, at
    the end of the English half where YOUTUBE.md requires every URL to sit, and
    the mandatory build line closes that half.
    """
    data = profile.section("comparison").get("youtube")
    if not isinstance(data, dict):
        raise SystemExit(f"{profile.path}: no [comparison.youtube] section")
    missing = {"description_en", "description_ja"} - set(data)
    if missing:
        raise SystemExit(f"{profile.path}: [comparison.youtube] missing "
                         f"{', '.join(sorted(missing))}")
    links = data.get("links")
    if not isinstance(links, dict) or not links:
        raise SystemExit(f"{profile.path}: [comparison.youtube.links] must "
                         f"have at least the project link")
    link_lines = "\n".join(f"{label}: {url}" for label, url in links.items())
    english = data["description_en"].strip()
    japanese = data["description_ja"].strip()
    return f"{english}\n\n{link_lines}\nBuild: {{build}}\n\n----\n\n{japanese}\n"


def cram_counts(sim_out: Path) -> tuple[int, int]:
    decisions = pickle.loads((sim_out / "decisions.pkl").read_bytes())
    segments = len(set(int(v) for v in decisions["frame_seg"]))
    return segments, segments - 1


def band_kib(timeline_tsv: Path) -> int:
    """Mean useful BODY delivery, the value the analysis Band meter shows."""
    useful = physical = 0
    with timeline_tsv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if int(row["frame"]) == 0:
                continue
            useful += int(row["body_useful_bytes"])
            physical += int(row["body_physical_bytes"])
    if not physical:
        raise SystemExit(f"{timeline_tsv}: no timed BODY bytes")
    return round(useful / (physical / CD_1X_BYTES) / 1024)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Render a YouTube description from templates/youtube/.")
    parser.add_argument("--config", required=True, type=Path,
                        help="encode profile TOML")
    parser.add_argument("--kind", required=True,
                        choices=sorted(URL_FIELDS), help="which video")
    parser.add_argument("--timeline-tsv", type=Path,
                        help="analysis TSV, required for analysis/playback")
    parser.add_argument("--analysis-url")
    parser.add_argument("--playback-url")
    parser.add_argument("--timeline-url")
    parser.add_argument("--output", type=Path, help="write here instead of stdout")
    args = parser.parse_args(argv)

    profile = encode_config.load_profile(args.config)
    if args.kind == "comparison":
        template_text = comparison_template(profile)
        template_name = f"{args.config}: [comparison.youtube]"
    else:
        template = TEMPLATE_DIR / f"{args.kind}.txt"
        if not template.is_file():
            raise SystemExit(f"template not found: {template}")
        template_text = template.read_text(encoding="utf-8")
        template_name = str(template)

    values = {"build": build_version(), "emulator": EMULATOR}

    if args.kind == "verification":
        values["change_note"] = encoder_change_note()
    else:
        video = profile.section("video")
        width, height = int(video["width"]), int(video["height"])
        cols, rows = width // 8, height // 8
        segments, switches = cram_counts(profile.output_dir)
        if args.timeline_tsv is None:
            raise SystemExit(f"--timeline-tsv is required for --kind {args.kind}")
        for name, value in (("source_label", profile.source_label),
                            ("source_label_ja", profile.source_label_ja)):
            if not value:
                raise SystemExit(
                    f"{args.config}: [youtube] {name} is required for "
                    f"--kind {args.kind}")
            values[name] = value
        # Where the master came from. The citation is a URL, so it sits in the
        # English half only, on its own line: a URL with a sentence's full stop
        # glued to it is one character away from being the wrong link. A
        # profile with no [youtube] source_url keeps the plain sentence.
        source_url = (profile.section("youtube") or {}).get("source_url", "")
        # A master offered under a licence that asks for a credit carries that
        # credit in both halves, because the notice is part of what the licence
        # grants the film in return. Only the terms link is English-only, for
        # the same reason every other URL is, and it likewise stands on its own
        # line.
        licence = profile.source_license
        values["source_line"] = (
            f"Source: {values['source_label']}."
            + (f"\nSource video: {source_url}" if source_url else "")
            + (f"\nLicense: {licence}"
               f"\nLicense terms: {profile.source_license_url}"
               if licence else ""))
        values["source_line_ja"] = (
            f"Source: {values['source_label_ja']}。"
            + (f"\nLicense: {profile.source_license_ja}" if licence else ""))
        values.update(
            width=width, height=height, cols=cols, rows=rows,
            cells=cols * rows,
            fps=str(profile.section("source")["fps"]),
            cram_segments=segments, cram_switches=switches,
            band=band_kib(args.timeline_tsv),
        )

    for field in URL_FIELDS[args.kind]:
        value = getattr(args, field.replace("_url", "") + "_url")
        if not value:
            raise SystemExit(f"--{field.replace('_', '-')} is required for "
                             f"--kind {args.kind}")
        values[field] = value

    try:
        text = StrictFormatter().vformat(template_text, (), values)
    except KeyError as exc:
        raise SystemExit(
            f"{template_name}: no value for placeholder "
            f"{exc.args[0]!r}") from exc

    if args.output:
        args.output.write_text(text, encoding="utf-8")
        print(f"{args.output} ({len(text)} characters)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
