#!/usr/bin/env python3
"""Build per-region disc images and publish them as a GitHub release.

One build produces one release, holding every title packaged with it. Each
title gets one zip per region, and a zip holds that region's disc image, its
cue sheet, and a README written for whoever downloads it. Nothing about a
particular title lives here: every name, credit and figure is read from the
profile TOML, the packed stream, and ``tools/av_version.txt``.

Two stages, kept apart on purpose:

``build``    assembles the discs and the zips. Local, repeatable, no network.
``publish``  hands the zips to GitHub. It creates a draft by default, because
             publishing is outward-facing and should be a deliberate step.

Usage::

    tools/python.sh tools/region_release.py build \\
        --config profiles/bad-apple.toml --config profiles/tears-of-steel.toml
    tools/python.sh tools/region_release.py publish \\
        --config profiles/bad-apple.toml --config profiles/tears-of-steel.toml \\
        --zip out/releases/....zip --zip ...
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import disc_region
from analysis_logs import av_versions
from encode_config import EncodeProfile, load_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RELEASE_DIR = PROJECT_ROOT / "out" / "releases"
PROJECT_URL = "https://github.com/akiyan/segacd-fmv-cavc"

# A .txt read on Windows straight out of a zip. CRLF costs nothing anywhere
# else and keeps that reader from seeing one run-on line.
README_NEWLINE = "\r\n"

# Fixed by the on-disc layout rather than by the profile.
AUDIO_FORMAT_EN = "22.05 kHz mono IMA ADPCM, decoded by the Sub CPU"
AUDIO_FORMAT_JA = "22.05 kHz モノラル IMA ADPCM、Sub CPU がデコード"
APERTURE = "320x224"


def _run(command: list[str], **kwargs) -> subprocess.CompletedProcess:
    print("+ " + " ".join(command), flush=True)
    return subprocess.run(command, check=True, **kwargs)


def _version_tag() -> str:
    encoder, player = av_versions()
    return f"{encoder}.{player}"


def _build_date(value: str | None) -> str:
    if not value:
        return date.today().strftime("%Y%m%d")
    parsed = datetime.strptime(value, "%Y%m%d")
    return parsed.strftime("%Y%m%d")


def _mib(path: Path) -> str:
    return f"{path.stat().st_size / (1024 * 1024):.1f}"


def asset_stem(profile: EncodeProfile, region_code: str, build_date: str) -> str:
    """`<profile>_<CONSOLE>_<REGION>_<date>.e<N>.p<M>`, the zip's own name."""

    return f"{disc_stem(profile, region_code)}_{build_date}.{_version_tag()}"


def disc_stem(profile: EncodeProfile, region_code: str) -> str:
    """`<profile-stem>_<CONSOLE>_<REGION>`, the names used inside the zip.

    The console is named because Sega sold the same machine as the Mega-CD and
    as the Sega CD, and a file sitting in a downloads folder should say which
    one it is for before it is opened.
    """

    region = disc_region.release_region(region_code)
    return f"{profile.artifact_stem}_{region.console}_{region.tag}"


def release_tag(build_date: str) -> str:
    """One release per build, not one per title.

    Every title packaged on the same day at the same encoder/player version
    belongs on one page, so the tag names the build rather than a profile.
    """

    return f"disc-{build_date}.{_version_tag()}"


def build_disc(profile: EncodeProfile, region_code: str) -> Path:
    """Build one region's release disc and return its ISO path.

    Regions of one profile share an output stem lock, so callers must build
    them one after another rather than at the same time.
    """

    region = disc_region.release_region(region_code)
    _run([
        "make", "disc",
        f"CONFIG={profile.path}",
        "DEBUG=0",
        f"SECURITY_REGION={region.code}",
    ], cwd=PROJECT_ROOT)
    iso = PROJECT_ROOT / profile.region_release_disc_iso(region.code)
    if not iso.is_file():
        raise SystemExit(f"{iso}: the build did not produce a disc image")
    return iso


