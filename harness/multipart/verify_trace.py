#!/usr/bin/env python3
"""Check multipart dispatch and actual VDP output against independent SIM decisions.

This diagnostic supports non-scrolling DEBUG movies. It is not a recording or
hardware qualification gate. No assembly algorithm is reimplemented here.
"""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import pickle
import re
import struct
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import encode_config
import resource_tokens
import tmpfs_workspace
from multipart import digest, write_json

WRITE = re.compile(r"(VRAM|CRAM) 0x([0-9a-f]+) write -> 0x([0-9a-f]+) \(([0-9a-f]+)\)")


def pixel_hash(colors):
    return hashlib.sha256(np.asarray(colors, dtype=">u2").tobytes()).hexdigest()


def expected_frames(item):
    profile = encode_config.load_profile(item["profile"])
    if profile.sha256 != item["profile_sha256"]:
        raise ValueError("part profile changed since the ISO was built")
    path = profile.decision_log
    lease = tmpfs_workspace.lease_managed_path(path)
    if lease is None:
        raise ValueError(f"completed SIM is unavailable: {path}")
    try:
        with path.open("rb") as source:
            decisions = pickle.load(source)
    finally:
        lease.release()
    if decisions["config"]["profile"]["sha256"] != profile.sha256:
        raise ValueError("SIM belongs to a different part profile")
    if np.any(decisions.get("scroll", {}).get("active", False)):
        raise ValueError("this diagnostic requires a non-scrolling part")
    columns, rows, cells, tile = decisions["geom"]
    if tile != 8 or cells != columns * rows or len(decisions["frames"]) != item["frames"]:
        raise ValueError("SIM geometry/frame count differs")
    indices = np.zeros((cells, 64), np.uint8)
    palettes = np.zeros(cells, np.uint8)
    expected = []
    for frame, updates in enumerate(decisions["frames"]):
        for cell, palette, key in updates:
            indices[cell] = np.frombuffer(key, np.uint8)
            palettes[cell] = palette
        rgb = np.zeros((4, 16, 3), np.uint16)
        rgb[:, 1:] = decisions["fade"]["active_frame_cram"][frame]
        cram = rgb[..., 0] | (rgb[..., 1] << 3) | (rgb[..., 2] << 6)
        expected.append(pixel_hash(cram[palettes[:, None], indices]))
    return columns, rows, expected, digest(path)


