#!/usr/bin/env python3
"""Qualify a HUD-free playlist through its immutable DEBUG baseline."""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import subprocess
from pathlib import Path

from analyze import ROOT, read_markers
import playlist_build


def baseline_for(manifest, gate_path):
    gate = json.loads(gate_path.read_text())
    baseline_path = Path(gate["manifest"])
    if gate["gate"] != "PASS" or playlist_build.digest(baseline_path) != gate["manifest_sha256"]:
        raise ValueError("release needs an intact PASS DEBUG baseline")
    baseline = json.loads(baseline_path.read_text())
    if baseline["debug"] != 1 or manifest["debug"] != 0:
        raise ValueError("expected DEBUG baseline and release target")
    if not baseline.get("versions") or baseline["versions"] != manifest.get("versions"):
        raise ValueError("encoder/player versions differ or are missing")
    if len(baseline["items"]) != len(manifest["items"]):
        raise ValueError("playlist length differs from baseline")
    for before, after in zip(baseline["items"], manifest["items"]):
        for field in ("id", "index", "profile_sha256", "frames", "fps", "palette_files"):
            if field not in before or before[field] != after.get(field):
                raise ValueError(f"release differs from baseline: {after['id']} {field}")
        for name, info in before["files"].items():
            if name.endswith(("HDR.DAT", "BOD.DAT")) and after["files"].get(name) != info:
                raise ValueError(f"release stream changed: {name}")
    if gate["completed_visits"] < len(manifest["items"]) or gate["boundaries"] < len(manifest["items"]):
        raise ValueError("baseline must include a full cycle and wraparound")
    capture = json.loads(Path(gate["capture_receipt"]).read_text())
    for name in ("recording", "full_log", "compact_log"):
        if playlist_build.digest(Path(capture[name])) != capture[name + "_sha256"]:
            raise ValueError(f"baseline {name} changed")
    if capture["iso_sha256"] != baseline["iso_sha256"] or capture["manifest_sha256"] != gate["manifest_sha256"]:
        raise ValueError("baseline capture does not bind the qualified build")
    return gate, capture


def qualify(capture_path, gate_path, minimum_cycles):
    capture = json.loads(capture_path.read_text())
    manifest = json.loads(Path(capture["manifest"]).read_text())
    gate, baseline = baseline_for(manifest, gate_path)
    for name in ("recording", "full_log", "compact_log", "manifest"):
        if playlist_build.digest(Path(capture[name])) != capture[name + "_sha256"]:
            raise ValueError(f"release {name} changed")
    if capture["iso_sha256"] != manifest["iso_sha256"] or capture["core_sha256"] != baseline["core_sha256"]:
        raise ValueError("release capture ISO/core differs from its evidence")
    if capture["seconds"] != baseline["seconds"]:
        raise ValueError("release and DEBUG must use the same bounded duration")
    print("Checking release dispatcher markers", flush=True)
    with gzip.open(capture["full_log"], "rt", errors="strict") as lines:
        markers = read_markers(lines, manifest)
    markers_path = capture_path.with_name(capture_path.stem + "_release_markers.tsv")
    with markers_path.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=["index", "cycle", "visit", "log_line", "id"],
                                delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows({**marker, "id": manifest["items"][marker["index"]]["id"]}
                         for marker in markers)
    failures = []
    if len(markers) < minimum_cycles * len(manifest["items"]) + 1:
        failures.append("release did not reach the next cycle")
    comparison_path = capture_path.with_name(capture_path.stem + "_logvdp_compare.json")
    comparison = subprocess.run(["tools/python.sh",
        ".agents/skills/release/scripts/compare_logvdp.py",
        "--baseline", baseline["compact_log"], "--release", capture["compact_log"],
        "--json", str(comparison_path)], cwd=ROOT)
    compared = json.loads(comparison_path.read_text())
    if comparison.returncode:
        failures.append("LOGVDP comparison failed")
    # A zero baseline must not silently exempt new active-display DMA.
    base_player = compared["baseline"]["player"]
    rel_player = compared["release"]["player"]
    if any(not (player["blanking_accesses"] + player["active_accesses"])
           for player in (base_player, rel_player)):
        failures.append("missing player DMA in a comparison trace")
    if not base_player["active_accesses"] and rel_player["active_accesses"]:
        failures.append("release introduced active-display DMA")
    path = capture_path.with_name(capture_path.stem + "_release_check.json")
    path.write_text(json.dumps(dict(schema_version=1,
        trace_result="FAIL" if failures else "PASS", failures=failures,
        visual_inspection="PENDING", baseline_gate=str(gate_path.resolve()),
        baseline_gate_sha256=playlist_build.digest(gate_path), capture=str(capture_path.resolve()),
        capture_sha256=playlist_build.digest(capture_path), iso_sha256=manifest["iso_sha256"],
        stream_hashes_identical=True, markers=markers, minimum_cycles=minimum_cycles,
        markers_tsv=str(markers_path),
        logvdp_comparison=str(comparison_path),
        logvdp_comparison_sha256=playlist_build.digest(comparison_path)), indent=2) + "\n")
    print(f"PLAYLIST_RELEASE_CHECK={path}\nPLAYLIST_TRACE_RESULT={'FAIL' if failures else 'PASS'}", flush=True)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--baseline-gate", type=Path, required=True)
    parser.add_argument("--min-cycles", type=int, default=1)
    args = parser.parse_args()
    if args.min_cycles <= 0:
        parser.error("--min-cycles must be positive")
    return qualify(args.capture, args.baseline_gate, args.min_cycles)


if __name__ == "__main__":
    raise SystemExit(main())
