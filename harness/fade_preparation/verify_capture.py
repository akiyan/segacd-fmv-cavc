#!/usr/bin/env python3
"""Match a native HUD-free fixture capture against every committed RGB333 image."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import pickle
import subprocess
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import tmpfs_workspace


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(decision_path, capture, tsv):
    with decision_path.open("rb") as source:
        log = pickle.load(source)
    if tuple(log["geom"]) != (40, 28, 1120, 8):
        raise ValueError("fixture must fill the 320x224 aperture")
    if np.any(log.get("scroll", {}).get("active", False)):
        raise ValueError("fixture must not scroll")
    indices = np.zeros((1120, 64), np.uint8)
    palettes = np.zeros(1120, np.uint8)
    expected = []
    for frame, updates in enumerate(log["frames"]):
        for cell, palette, key in updates:
            indices[cell] = np.frombuffer(key, np.uint8)
            palettes[cell] = palette
        cram = np.zeros((4, 16, 3), np.uint8)
        cram[:, 1:] = log["fade"]["active_frame_cram"][frame]
        cells = cram[palettes[:, None], indices]
        image = cells.reshape(28, 40, 8, 8, 3).transpose(0, 2, 1, 3, 4)
        expected.append(digest(image.tobytes()))
    probe = json.loads(subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_streams",
        "-of", "json", str(capture)]))["streams"][0]
    if (probe["width"], probe["height"]) != (320, 224):
        raise ValueError("capture must be native 320x224")
    process = subprocess.Popen([
        "ffmpeg", "-v", "error", "-i", str(capture), "-map", "0:v:0",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"], stdout=subprocess.PIPE)
    matches = [[] for _ in expected]
    lookup = {}
    for frame, key in enumerate(expected):
        lookup.setdefault(key, []).append(frame)
    capture_index = 0
    with tsv.open("w", encoding="utf-8", newline="") as target:
        writer = csv.writer(target, delimiter="\t", lineterminator="\n")
        writer.writerow(("capture_frame", "matching_movie_frames", "rgb333_sha256"))
        while True:
            raw = process.stdout.read(320 * 224 * 3)
            if not raw:
                break
            if len(raw) != 320 * 224 * 3:
                raise ValueError("truncated capture frame")
            # Native GPGX normal-intensity RGB levels map back to RGB333.
            pixels = np.frombuffer(raw, np.uint8).astype(np.float32)
            key = digest(np.rint(pixels * (7 / 255)).astype(np.uint8).tobytes())
            frames = lookup.get(key, [])
            for frame in frames:
                matches[frame].append(capture_index)
            if frames:
                writer.writerow((capture_index, ",".join(map(str, frames)), key))
            capture_index += 1
    if process.wait():
        raise ValueError("capture decode failed")
    missing = [frame for frame, indices in enumerate(matches) if not indices]
    # Require an ordered pass; identical holds and black frames can share a
    # capture image, but a later unique frame must occur after the prior one.
    cursor = 0
    for frame, indices in enumerate(matches):
        later = [index for index in indices if index >= cursor]
        if not later:
            raise ValueError(f"no ordered capture match at movie frame {frame}; missing={missing}")
        cursor = later[0]
    result = dict(frames=len(expected), exact_rgb333_frames=len(expected)-len(missing),
                  capture_frames=capture_index, decision_sha256=digest(decision_path.read_bytes()),
                  capture=str(capture.resolve()), tsv=str(tsv.resolve()))
    tsv.with_suffix(".json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("capture", type=Path)
    parser.add_argument("--tsv", type=Path, required=True)
    args = parser.parse_args()
    leases = [tmpfs_workspace.lease_managed_path(path)
              for path in (args.decisions, args.capture)]
    try:
        verify(args.decisions, args.capture, args.tsv)
    finally:
        for lease in leases:
            if lease is not None:
                lease.release()
