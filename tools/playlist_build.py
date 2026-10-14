#!/usr/bin/env python3
"""Build a menu-free looping disc from referenced encode profiles."""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import multimovie
import analysis_logs
import multimovie_build as multi
import player_constants
import playlist
import encode_config
import resource_tokens
import tmpfs_workspace


def symbol(prefix: str, obj: Path, name: str, base: int) -> int:
    output = subprocess.check_output([multi._tool(prefix, "nm"), "--defined-only", str(obj)], text=True)
    matches = [int(line.split()[0], 16) for line in output.splitlines()
               if len(line.split()) == 3 and line.split()[2] == name]
    if len(matches) != 1:
        raise ValueError(f"{obj}: missing or ambiguous symbol {name}")
    return base + matches[0]


def main_include(sizes, entries):
    return "\n".join([
        "/* Generated playlist dispatch table. */",
        f".equ MENU_COUNT, {len(sizes)}",
        ".data", ".align 2", "menu_ip_sizes:",
        ".word " + ",".join(str(size) for size in sizes),
        ".align 2", "playlist_player_entries:",
        ".long " + ",".join(hex(entry) for entry in entries), "",
    ])


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def reuse_packed(root, item, profile, baseline):
    """Authenticate a player-only rebuild without disposable SIM inputs."""
    old = next((v for v in baseline['items'] if v['id'] == item.id), None)
    if old is None or old['source_profile'] != str(item.profile) or old['overrides'] != item.overrides:
        raise ValueError(f'{item.id}: packed baseline source/overrides mismatch')
    prior = encode_config.load_profile(old['effective_profile'])
    if prior.sha256 != old['profile_sha256']:
        raise ValueError(f'{item.id}: packed baseline profile changed')
    before, after = copy.deepcopy(prior.data), copy.deepcopy(profile.data)
    before.pop('youtube', None)
    after.pop('youtube', None)
    if before != after:
        raise ValueError(f'{item.id}: encoded settings changed')
    source = (root / profile.section('source')['path']).resolve()
    if digest(source) != old['source_sha256']:
        raise ValueError(f'{item.id}: source bytes changed')
    original, target = root / 'out' / prior.artifact_stem, root / 'out' / profile.artifact_stem
    records = {name: next(v for k, v in old['files'].items() if k.endswith(suffix))
               for name, suffix in [('HEADER.DAT', 'HDR.DAT'), ('BODY.DAT', 'BOD.DAT')]}
    records.update(old['palette_files'])
    for name, record in records.items():
        path = original / name
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError(f'{item.id}: packed baseline bytes changed: {name}')
    target.mkdir(parents=True, exist_ok=True)
    for name in records:
        if original != target:
            shutil.copy2(original / name, target / name)


