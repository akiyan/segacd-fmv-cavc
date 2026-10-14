#!/usr/bin/env python3
"""Record one immutable playlist build and qualify its complete visits."""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import encode_config
import playlist_build
import resource_tokens
import tmpfs_workspace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--seconds", type=int, required=True)
    parser.add_argument("--min-cycles", type=int, default=1)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--baseline-gate", type=Path,
                        help="qualify a release disc against this PASS DEBUG playlist gate")
    parser.add_argument("--workspace-gb", type=int,
                        help="explicit managed tmpfs reservation for a measured long recording")
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    if args.seconds <= 0 or args.min_cycles <= 0 or (args.workspace_gb is not None and args.workspace_gb <= 0):
        parser.error("positive duration/cycles/workspace are required")
    if (manifest["debug"] == 0) != (args.baseline_gate is not None):
        parser.error("a release manifest requires --baseline-gate; DEBUG does not use it")
    iso = Path(manifest["iso"])
    with contextlib.ExitStack() as stack:
        stack.enter_context(resource_tokens.acquire_stem("playlist:" + Path(manifest["profile"]).stem))
        if args.baseline_gate is not None:
            from release import baseline_for
            baseline_gate = json.loads(args.baseline_gate.read_text())
            lease = tmpfs_workspace.lease_managed_path(Path(baseline_gate["recording"]))
            if lease is None:
                raise ValueError("DEBUG baseline recording is missing")
            stack.callback(lease.release)
            _, baseline_capture = baseline_for(manifest, args.baseline_gate)
            if baseline_capture["seconds"] != args.seconds:
                raise ValueError("release duration must match the DEBUG baseline")
        if playlist_build.digest(iso) != manifest["iso_sha256"]:
            raise ValueError("ISO no longer matches the build manifest")
        held = set()
        for item in manifest["items"]:
            profile = encode_config.load_profile(item["effective_profile"])
            if profile.sha256 != item["profile_sha256"]:
                raise ValueError("effective profile no longer matches build")
            if profile.sim_stem not in held:
                stack.enter_context(resource_tokens.acquire_stem(profile.sim_stem))
                held.add(profile.sim_stem)
            lease = tmpfs_workspace.lease_managed_path(profile.output_dir)
            if lease is None:
                raise ValueError(f"SIM data missing for {item['id']}")
            stack.callback(lease.release)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        snapshot = ROOT / "logs" / f"{stamp}_{Path(manifest['profile']).stem}_build.json"
        snapshot.write_text(json.dumps(manifest, indent=2) + "\n")
        command = ["tools/record_movie.sh", "--disc", str(iso.with_suffix(".cue")),
                   "--no-build", "--seconds", str(args.seconds), "--tag", args.tag,
                   "--record-size", "320x224"]
        core = ROOT / "vendor/gpgx-logvdp/genesis_plus_gx_logvdp_libretro.so"
        core_sha = playlist_build.digest(core)
        if args.baseline_gate is not None and baseline_capture["core_sha256"] != core_sha:
            raise ValueError("release core differs from the DEBUG baseline")
        env = dict(os.environ)
        if args.workspace_gb is not None:
            # Same recorder and resource locks; the outer pipeline owns the
            # allocation/lease instead of the recorder's per-minute estimate.
            workspace = tmpfs_workspace.activate_directory(
                kind="playlist-record", key=f"{args.tag}|{manifest['iso_sha256']}|{stamp}",
                required_bytes=args.workspace_gb * 1024**3)
            stack.callback(workspace.release)
            env.update(SEGACD_RECORD_TMPFS_HELD="1", OUTDIR=str(workspace.entry / "data"))
        print(f"Recording {args.seconds}s / {args.min_cycles} cycles", flush=True)
        run = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        sys.stdout.write(run.stdout)
        sys.stdout.flush()
        run.check_returncode()
        recording = Path(next(line.split("=", 1)[1] for line in run.stdout.splitlines() if line.startswith("LOSSLESS=")))
        lease = tmpfs_workspace.lease_managed_path(recording)
        if lease is None:
            raise ValueError("recording lost its managed workspace entry")
        stack.callback(lease.release)
        full_log = recording.parent / f"gpgx_logvdp_{args.tag}.log.gz"
        if playlist_build.digest(iso) != manifest["iso_sha256"] or playlist_build.digest(core) != core_sha:
            raise ValueError("ISO or emulator core changed during recording")
        receipt = snapshot.with_name(snapshot.stem + "_capture.json")
        compact_log = recording.parent / f"retroarch_{args.tag}.log"
        receipt.write_text(json.dumps(dict(schema_version=1,
            manifest=str(snapshot), manifest_sha256=playlist_build.digest(snapshot),
            iso_sha256=manifest["iso_sha256"], core_sha256=core_sha,
            recording=str(recording), recording_sha256=playlist_build.digest(recording),
            compact_log=str(compact_log), compact_log_sha256=playlist_build.digest(compact_log),
            full_log=str(full_log), full_log_sha256=playlist_build.digest(full_log),
            seconds=args.seconds, command=command), indent=2) + "\n")
        print(f"CAPTURE_RECEIPT={receipt}", flush=True)
        if args.baseline_gate is not None:
            return subprocess.run(["tools/python.sh", "harness/playlist/release.py", str(receipt),
                "--baseline-gate", str(args.baseline_gate),
                "--min-cycles", str(args.min_cycles)], cwd=ROOT).returncode
        return subprocess.run(["tools/python.sh", "harness/playlist/analyze.py",
                    str(recording), str(full_log), str(snapshot),
                    "--capture-receipt", str(receipt), "--min-cycles", str(args.min_cycles)], cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
