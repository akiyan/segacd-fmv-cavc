#!/usr/bin/env python3
"""Apply the standard publication HUD gate to each actual multipart visit."""
import argparse
import csv
from dataclasses import replace
import gzip
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import encode_config
import resource_tokens
import tmpfs_workspace
from multipart import digest, write_json
from verify_trace import WRITE

spec = importlib.util.spec_from_file_location("multipart_hud", ROOT / "harness/startup_resync/analyze.py")
hud = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = hud
spec.loader.exec_module(hud)


def read_markers(trace, manifest):
    words, markers = [], []
    with gzip.open(trace, "rt", errors="strict") as source:
        for line in source:
            match = WRITE.search(line) if " write -> " in line else None
            if not match:
                continue
            kind, address, value, pc = match.groups()
            pc = int(pc, 16) & 0xFFFFFF
            if kind != "VRAM" or not manifest["trace_pc_start"] <= pc <= manifest["trace_pc_end"]:
                continue
            if int(address, 16) != 2*len(words):
                raise ValueError("incomplete dispatcher marker")
            words.append(int(value, 16))
            if len(words) == 8:
                if words[:2] != [0x4D50, 0x5254] or words[-1] != 0x454E:
                    raise ValueError("invalid multipart dispatcher signature")
                marker = (words[2], (words[3]<<16)|words[4], (words[5]<<16)|words[6])
                ordinal, count = len(markers), len(manifest["items"])
                if marker != (ordinal % count, ordinal // count, ordinal+1):
                    raise ValueError("wrong multipart dispatch order")
                markers.append(marker)
                words = []
    if words or not markers:
        raise ValueError("missing/truncated multipart markers")
    return markers


def analyze(binding, output):
    for name in ("recording", "full_log", "manifest"):
        if digest(binding[name]) != binding[name+"_sha256"]:
            raise ValueError(f"capture binding changed: {name}")
    manifest = json.loads(Path(binding["manifest"]).read_text())
    if not manifest["debug"] or manifest["iso_sha256"] != binding["iso_sha256"]:
        raise ValueError("need this recording's DEBUG manifest")
    recording = Path(binding["recording"])
    markers = read_markers(binding["full_log"], manifest)
    probe = hud.probe_video(recording)
    if (probe.width, probe.height) != (320, 224):
        raise ValueError("multipart HUD qualification requires native 320x224")
    print(f"{len(markers)} ordered dispatcher markers; reading recorded HUD", flush=True)
    raw = hud.group_samples(hud.iter_samples(recording, probe, 0.90, 0), 3)
    groups = hud.select_movie_groups(raw, 4, 4)
    visits = []
    for group in groups:
        while len(visits) <= group.loop:
            visits.append([])
        visits[group.loop].append(replace(group, loop=0))
    failures, results, boundaries = [], [], []
    for ordinal, visit in enumerate(visits):
        if ordinal >= len(markers) or not visit:
            raise ValueError("recorded visit has no matching dispatcher marker")
        index, cycle, number = markers[ordinal]
        item = manifest["items"][index]
        profile = encode_config.load_profile(item["profile"])
        if profile.sha256 != item["profile_sha256"]:
            raise ValueError("part profile changed since capture")
        # Prove actual frame -1 immediately before this visit's frame 0. Do
        # not borrow the anchor from another movie or another recording.
        previous = [g for g in raw if g.capture_last < visit[0].capture_first]
        sentinel = previous[-1] if previous else None
        if (visit[0].values["frame"] != 0 or sentinel is None
                or sentinel.values["frame"] != 0xFFFF):
            failures.append(f"visit {number}: missing frame -1 / frame 0 anchor")
        complete = [g.values["frame"] for g in visit] == list(range(item["frames"]))
        result = dict(part=index+1, cycle=cycle, visit=number, complete=complete,
                      observed_frames=len(visit), frame0_capture=visit[0].capture_first,
                      frame0_time=visit[0].time_first, final_frame_time=visit[-1].time_last)
        if complete or ordinal < len(visits)-1:
            gate = hud.evaluate_upload_gate(visit, item["frames"], recording,
                                             float(profile.section("source")["fps"]), profile)
            gate["multipart_context"] = dict(part=index+1, cycle=cycle, visit=number,
                                               iso_sha256=manifest["iso_sha256"],
                                               manifest_sha256=binding["manifest_sha256"],
                                               full_log_sha256=binding["full_log_sha256"])
            gate["ocr_start_anchor"] = dict(method="recorded_frame_minus_one_and_dispatcher",
                                             frame0_capture_first=visit[0].capture_first,
                                             frame_minus_one_capture_first=(sentinel.capture_first if sentinel else None))
            tsv = output.with_name(output.stem+f"-visit{number:03}.tsv")
            hud.write_tsv(tsv, visit, hud.transition_indices(visit))
            gate_path = tsv.with_suffix(".gate.json")
            hud.write_gate_json(gate_path, gate)
            result.update(gate=gate["gate"], alert=gate["alert"], warnings=gate["warnings"],
                          gate_json=str(gate_path), hud_tsv=str(tsv))
            if gate["gate"] != "PASS":
                failures.append(f"visit {number}: {gate['failures']}")
        results.append(result)
        if ordinal:
            boundaries.append((number, index+1, visits[ordinal-1][-1].time_last,
                               visit[0].time_first, visit[0].time_first-visits[ordinal-1][-1].time_last))
    count = len(manifest["items"])
    if sum(r["complete"] for r in results) < count or len(visits) <= count:
        failures.append("need every part and the next cycle's frame 0")
    # The trace includes the recorder's extra ten-second tail, while the
    # bounded MKV ends earlier. Only its observed visits receive HUD gates.
    boundary_tsv = output.with_suffix(".boundaries.tsv")
    with boundary_tsv.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, delimiter="\t", lineterminator="\n")
        writer.writerow(("visit", "part", "previous_last_time", "frame0_time", "boundary_seconds"))
        writer.writerows(boundaries)
    result = {"gate": "FAIL" if failures else "PASS", "failures": failures,
              "capture": binding, "visits": results, "boundaries_tsv": str(boundary_tsv)}
    write_json(output, result)
    print(f"MULTIPART_RECORDING_GATE={result['gate']} {output}", flush=True)
    if failures:
        raise ValueError("; ".join(failures))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-receipt", type=Path, required=True)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    binding = json.loads(args.capture_receipt.read_text())["captures"]["debug"]
    lease = tmpfs_workspace.lease_managed_path(binding["recording"])
    if lease is None:
        raise ValueError("capture must be in its managed artifact")
    try:
        with resource_tokens.acquire_tokens("cpu", count=1):
            analyze(binding, args.json)
    finally:
        lease.release()
