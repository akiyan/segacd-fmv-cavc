#!/usr/bin/env python3
"""Qualify every playlist visit using dispatcher traces and the standard HUD."""
from __future__ import annotations

import argparse
import csv
import dataclasses
import gzip
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import analysis_logs
import encode_config
import playlist_build
import resource_tokens

spec = importlib.util.spec_from_file_location("playlist_hud", ROOT / "harness/startup_resync/analyze.py")
hud = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = hud
spec.loader.exec_module(hud)

VRAM = re.compile(r"VRAM 0x([0-9a-fA-F]+) write -> 0x([0-9a-fA-F]+) \(([0-9a-fA-F]+)\)")


def read_markers(lines, manifest):
    start, end = manifest["trace_pc_start"] & 0xFFFF, manifest["trace_pc_end"] & 0xFFFF
    words, markers = [], []
    for line_no, line in enumerate(lines, 1):
        match = VRAM.search(line)
        if not match:
            continue
        address, value, pc = (int(v, 16) for v in match.groups())
        if not start <= (pc & 0xFFFF) <= end:
            continue
        if address != 2 * len(words):
            raise ValueError(f"incomplete dispatcher marker at log line {line_no}")
        words.append(value)
        if len(words) == 8:
            if words[:2] != [0x504C, 0x5354] or words[-1] != 0x454E:
                raise ValueError("invalid dispatcher marker signature")
            markers.append(dict(index=words[2], cycle=(words[3] << 16) | words[4],
                                visit=(words[5] << 16) | words[6], log_line=line_no))
            words = []
    if words or not markers:
        raise ValueError("missing or truncated dispatcher markers")
    for ordinal, marker in enumerate(markers):
        count = len(manifest["items"])
        expected = (ordinal % count, ordinal // count, ordinal + 1)
        if (marker["index"], marker["cycle"], marker["visit"]) != expected:
            raise ValueError(f"wrong playlist progression: {marker}, expected {expected}")
    return markers


def analyze(recording: Path, full_log: Path, manifest_path: Path, min_cycles: int, capture_receipt: Path | None = None):
    manifest = json.loads(manifest_path.read_text())
    if capture_receipt is not None:
        binding = json.loads(capture_receipt.read_text())
        for name, path in (("recording", recording), ("full_log", full_log), ("manifest", manifest_path)):
            if Path(binding[name]).resolve() != path.resolve() or binding[name + "_sha256"] != playlist_build.digest(path):
                raise ValueError(f"capture receipt does not match {name}")
        if binding["iso_sha256"] != manifest["iso_sha256"]:
            raise ValueError("capture receipt belongs to another ISO")
    if manifest["debug"] != 1:
        raise ValueError("playlist HUD qualification requires a DEBUG manifest")
    items = manifest["items"]
    profiles = [encode_config.load_profile(item["effective_profile"]) for item in items]
    for profile, item in zip(profiles, items):
        if profile.sha256 != item["profile_sha256"]:
            raise ValueError("effective profile changed since ISO build")
    print("Checking dispatcher markers in the complete trace", flush=True)
    with gzip.open(full_log, "rt", errors="strict") as trace:
        markers = read_markers(trace, manifest)
    print(f"Verified {len(markers)} ordered dispatcher markers; decoding native HUD", flush=True)
    probe = hud.probe_video(recording)
    if (probe.width, probe.height) != (320, 224):
        raise ValueError("playlist HUD requires native 320x224 recording")
    with resource_tokens.acquire_tokens("cpu", count=1):
        raw = hud.group_samples(hud.iter_samples(recording, probe, 0.90, 0), 3)
    groups = hud.select_movie_groups(raw, 4, 4)
    print(f"Decoded {len(groups)} movie-frame groups; qualifying every visit", flush=True)
    visits = []
    for group in groups:
        while len(visits) <= group.loop:
            visits.append([])
        visits[group.loop].append(dataclasses.replace(group, loop=0))
    failures = []
    if len(markers) != len(visits):
        failures.append(f"dispatcher/HUD visit mismatch: {len(markers)} vs {len(visits)}")
    results, boundary_rows = [], []
    for ordinal, visit in enumerate(visits):
        if ordinal >= len(markers):
            break
        marker = markers[ordinal]
        item = items[marker["index"]]
        profile = profiles[marker["index"]]
        complete = [g.values["frame"] for g in visit] == list(range(item["frames"]))
        # Only the final capture tail may be incomplete. Still prove its frame0.
        tail = ordinal == len(visits) - 1 and not complete
        if tail:
            if not visit or visit[0].values["frame"] != 0:
                failures.append("final visit has no frame0")
            results.append(dict(**marker, id=item["id"], complete=False,
                                observed_frames=len(visit), frame0_capture=visit[0].capture_first))
        else:
            result = hud.evaluate_upload_gate(visit, item["frames"], recording, item["fps"], profile)
            result["playlist_context"] = dict(**marker, id=item["id"],
                manifest=str(manifest_path.resolve()), manifest_sha256=playlist_build.digest(manifest_path),
                iso_sha256=manifest["iso_sha256"], full_log=str(full_log.resolve()))
            result["ocr_start_anchor"] = {
                "method": "dispatcher_marker_and_frame_sequence",
                "frame0_capture_first": visit[0].capture_first,
                "frame0_time_first_s": visit[0].time_first,
                "frame0_time_last_s": visit[0].time_last,
            }
            tsv = analysis_logs.unique_tsv_path(profile, kind=f"visit{ordinal + 1:04d}_hud")
            hud.write_tsv(tsv, visit, hud.transition_indices(visit))
            gate_path = tsv.with_name(tsv.stem + "_gate.json")
            hud.write_gate_json(gate_path, result)
            print(hud.format_cd_wait_statistics(result["cd_wait_statistics"]), flush=True)
            print(hud.format_adpcm_decode_statistics(result["adpcm_decode_statistics"]), flush=True)
            if result["gate"] != "PASS":
                failures.append(f"visit {ordinal + 1} ({item['id']}): HUD FAIL")
            results.append(dict(**marker, id=item["id"], complete=complete, gate=result["gate"],
                                hud_tsv=str(tsv), hud_gate=str(gate_path),
                                frame0_capture=visit[0].capture_first))
        if ordinal:
            previous = visits[ordinal - 1]
            boundary_rows.append(dict(cycle=marker["cycle"], visit=marker["visit"],
                previous_item=items[markers[ordinal - 1]["index"]]["id"], next_item=item["id"],
                previous_last_frame=previous[-1].values["frame"],
                previous_last_capture=previous[-1].capture_last,
                next_frame0_capture=visit[0].capture_first,
                last_observed_to_frame0_seconds=visit[0].time_first - previous[-1].time_last))
    completed = sum(bool(result.get("complete")) for result in results)
    required = min_cycles * len(items)
    if completed < required or len(boundary_rows) < required:
        failures.append(f"need {min_cycles} cycles and next frame0: completed={completed}, boundaries={len(boundary_rows)}")
    path = analysis_logs.unique_tsv_path(profiles[0], kind="playlist_boundaries")
    with path.open("w", newline="") as target:
        fields = ["cycle", "visit", "previous_item", "next_item", "previous_last_frame",
                  "previous_last_capture", "next_frame0_capture", "last_observed_to_frame0_seconds"]
        writer = csv.DictWriter(target, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(boundary_rows)
    result = dict(schema_version=1, gate="FAIL" if failures else "PASS", failures=failures,
                  capture_receipt=str(capture_receipt.resolve()) if capture_receipt else None,
                  minimum_cycles=min_cycles, completed_visits=completed, boundaries=len(boundary_rows),
                  recording=str(recording.resolve()), recording_sha256=playlist_build.digest(recording),
                  full_log=str(full_log.resolve()), full_log_sha256=playlist_build.digest(full_log),
                  manifest=str(manifest_path.resolve()), manifest_sha256=playlist_build.digest(manifest_path),
                  iso_sha256=manifest["iso_sha256"], boundary_tsv=str(path), visits=results)
    gate_path = path.with_name(path.stem + "_gate.json")
    gate_path.write_text(json.dumps(result, indent=2) + "\n")
    print(f"PLAYLIST_GATE={gate_path}\nPLAYLIST_RESULT={result['gate']}", flush=True)
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("recording", type=Path)
    parser.add_argument("full_log", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--min-cycles", type=int, default=1)
    parser.add_argument("--capture-receipt", type=Path)
    args = parser.parse_args()
    if args.min_cycles < 1:
        parser.error("--min-cycles must be positive")
    return analyze(args.recording, args.full_log, args.manifest, args.min_cycles, args.capture_receipt)


if __name__ == "__main__":
    raise SystemExit(main())