def verify_iso(iso: Path, staged: Path) -> None:
    """Walk ISO9660 directory records and authenticate every staged file."""
    def paired_u32(record, offset):
        little = int.from_bytes(record[offset:offset + 4], "little")
        big = int.from_bytes(record[offset + 4:offset + 8], "big")
        if little != big:
            raise ValueError("ISO little/big-endian directory fields disagree")
        return little

    with iso.open("rb") as stream:
        stream.seek(16 * 2048)
        pvd = stream.read(2048)
        if pvd[:7] != b"\x01CD001\x01":
            raise ValueError("missing ISO9660 primary descriptor")
        root = pvd[156:190]
        lba = paired_u32(root, 2)
        size = paired_u32(root, 10)
        if not 0 < size <= 65536:
            raise ValueError("playlist ISO directory exceeds loader's 64 KiB capacity")
        stream.seek(lba * 2048)
        directory = stream.read(size)
        if len(directory) != size:
            raise ValueError("truncated ISO root directory")
        files = {}
        offset = 0
        while offset < size:
            length = directory[offset]
            if length == 0:
                offset = (offset // 2048 + 1) * 2048
                continue
            record = directory[offset:offset + length]
            if length < 34 or len(record) != length or 33 + record[32] > length:
                raise ValueError("invalid ISO directory record")
            if not record[25] & 2:
                name = record[33:33 + record[32]].decode("ascii").split(";")[0]
                if name in files:
                    raise ValueError("duplicate ISO file")
                files[name] = (paired_u32(record, 2), paired_u32(record, 10))
            offset += length
        for path in staged.iterdir():
            if not path.is_file():
                raise ValueError("playlist staging must be flat")
            if path.name not in files:
                raise ValueError(f"missing ISO file: {path.name}")
            start, count = files[path.name]
            if count != path.stat().st_size:
                raise ValueError(f"ISO size mismatch: {path.name}")
            stream.seek(start * 2048)
            if hashlib.sha256(stream.read(count)).hexdigest() != digest(path):
                raise ValueError(f"ISO byte mismatch: {path.name}")
    if iso.stat().st_size > 360000 * 2048:
        raise ValueError("playlist exceeds an 80-minute data disc")


@contextlib.contextmanager
def profile_lock(profile):
    with resource_tokens.acquire_stem(profile.sim_stem):
        key = resource_tokens.HELD_STEMS_ENV
        previous = os.environ.get(key)
        os.environ[key] = resource_tokens.held_stem_environment(profile.sim_stem)[key]
        try:
            yield
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous


def build(args):
    root = Path(__file__).resolve().parents[1]
    config = playlist.load(args.manifest)
    baseline_path = getattr(args, 'packed_manifest', None)
    baseline = json.loads(baseline_path.read_text()) if baseline_path else None
    if baseline:
        if args.encode or baseline['versions'][0] != analysis_logs.av_versions()[0]:
            raise ValueError('packed rebuild requires the same encoder version and no --encode')
    work = root / "tmp" / config.stem
    build_dir = work / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    profiles = playlist.materialize(config, work / "profiles")
    videos = tuple(multimovie.MenuVideo(i, p.path, item.id)
                   for i, (item, p) in enumerate(zip(config.items, profiles)))
    manifest = multimovie.MenuManifest(config.path, "CAVC FMV PLAYLIST", "", config.stem, videos)
    launcher_include = multimovie.render_launcher_include(manifest)
    multi._write_text_if_changed(build_dir / "multimovie_sp.inc", launcher_include)
    multi._write_text_if_changed(build_dir / "multimovie_ip.inc",
                                 main_include([2] * len(videos), [0] * len(videos)))
    assemble = dict(root=root, build_dir=build_dir, marsdev=args.marsdev,
                    m68k_prefix=args.m68k_prefix, security_region=args.security_region,
                    main_source="boot/playlist_ip.s")
    # Link a skeleton first to derive the reentry symbol, not a magic address.
    multi._assemble_menu(**assemble)
    reentry = symbol(args.m68k_prefix, build_dir / "multimovie_ip.o", "playlist_resume", 0xFF0000)
    obj = build_dir / "multimovie_ip.o"
    if symbol(args.m68k_prefix, obj, "playlist_copy_end", 0) - symbol(args.m68k_prefix, obj, "playlist_copy", 0) > 0xB1D0 - 0x8880:
        raise ValueError("playlist copy stub overlaps persistent state")
    staged = work / "disc"
    staged.mkdir(parents=True, exist_ok=True)
    for child in staged.iterdir():
        if child.is_file():
            child.unlink()
        else:
            raise ValueError(f"unexpected playlist staging entry: {child}")
    metadata, sizes, entries, sp_entries = [], [], [], []
    for item, profile, video in zip(config.items, profiles, videos):
        print(f"playlist: {item.id}: {profile.path}", flush=True)
        with profile_lock(profile):
            if args.encode:
                multi._run([args.python, "--gpu", "tools/sim.py", str(profile.path)], root)
            lease = tmpfs_workspace.lease_managed_path(profile.output_dir)
            if baseline:
                reuse_packed(root, item, profile, baseline)
            elif lease is None:
                raise ValueError(f"missing SIM for {item.id}; use --encode")
            try:
                paths = multi._build_player_module(
                    root, args.python, args.make, video, args.debug,
                    args.security_region, args.marsdev, args.m68k_prefix, 1, 1,
                    f".equ PLAYLIST, 1\n.equ PLAYLIST_RETURN_ENTRY, {reentry}\n",
                    reuse_packed=bool(baseline))
                ip, sp, header, body = paths
                module_dir = ip.parent
                if baseline:
                    # The extension executes from HEADER rather than the new
                    # SP image. A player-only rebuild must keep that code exact.
                    import ima_adpcm
                    import sp_extension
                    preload = sp_extension.adpcm_preload_image(
                        ima_adpcm.full_tables(),
                        (module_dir / 'movieplay_sp_ext.bin').read_bytes())
                    if header.read_bytes().count(preload) != 1:
                        raise ValueError(f'{item.id}: packed Sub extension differs; repack required')
                ip_entry = symbol(args.m68k_prefix, module_dir / "movieplay_ip.o", "ip_entry", 0xFF0000)
                sp_entry = symbol(args.m68k_prefix, module_dir / "movieplay_sp.o", "multi_player_entry", 0x6000)
                if not 0xFF0000 <= ip_entry < 0xFF0000 + ip.stat().st_size:
                    raise ValueError("Main entry outside player image")
                if not 0x6000 <= sp_entry < 0x6000 + sp.stat().st_size:
                    raise ValueError("Sub entry outside player image")
                sizes.append(ip.stat().st_size)
                entries.append(ip_entry)
                sp_entries.append(sp_entry)
                constants = player_constants.parse_header_sector(header.read_bytes()[:2048])
                files = {}
                for path, name in zip(paths, (video.ip_name, video.sp_name, video.header_name, video.body_name)):
                    shutil.copy2(path, staged / name)
                    files[name] = {"bytes": path.stat().st_size, "sha256": digest(path)}
                source_path = (root / profile.section("source")["path"]).resolve()
                palette_files = {name: {"bytes": (header.parent / name).stat().st_size,
                                        "sha256": digest(header.parent / name)}
                                 for name in ("paltab.bin", "palidx.bin")}
                metadata.append(dict(id=item.id, index=video.index, source_profile=str(item.profile),
                                     source_path=str(source_path), source_sha256=digest(source_path),
                                     effective_profile=str(profile.path), profile_sha256=profile.sha256,
                                     overrides=item.overrides, frames=constants.frames,
                                     fps=constants.fps_int, ip_entry=ip_entry, sp_entry=sp_entry,
                                     palette_files=palette_files, files=files))
            finally:
                if lease is not None:
                    lease.release()
    multi._write_text_if_changed(build_dir / "multimovie_ip.inc", main_include(sizes, entries))
    # The Sub launcher also uses generated entry addresses for every module.
    launcher_include += "\n.equ PLAYLIST, 1\n.data\n.align 2\nplaylist_sp_entries:\n.long " + ",".join(hex(v) for v in sp_entries) + "\n"
    multi._write_text_if_changed(build_dir / "multimovie_sp.inc", launcher_include)
    menu_ip, menu_sp, boot = multi._assemble_menu(**assemble)
    bootstrap_obj = build_dir / "multimovie_boot_sp.o"
    for first, last, capacity in (
        ("multi_word_swap_stub_image", "multi_word_swap_stub_image_end", 0x7F64 - 0x7F50),
        ("multi_return_image", "multi_return_image_end", 0xD800 - 0xD680),
    ):
        length = symbol(args.m68k_prefix, bootstrap_obj, last, 0) - symbol(args.m68k_prefix, bootstrap_obj, first, 0)
        if not 0 < length <= capacity or length % 2:
            raise ValueError(f"resident {first} exceeds its reserved memory: {length}/{capacity}")
    if reentry != symbol(args.m68k_prefix, build_dir / "multimovie_ip.o", "playlist_resume", 0xFF0000):
        raise ValueError("dispatcher reentry moved after table generation")
    shutil.copy2(menu_ip, staged / "MENUIP.BIN")
    shutil.copy2(menu_sp, staged / "MENUSP.BIN")
    out = root / "out"
    out.mkdir(exist_ok=True)
    suffix = "" if args.debug else "_release"
    iso = out / f"{config.stem}{suffix}.iso"
    pending = work / "playlist.pending.iso"
    tool = args.mkisofs or shutil.which("mkisofs") or shutil.which("genisoimage")
    if not tool:
        raise ValueError("mkisofs/genisoimage is required")
    multi._run([tool, "-iso-level", "1", "-G", str(boot), "-pad", "-V", "CAVC_PLAYLIST",
                "-o", str(pending), str(staged)], root)
    verify_iso(pending, staged)
    pending.replace(iso)
    cue = iso.with_suffix(".cue")
    cue.write_text(f'FILE "{iso.name}" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n')
    receipt = out / config.stem / f"playlist{suffix}.json"
    receipt.parent.mkdir(exist_ok=True)
    receipt.write_text(json.dumps(dict(schema_version=1, profile=str(config.path),
                          versions=list(analysis_logs.av_versions()),
                          profile_sha256=digest(config.path), debug=args.debug,
                          trace_pc_start=symbol(args.m68k_prefix, build_dir / "multimovie_ip.o", "playlist_trace_begin", 0xFF0000),
                          trace_pc_end=symbol(args.m68k_prefix, build_dir / "multimovie_ip.o", "playlist_trace_end", 0xFF0000),
                          iso=str(iso), iso_bytes=iso.stat().st_size,
                          packed_baseline=(dict(path=str(baseline_path.resolve()),
                                                sha256=digest(baseline_path))
                                           if baseline_path else None),
                          iso_sha256=digest(iso), items=metadata), indent=2) + "\n")
    print(f"playlist: verified {iso}\nplaylist: {cue}\nplaylist: {receipt}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--debug", type=int, choices=(0, 1), default=1)
    parser.add_argument("--encode", action="store_true")
    parser.add_argument("--packed-manifest", type=Path,
                        help="authenticate existing streams for a player-only rebuild")
    parser.add_argument("--security-region", choices=("jp",), default="jp")
    parser.add_argument("--marsdev", default=str(Path.home() / "toolchains/mars"))
    parser.add_argument("--m68k-prefix", default=str(Path.home() / "toolchains/mars/m68k-elf/bin/m68k-elf-"))
    parser.add_argument("--python", default="tools/python.sh")
    parser.add_argument("--make", default="make")
    parser.add_argument("--mkisofs", default="")
    args = parser.parse_args()
    with resource_tokens.acquire_stem("playlist:" + args.manifest.resolve().stem):
        build(args)


if __name__ == "__main__":
    main()