def verify(manifest, trace, tsv):
    expected = [expected_frames(item) for item in manifest["items"]]
    count = len(expected)
    vram = bytearray(65536)
    cram = np.zeros(64, np.uint16)
    marker, hud, visits, rows = [], [], [], []
    pending = None

    def finish_frame():
        nonlocal pending
        if pending is None:
            return
        frame, digits = pending
        visit = visits[-1]
        columns, height, hashes, _ = expected[visit["index"]]
        entries = np.frombuffer(vram, ">u2", count=2048, offset=0xE000).reshape(32, 64)
        x, y = (40-columns)//2, (28-height)//2
        entries = entries[y:y+height, x:x+columns].reshape(-1)
        patterns = np.frombuffer(vram, np.uint8).reshape(2048, 32)[entries & 0x7FF]
        indices = np.stack((patterns >> 4, patterns & 15), axis=2).reshape(-1, 8, 8)
        indices = np.where((entries & 0x800)[:, None, None], indices[:, :, ::-1], indices)
        indices = np.where((entries & 0x1000)[:, None, None], indices[:, ::-1, :], indices)
        colors = cram[((entries >> 13) & 3)[:, None]*16 + indices.reshape(-1, 64)]
        actual = pixel_hash(colors)
        if actual != hashes[frame]:
            raise ValueError(f"VDP pixels differ: visit {len(visits)}, frame {frame}")
        if digits[5:8] != [0, 0, 0]:
            raise ValueError(f"recovery counters: visit {len(visits)}, frame {frame}: {digits[5:8]}")
        rows.append((len(visits), visit["index"]+1, visit["cycle"], frame, *digits[5:8], actual))
        visit["frames"] += 1
        pending = None

    with gzip.open(trace, "rt", errors="strict") as source:
        for line in source:
            match = WRITE.search(line) if " write -> " in line else None
            if match is None:
                continue
            kind, *numbers = match.groups()
            address, word, pc = map(lambda value: int(value, 16), numbers)
            # The core can sign-extend an absolute-short Main PC and reports
            # the PC after the writing instruction, including the final one.
            pc &= 0xFFFFFF
            if manifest["trace_pc_start"] <= pc <= manifest["trace_pc_end"] and kind == "VRAM":
                if address == 0:
                    finish_frame()
                if address != len(marker)*2:
                    raise ValueError("incomplete multipart dispatcher marker")
                marker.append(word)
                if len(marker) == 8:
                    if marker[:2] != [0x4D50, 0x5254] or marker[-1] != 0x454E:
                        raise ValueError("invalid multipart dispatcher signature")
                    index, cycle, visit = marker[2], (marker[3]<<16)|marker[4], (marker[5]<<16)|marker[6]
                    ordinal = len(visits)
                    if (index, cycle, visit) != (ordinal % count, ordinal // count, ordinal+1):
                        raise ValueError("wrong multipart playback order")
                    if visits and visits[-1]["frames"] != len(expected[visits[-1]["index"]][2]):
                        raise ValueError("part ended without displaying every frame")
                    visits.append(dict(index=index, cycle=cycle, visit=visit, frames=0))
                    print(f"Trace: visit {visit}, part {index+1}, cycle {cycle}", flush=True)
                    marker, hud = [], []
                continue
            if pc & 0xFF0000 != 0xFF0000:
                continue
            if kind == "CRAM":
                cram[(address & 0x7E)//2] = word
                continue
            address &= 0xFFFF
            # HUD precedes this frame's optional CRAM writes. Finish after
            # those writes but before any pattern/NT mutation of the next
            # frame, including a centered raster whose band starts at E080.
            if address < 0xDA00 or 0xE000 <= address < 0xF000:
                finish_frame()
            struct.pack_into(">H", vram, address, word)
            if address == 0xF000:
                hud = []
            if 0xF000 <= address < 0xF050:
                if address == 0xF000+len(hud)*2 and 1744 <= word & 0x7FF < 1760:
                    hud.append(word & 15)
                else:
                    hud = []
                if len(hud) == 40:
                    frame = int("".join(f"{digit:x}" for digit in hud[:4]), 16)
                    next_frame = visits[-1]["frames"] if visits else 0
                    if frame != 0xFFFF or next_frame == 0xFFFF:
                        if not visits or pending is not None or frame != next_frame & 0xFFFF:
                            raise ValueError(f"HUD frame order: {frame} expected {next_frame}")
                        if next_frame >= len(expected[visits[-1]["index"]][2]):
                            raise ValueError("extra movie frame before next part")
                        pending = next_frame, hud
                    hud = []
    finish_frame()
    if marker or len(visits) < count+1 or not visits[count]["frames"]:
        raise ValueError("need one complete cycle and the next part's frame 0")
    with tsv.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, delimiter="\t", lineterminator="\n")
        writer.writerow(("visit", "part", "cycle", "frame", "sector_slip", "control_desync", "audio_resync", "rgb333_sha256"))
        writer.writerows(rows)
    return {"result": "PASS", "visits": visits, "displayed_frames": len(rows),
            "decision_sha256": [item[3] for item in expected], "tsv": str(tsv)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Recheck a retained multipart playback trace")
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads(args.receipt.read_text())
    for key in ("manifest", "trace"):
        if digest(receipt[key]) != receipt[key+"_sha256"]:
            raise ValueError(f"retained {key} differs from the capture receipt")
    manifest = json.loads(Path(receipt["manifest"]).read_text())
    if manifest["iso_sha256"] != receipt["iso_sha256"]:
        raise ValueError("capture receipt belongs to another disc")
    lease = tmpfs_workspace.lease_managed_path(receipt["trace"])
    if lease is None:
        raise ValueError("retained trace must be in its managed artifact")
    try:
        with resource_tokens.acquire_tokens("cpu", count=1):
            receipt.update(verify(manifest, Path(receipt["trace"]), args.receipt.with_suffix(".tsv")))
        receipt.pop("error", None)
        tmpfs_workspace.mark_directory_complete(lease, reuse_token=manifest["iso_sha256"])
    except BaseException as error:
        receipt.update(result="FAIL", error=str(error))
        raise
    finally:
        write_json(args.receipt, receipt)
        lease.release()
    print(f"PASS: {receipt['displayed_frames']} exact displayed frames; {args.receipt}")