def readme_text(
    profile: EncodeProfile,
    region_code: str,
    iso: Path,
    build_date: str,
) -> str:
    region = disc_region.release_region(region_code)
    encoder, player = av_versions()
    video = profile.data["video"]
    width = int(video["width"])
    height = int(video["height"])
    fps = str(profile.data["source"]["fps"])
    names = disc_stem(profile, region_code)
    size = _mib(iso)
    fit = "filling" if width == 320 and height == 224 else "centered in"
    fit_ja = ("いっぱいに表示" if width == 320 and height == 224
              else "の中央に配置")

    source_lines = []
    if profile.source_label:
        source_lines.append(profile.source_label)
    if profile.source_url:
        source_lines.append(profile.source_url)
    source_lines_ja = []
    if profile.source_label_ja or profile.source_label:
        source_lines_ja.append(profile.source_label_ja or profile.source_label)
    if profile.source_url:
        source_lines_ja.append(profile.source_url)

    def block(label: str, lines: list[str]) -> list[str]:
        if not lines:
            return []
        out = [f"{label}{lines[0]}"]
        pad = " " * len(label)
        out.extend(f"{pad}{line}" for line in lines[1:])
        return out

    english = [
        "Sega CD Constraint-Aware Video Codec",
        profile.release_title,
        "",
        f"Region      : {region.name_en}",
        f"Disc image  : {names}.iso  ({size} MiB, ISO 9660, "
        "Mode1/2048, one data track)",
        f"Cue sheet   : {names}.cue",
        f"Video       : {width}x{height} {fit} the {APERTURE} H40 screen, "
        f"{fps} fps",
        f"Audio       : {AUDIO_FORMAT_EN}",
        f"Build       : encoder {encoder}, player {player}, "
        f"packaged {build_date}",
    ]
    english += block("Source      : ", source_lines)
    english += [
        "",
        "NTSC only. This player's frame pacing, audio sync and CD delivery",
        "deadlines are all built on a 60 Hz field rate, so the disc is not",
        "made for a 50 Hz PAL console.",
        "",
        "Use the image whose region matches your console. A console checks the",
        "region's security code on the disc and refuses the other one.",
        "",
        "In an emulator",
        "  Open the .cue file. It names the .iso beside it, so keep both files",
        "  together in one directory.",
        "",
        "On real hardware",
        "  Burn the .iso as a single Disc-At-Once session with one data track.",
        "  Track-At-Once leaves a pregap that an early-1990s Sega CD drive can",
        "  fail to read past. The .cue is not needed for the burn.",
        "  A Sega CD pickup was built for pressed discs, which reflect more",
        "  light than any CD-R, so the brand and dye of the blank genuinely",
        "  change whether a console boots it. If one blank does not work, a",
        "  different one may.",
        "",
        PROJECT_URL,
    ]

    japanese = [
        "Sega CD Constraint-Aware Video Codec",
        profile.release_title_ja,
        "",
        f"リージョン    : {region.name_ja}",
        f"ディスク      : {names}.iso  ({size} MiB、ISO 9660、"
        "Mode1/2048、データトラック 1 本)",
        f"cue シート    : {names}.cue",
        f"映像          : {width}x{height}、{APERTURE} の H40 画面"
        f"{fit_ja}、{fps} fps",
        f"音声          : {AUDIO_FORMAT_JA}",
        f"ビルド        : encoder {encoder}、player {player}、"
        f"パッケージ {build_date}",
    ]
    japanese += block("出典          : ", source_lines_ja)
    japanese += [
        "",
        "NTSC 専用です。このプレイヤーのフレーム進行、音声同期、CD の配送期限は",
        "すべて 60 Hz を前提に組んであります。50 Hz の PAL 実機向けではありません。",
        "",
        "お使いの本体に合うリージョンのイメージを選んでください。本体はディスク上の",
        "セキュリティコードを確認し、合わないほうは起動しません。",
        "",
        "エミュレータで再生する",
        "  .cue を開いてください。同じ場所にある .iso を参照するので、2 つのファイルは",
        "  同じディレクトリに置いたままにしてください。",
        "",
        "実機で再生する",
        "  .iso をデータトラック 1 本の Disc-At-Once・シングルセッションで焼いてください。",
        "  Track-At-Once はプリギャップが残り、1990 年代前半の Sega CD のドライブが",
        "  その先を読めないことがあります。焼くときに .cue は不要です。",
        "  Sega CD のピックアップはプレスディスク向けで、CD-R はそれより反射率が低い",
        "  ため、ブランクメディアの銘柄や色素で起動可否が実際に変わります。あるメディア",
        "  で起動しなくても、別のメディアなら起動することがあります。",
        "",
        PROJECT_URL,
    ]

    lines = english + ["", "-" * 72, ""] + japanese
    return README_NEWLINE.join(lines) + README_NEWLINE


def cue_text(names: str) -> str:
    return (f'FILE "{names}.iso" BINARY\n'
            "  TRACK 01 MODE1/2048\n"
            "    INDEX 01 00:00:00\n")


