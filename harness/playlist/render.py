#!/usr/bin/env python3
"""Render first-cycle diagnostics with explicitly matched per-item timelines."""
from __future__ import annotations

import argparse
import contextlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import playlist_build
import encode_config
import tmpfs_workspace


def render(script, arguments):
    command = ["tools/python.sh", f".agents/skills/{script}", *map(str, arguments)]
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(result.stdout + result.stderr)
    lines = result.stdout.strip().splitlines()
    if len(lines) != 2 or not all(Path(line).is_file() for line in lines):
        raise ValueError(f"unexpected renderer output: {result.stdout}")
    return dict(image=lines[0], layout=lines[1], sha256=playlist_build.digest(Path(lines[0])))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gate", type=Path)
    parser.add_argument("--timeline", action="append", required=True, metavar="ITEM=TSV")
    args = parser.parse_args()
    timelines = {}
    for value in args.timeline:
        name, separator, path = value.partition("=")
        if not separator or name in timelines:
            parser.error("each --timeline must be a unique ITEM=TSV")
        timelines[name] = Path(path).resolve()
    gate = json.loads(args.gate.read_text())
    manifest_path = Path(gate["manifest"])
    if playlist_build.digest(manifest_path) != gate["manifest_sha256"]:
        raise ValueError("build manifest changed after qualification")
    manifest = json.loads(manifest_path.read_text())
    if len(gate["visits"]) < len(manifest["items"]):
        raise ValueError("a complete first cycle is required for whole-movie graphs")
    output = []
    with contextlib.ExitStack() as stack:
        recording_lease = tmpfs_workspace.lease_managed_path(Path(gate["recording"]))
        if recording_lease is not None:
            stack.callback(recording_lease.release)
        for item, visit in zip(manifest["items"], gate["visits"]):
            if visit["id"] != item["id"] or not visit["complete"]:
                raise ValueError("a complete first cycle is required for whole-movie graphs")
            profile = item["effective_profile"]
            effective = encode_config.load_profile(profile)
            if effective.sha256 != item["profile_sha256"]:
                raise ValueError("effective profile changed after build")
            timeline = render("timeline/scripts/render_timeline.py", [
                timelines[item["id"]], "--config", profile, "--sim-out", effective.output_dir,
                "--label", f"playlist: {item['id']}"])
            lease = tmpfs_workspace.lease_managed_path(Path(timeline["image"]))
            stack.callback(lease.release)
            hudline = render("hudline/scripts/render_hudline.py", [
                visit["hud_tsv"], "--gate-json", visit["hud_gate"], "--config", profile,
                "--label", f"playlist: {item['id']} visit {visit['visit']}"])
            overages = Path(visit["hud_tsv"]).with_suffix(".overages.md")
            with overages.open("w") as report:
                subprocess.run(["tools/python.sh",
                    ".agents/skills/hudline/scripts/report_overages.py", visit["hud_tsv"],
                    "--gate-json", visit["hud_gate"]], cwd=ROOT, stdout=report, check=True)
            lease = tmpfs_workspace.lease_managed_path(Path(hudline["image"]))
            stack.callback(lease.release)
            mixline = render("mixline/scripts/render_mixline.py", [
                timeline["image"], hudline["image"], "--timeline-layout", timeline["layout"],
                "--hudline-layout", hudline["layout"]])
            lease = tmpfs_workspace.lease_managed_path(Path(mixline["image"]))
            stack.callback(lease.release)
            output.append(dict(id=item["id"], timeline=timeline, hudline=hudline,
                               mixline=mixline, overages=str(overages)))
            print(f"Rendered {item['id']}", flush=True)
        path = args.gate.with_name(args.gate.stem + "_graphs.json")
        path.write_text(json.dumps(dict(gate=str(args.gate.resolve()),
            gate_sha256=playlist_build.digest(args.gate), items=output), indent=2) + "\n")
        print(f"PLAYLIST_GRAPHS={path.resolve()}")


if __name__ == "__main__":
    main()
