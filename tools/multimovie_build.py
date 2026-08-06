#!/usr/bin/env python3
"""Build a separate multi-video menu disc from one TOML manifest."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import encode_config
import gen_menu_font
import multimovie
import player_constants


MENU_IP_IMAGE_BYTES = 0x5000
MENU_IP_SIZE_FIELD_MAX = 0xFFFF
PLAYER_IP_STAGE_BYTES = 0x20000 - 0x5000
MENU_SP_MAX_BYTES = 5120
BOOT_IMAGE_BYTES = 0x8000


def _run(command: list[str], root: Path) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=root, check=True)


def _tool(prefix: str, name: str) -> str:
    candidate = Path(prefix + name)
    if candidate.is_file():
        return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"cannot find {name!r} using prefix {prefix!r}")


def _write_if_changed(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_bytes() != data:
        path.write_bytes(data)


def _write_text_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def _profile_arg(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _build_player_module(
        root: Path,
        python: str,
        make: str,
        video: multimovie.MenuVideo,
        debug: int,
        security_region: str,
        marsdev: str,
        m68k_prefix: str,
        main_codegen: int,
        player_specialize: int,
    ) -> tuple[Path, Path, Path, Path]:
    profile = encode_config.load_profile(video.profile)
    profile_build = root / "tmp" / profile.artifact_stem / "build"
    include_path = profile_build / "multi_player.inc"
    _write_text_if_changed(include_path, multimovie.render_player_include(video))
    profile_build.mkdir(parents=True, exist_ok=True)
    command = [
        make,
        "movieplay-module",
        f"CONFIG={_profile_arg(root, video.profile)}",
        f"DEBUG={debug}",
        f"SECURITY_REGION={security_region}",
        "MULTI_MENU=1",
        f"MULTI_PLAYER_INCLUDE={include_path}",
        f"MAIN_CODEGEN={main_codegen}",
        f"PLAYER_SPECIALIZE={player_specialize}",
        f"MARSDEV={marsdev}",
        f"M68K_PREFIX={m68k_prefix}",
        f"PYTHON={python}",
    ]
    _run(command, root)
    stream_dir = root / "out" / profile.artifact_stem
    ip_path = profile_build / "movieplay_ip.bin"
    sp_path = profile_build / "movieplay_sp.bin"
    header_path = stream_dir / "HEADER.DAT"
    body_path = stream_dir / "BODY.DAT"
    for path in (ip_path, sp_path, header_path, body_path):
        if not path.is_file():
            raise RuntimeError(f"multi-video player build did not produce {path}")
    ip_bytes = ip_path.stat().st_size
    sp_bytes = sp_path.stat().st_size
    if ip_bytes <= 0 or ip_bytes & 1:
        raise RuntimeError(f"selected IP image must have a positive even size: {ip_path}")
    if ip_bytes > MENU_IP_SIZE_FIELD_MAX:
        raise RuntimeError(
            f"selected IP image is {ip_bytes} bytes; menu size table stores at most "
            f"{MENU_IP_SIZE_FIELD_MAX} bytes")
    if ip_bytes > PLAYER_IP_STAGE_BYTES:
        raise RuntimeError(
            f"selected IP image is {ip_bytes} bytes; Word-RAM staging slot is "
            f"{PLAYER_IP_STAGE_BYTES} bytes")
    if sp_bytes <= 0 or sp_bytes & 1 or sp_bytes > MENU_SP_MAX_BYTES:
        raise RuntimeError(
            f"selected SP image must be a positive even size no larger than "
            f"{MENU_SP_MAX_BYTES}: {sp_path}")
    return ip_path, sp_path, header_path, body_path


def _assemble_menu(
        root: Path,
        build_dir: Path,
        marsdev: str,
        m68k_prefix: str,
        security_region: str,
    ) -> tuple[Path, Path, Path]:
    assembler = _tool(m68k_prefix, "as")
    linker = _tool(m68k_prefix, "ld")
    objcopy = _tool(m68k_prefix, "objcopy")
    security = root / "boot" / f"sec_{security_region}.bin"
    if not security.is_file():
        raise FileNotFoundError(f"missing security file: {security}")
    shutil.copy2(security, build_dir / "security.bin")

    font_path = Path(marsdev) / "m68k-elf" / "res" / "image" / "font_default.png"
    font_data = gen_menu_font.generate(font_path)
    _write_if_changed(build_dir / "menu_font.bin", font_data)

    ip_obj = build_dir / "multimovie_ip.o"
    ip_raw = build_dir / "multimovie_ip.raw.bin"
    ip_image = build_dir / "multimovie_ip.bin"
    _run([
        assembler, "-m68000", "--register-prefix-optional", "--bitwise-or",
        f"-I{build_dir}", "-Iboot", "boot/multimovie_ip.s", "-o", str(ip_obj),
    ], root)
    _run([
        linker, "-nostdlib", "--oformat", "binary", "-T", "cfg/multimovie_ip.ld",
        "-o", str(ip_raw), str(ip_obj),
    ], root)
    raw = ip_raw.read_bytes()
    if len(raw) > MENU_IP_IMAGE_BYTES:
        raise RuntimeError(
            f"multi-video menu IP is {len(raw)} bytes; fixed slot is "
            f"{MENU_IP_IMAGE_BYTES} bytes")
    _write_if_changed(ip_image, raw.ljust(MENU_IP_IMAGE_BYTES, b"\0"))

    sp_obj = build_dir / "multimovie_sp.o"
    sp_image = build_dir / "menu_word.bin"
    _run([
        assembler, "-m68000", "--register-prefix-optional", "--bitwise-or",
        "--defsym", "MULTI_MENU_WORD=1",
        f"-I{build_dir}", "-Iboot", "boot/multimovie_sp.s", "-o", str(sp_obj),
    ], root)
    _run([
        linker, "-nostdlib", "--oformat", "binary", "-T", "cfg/sp_menu_word.ld",
        "-o", str(sp_image), str(sp_obj),
    ], root)
    sp_size = sp_image.stat().st_size
    if sp_size > MENU_SP_MAX_BYTES:
        raise RuntimeError(
            f"multi-video Word-RAM launcher is {sp_size} bytes; limit is "
            f"{MENU_SP_MAX_BYTES}")
    if sp_size < MENU_SP_MAX_BYTES:
        sp_image.write_bytes(sp_image.read_bytes().ljust(MENU_SP_MAX_BYTES, b"\0"))

    bootstrap_obj = build_dir / "multimovie_boot_sp.o"
    bootstrap_image = build_dir / "multimovie_boot_sp.bin"
    _run([
        assembler, "-m68000", "--register-prefix-optional", "--bitwise-or",
        f"-I{build_dir}", "-Iboot", "boot/multimovie_boot_sp.s",
        "-o", str(bootstrap_obj),
    ], root)
    _run([
        linker, "-nostdlib", "--oformat", "binary", "-T", "cfg/sp.ld",
        "-o", str(bootstrap_image), str(bootstrap_obj),
    ], root)
    bootstrap_size = bootstrap_image.stat().st_size
    if bootstrap_size > MENU_SP_MAX_BYTES:
        raise RuntimeError(
            f"multi-video boot Sub loader is {bootstrap_size} bytes; limit is "
            f"{MENU_SP_MAX_BYTES}")

    boot_obj = build_dir / "multimovie_boot.o"
    boot_image = build_dir / "multimovie_boot.bin"
    _run([
        assembler, "-m68000", "--register-prefix-optional", "--bitwise-or",
        f"-I{build_dir}", "-Iboot", "boot/multimovie_boot.s", "-o", str(boot_obj),
    ], root)
    _run([objcopy, "-O", "binary", str(boot_obj), str(boot_image)], root)
    if boot_image.stat().st_size != BOOT_IMAGE_BYTES:
        raise RuntimeError(
            f"multi-video boot image is {boot_image.stat().st_size} bytes; "
            f"expected {BOOT_IMAGE_BYTES}")
    return ip_image, sp_image, boot_image


def build(args: argparse.Namespace) -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = multimovie.load_manifest(args.manifest)
    debug = int(args.debug)
    if debug not in (0, 1):
        raise ValueError("--debug must be 0 or 1")
    output_stem = f"{manifest.output_stem}_multi"
    suffix = "" if debug else "_release"
    work_dir = root / "tmp" / f"{output_stem}{suffix}"
    build_dir = work_dir / "build"
    disc_dir = work_dir / "disc"
    out_dir = root / "out"
    iso_path = out_dir / f"{output_stem}{suffix}.iso"
    cue_path = out_dir / f"{output_stem}{suffix}.cue"
    build_dir.mkdir(parents=True, exist_ok=True)
    disc_dir.mkdir(parents=True, exist_ok=True)

    built: list[multimovie.BuiltVideo] = []
    staged: list[tuple[multimovie.MenuVideo, Path, Path, Path, Path]] = []
    for video in manifest.videos:
        print(f"multi-video: building {video.index}: {video.title}")
        ip_path, sp_path, header_path, body_path = _build_player_module(
            root=root,
            python=args.python,
            make=args.make,
            video=video,
            debug=debug,
            security_region=args.security_region,
            marsdev=args.marsdev,
            m68k_prefix=args.m68k_prefix,
            main_codegen=int(args.main_codegen),
            player_specialize=int(args.player_specialize),
        )
        with header_path.open("rb") as src:
            constants = player_constants.parse_header_sector(src.read(2048))
        built.append(multimovie.BuiltVideo(
            video=video,
            frames=constants.frames,
            tcols=constants.tcols,
            trows=constants.trows,
            fps=constants.fps_int,
            header_bytes=header_path.stat().st_size,
            body_bytes=body_path.stat().st_size,
            ip_bytes=ip_path.stat().st_size,
            sp_bytes=sp_path.stat().st_size,
        ))
        staged.append((video, ip_path, sp_path, header_path, body_path))

    _write_text_if_changed(
        build_dir / "multimovie_ip.inc",
        multimovie.render_menu_include(manifest, built),
    )
    _write_text_if_changed(
        build_dir / "multimovie_sp.inc",
        multimovie.render_launcher_include(manifest),
    )
    menu_ip, menu_word, boot_image = _assemble_menu(
        root=root,
        build_dir=build_dir,
        marsdev=args.marsdev,
        m68k_prefix=args.m68k_prefix,
        security_region=args.security_region,
    )

    for child in disc_dir.iterdir():
        if child.is_file() or child.is_symlink():
            child.unlink()
        elif child.is_dir():
            shutil.rmtree(child)
    _write_text_if_changed(
        disc_dir / "README.TXT",
        "SCFMV multi-video menu build\n",
    )
    shutil.copy2(menu_ip, disc_dir / "MENUIP.BIN")
    shutil.copy2(menu_word, disc_dir / "MENUSP.BIN")
    for video, ip_path, sp_path, header_path, body_path in staged:
        shutil.copy2(ip_path, disc_dir / video.ip_name)
        shutil.copy2(sp_path, disc_dir / video.sp_name)
        shutil.copy2(header_path, disc_dir / video.header_name)
        shutil.copy2(body_path, disc_dir / video.body_name)

    iso_tool = args.mkisofs or shutil.which("mkisofs") or shutil.which("genisoimage")
    if not iso_tool:
        raise FileNotFoundError("mkisofs/genisoimage is required for multi-disc")
    out_dir.mkdir(parents=True, exist_ok=True)
    if iso_path.exists():
        iso_path.unlink()
    _run([
        iso_tool, "-iso-level", "1", "-G", str(boot_image), "-pad",
        "-V", "SCFMV_MUL", "-o", str(iso_path), str(disc_dir),
    ], root)
    _write_text_if_changed(
        cue_path,
        f'FILE "{iso_path.name}" BINARY\n'
        "  TRACK 01 MODE1/2048\n"
        "    INDEX 01 00:00:00\n",
    )
    print(f"multi-video: {iso_path}")
    print(f"multi-video: {cue_path}")
    print(multimovie.render_manifest_summary(manifest))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", choices=("build",))
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--debug", default="0")
    parser.add_argument("--security-region", default="jp")
    parser.add_argument("--marsdev", required=True)
    parser.add_argument("--m68k-prefix", required=True)
    parser.add_argument("--python", required=True)
    parser.add_argument("--make", default="make")
    parser.add_argument("--mkisofs", default="")
    parser.add_argument("--main-codegen", default="1")
    parser.add_argument("--player-specialize", default="1")
    args = parser.parse_args()
    build(args)


if __name__ == "__main__":
    main()