def write_zip(
    zip_path: Path,
    members: list[tuple[str, Path | bytes]],
    build_date: str,
) -> None:
    """Write the zip with fixed member order and timestamps.

    A rebuild of the same inputs then produces the same bytes, so a re-upload
    that should be a no-op is visibly one.
    """

    stamp = datetime.strptime(build_date, "%Y%m%d")
    timestamp = (stamp.year, stamp.month, stamp.day, 0, 0, 0)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = zip_path.with_suffix(".zip.part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
        for name, payload in members:
            info = zipfile.ZipInfo(name, date_time=timestamp)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            if isinstance(payload, bytes):
                out.writestr(info, payload)
                continue
            with payload.open("rb") as handle, out.open(info, "w") as target:
                shutil.copyfileobj(handle, target, 1024 * 1024)
    tmp.replace(zip_path)


def package_region(
    profile: EncodeProfile,
    region_code: str,
    build_date: str,
    *,
    output_dir: Path,
    skip_build: bool,
    force: bool,
) -> Path:
    region = disc_region.release_region(region_code)
    zip_path = output_dir / f"{asset_stem(profile, region.code, build_date)}.zip"
    if zip_path.exists() and not force:
        raise SystemExit(
            f"{zip_path}: already exists; pass --force to rebuild it")

    if skip_build:
        iso = PROJECT_ROOT / profile.region_release_disc_iso(region.code)
        if not iso.is_file():
            raise SystemExit(
                f"{iso}: no disc image to package; drop --skip-build")
    else:
        iso = build_disc(profile, region.code)

    names = disc_stem(profile, region.code)
    members: list[tuple[str, Path | bytes]] = [
        (f"{names}.iso", iso),
        (f"{names}.cue", cue_text(names).encode("utf-8")),
        ("README.txt",
         readme_text(profile, region.code, iso, build_date).encode("utf-8")),
    ]
    write_zip(zip_path, members, build_date)
    print(f"{region.tag} zip: {zip_path}", flush=True)
    return zip_path


def _assets_for(profile: EncodeProfile, zips: list[Path]) -> list[Path]:
    """The zips built from this profile, matched by their name prefix."""

    prefix = f"{profile.artifact_stem}_"
    return sorted(path for path in zips if path.name.startswith(prefix))


def release_notes(
    profiles: list[EncodeProfile],
    regions: list[str],
    build_date: str,
    zips: list[Path],
) -> str:
    """One release body covering every title in the release.

    English only. The release page is the project's public face, and the
    per-region README inside each zip is where a reader gets the same thing in
    Japanese.
    """

    encoder, player = av_versions()
    named = [disc_region.release_region(code) for code in regions]
    region_list = ", ".join(r.name_en for r in named)

    lines = [
        "Bootable Sega CD disc images produced by the Sega CD "
        "Constraint-Aware Video Codec. The console decodes and displays every "
        "frame itself while reading one single-speed CD, with no extra chip.",
        "",
        f"Regions: {region_list}. "
        f"Build: encoder {encoder}, player {player}, packaged {build_date}.",
        "",
        "**NTSC only.** The player's frame pacing, audio sync and CD delivery "
        "deadlines are all built on a 60 Hz field rate, so these discs are not "
        "made for a 50 Hz PAL console.",
        "",
        "Each zip holds one region's `.iso`, its `.cue`, and a README. Pick "
        "the region that matches your console: a console checks the region's "
        "security code on the disc and refuses the other one. In an emulator, "
        "open the `.cue`. On real hardware, burn the `.iso` as a single "
        "Disc-At-Once session with one data track.",
    ]

    for profile in profiles:
        video = profile.data["video"]
        width = int(video["width"])
        height = int(video["height"])
        fps = str(profile.data["source"]["fps"])
        fit = "filling" if width == 320 and height == 224 else "centered in"
        lines += [
            "",
            f"## {profile.release_title}",
            "",
            f"- Video: {width}x{height} {fit} the {APERTURE} H40 screen, "
            f"{fps} fps",
            f"- Audio: {AUDIO_FORMAT_EN}",
        ]
        if profile.source_label:
            source = profile.source_label
            if profile.source_url:
                source = f"{source} — {profile.source_url}"
            lines.append(f"- Source: {source}")
        for path in _assets_for(profile, zips):
            size = path.stat().st_size / (1024 * 1024)
            lines.append(f"- `{path.name}` ({size:.1f} MiB)")

    lines.append("")
    return "\n".join(lines)


def gh_release_exists(tag: str) -> bool:
    result = subprocess.run(
        ["gh", "release", "view", tag],
        cwd=PROJECT_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _profiles(args: argparse.Namespace) -> list[EncodeProfile]:
    return [load_profile(item) for item in args.config]


def cmd_build(args: argparse.Namespace) -> int:
    build_date = _build_date(args.date)
    output_dir = Path(args.output_dir) if args.output_dir else RELEASE_DIR
    zips = []
    # Serial on purpose: the regions of one profile take the same output-stem
    # lock, and a second holder fails immediately rather than queueing.
    for profile in _profiles(args):
        for code in args.regions:
            zips.append(package_region(
                profile, code, build_date,
                output_dir=output_dir,
                skip_build=args.skip_build,
                force=args.force,
            ))
    print(f"release tag: {release_tag(build_date)}", flush=True)
    for zip_path in zips:
        print(zip_path, flush=True)
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    build_date = _build_date(args.date)
    zips = [Path(item) for item in args.zip]
    print(release_notes(_profiles(args), args.regions, build_date, zips))
    return 0


def cmd_publish(args: argparse.Namespace) -> int:
    profiles = _profiles(args)
    build_date = _build_date(args.date)
    zips = [Path(item) for item in args.zip]
    missing = [str(path) for path in zips if not path.is_file()]
    if missing:
        raise SystemExit("missing assets: " + ", ".join(missing))
    unclaimed = set(zips) - {
        path for profile in profiles for path in _assets_for(profile, zips)}
    if unclaimed:
        raise SystemExit(
            "assets belong to no --config profile: "
            + ", ".join(sorted(path.name for path in unclaimed)))

    tag = args.tag or release_tag(build_date)
    notes = release_notes(profiles, args.regions, build_date, zips)
    with tempfile.NamedTemporaryFile(
            "w", suffix=".md", encoding="utf-8", delete=False) as handle:
        handle.write(notes)
        notes_path = Path(handle.name)

    try:
        if gh_release_exists(tag):
            print(f"release {tag} exists; uploading assets to it", flush=True)
            command = ["gh", "release", "upload", tag]
            command += [str(path) for path in zips]
            if args.clobber:
                command.append("--clobber")
            _run(command, cwd=PROJECT_ROOT)
            # The body lists the assets by name, so it goes stale the moment
            # the set of assets changes. Rewrite it from the zips just sent.
            _run(["gh", "release", "edit", tag,
                  "--notes-file", str(notes_path)], cwd=PROJECT_ROOT)
        else:
            command = [
                "gh", "release", "create", tag,
                "--title", f"Sega CD disc images ({build_date}.{_version_tag()})",
                "--notes-file", str(notes_path),
            ]
            if args.target:
                command += ["--target", args.target]
            if args.draft:
                command.append("--draft")
            command += [str(path) for path in zips]
            _run(command, cwd=PROJECT_ROOT)
    finally:
        notes_path.unlink(missing_ok=True)

    _run(["gh", "release", "view", tag, "--json",
          "url,isDraft,assets", "--jq",
          '"\\(.url)\\ndraft=\\(.isDraft)\\n" + '
          '(.assets | map("asset " + .name) | join("\\n"))'],
         cwd=PROJECT_ROOT)
    return 0


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", action="append", required=True,
        help="profile TOML, e.g. profiles/bad-apple.toml; repeatable. Every "
             "profile named here goes on one release")
    parser.add_argument(
        "--region", dest="regions", action="append",
        choices=sorted(disc_region.RELEASE_REGIONS),
        help="release region; repeatable. Default: every release region")
    parser.add_argument("--date", help="build date YYYYMMDD; default today")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)

    build = sub.add_parser("build", help="build discs and package the zips")
    _add_common(build)
    build.add_argument("--output-dir", help=f"default {RELEASE_DIR}")
    build.add_argument("--skip-build", action="store_true",
                       help="package the discs already in out/")
    build.add_argument("--force", action="store_true",
                       help="overwrite an existing zip")
    build.set_defaults(func=cmd_build)

    notes = sub.add_parser("notes", help="print the release body and exit")
    _add_common(notes)
    notes.add_argument("--zip", action="append", default=[], required=True)
    notes.set_defaults(func=cmd_notes)

    publish = sub.add_parser("publish", help="create or update the release")
    _add_common(publish)
    publish.add_argument("--zip", action="append", default=[], required=True)
    publish.add_argument("--tag", help="default disc-<date>.eN.pM")
    publish.add_argument("--target", help="commit or branch the tag points at")
    publish.add_argument(
        "--draft", action=argparse.BooleanOptionalAction, default=True,
        help="create the release as a draft (default). --no-draft publishes it")
    publish.add_argument(
        "--clobber", action="store_true",
        help="replace an asset of the same name on an existing release")
    publish.set_defaults(func=cmd_publish)

    args = parser.parse_args(argv)
    if not args.regions:
        args.regions = list(disc_region.RELEASE_REGIONS)
    os.chdir(PROJECT_ROOT)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
