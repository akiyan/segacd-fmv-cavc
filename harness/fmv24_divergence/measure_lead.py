#!/usr/bin/env python3
"""Measure the pattern-supply lead per frame from the recording itself.

For each sampled frame, exact-match every freshly-updated cell's recorded
content (quantized back to RGB333 through the emulator ramp) against the
frame's own unique-pattern sequence, and report how many positions ahead the
delivered pattern was. A clean player reports lead 0 everywhere.
"""
from __future__ import annotations

import argparse
import pickle
import tempfile
from pathlib import Path

import numpy as np

from scan_divergence import load_capture_index, extract_capture

RAMP = np.array([0, 34, 69, 101, 138, 170, 207, 239], np.int16)


def to_idx(img: np.ndarray) -> np.ndarray:
    d = np.abs(img[..., None].astype(np.int16) - RAMP[None, None, None, :])
    return d.argmin(axis=-1).astype(np.uint8)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("decisions", type=Path)
    parser.add_argument("hud_tsv", type=Path)
    parser.add_argument("lossless", type=Path)
    parser.add_argument("--frames", type=int, nargs="+", required=True)
    args = parser.parse_args()

    dec = pickle.load(args.decisions.open("rb"))
    tcols, trows, cells, _ = dec["geom"]
    frame_seg = np.asarray(dec["frame_seg"])
    seg_pals = np.asarray(dec["seg_pals"])
    caps = load_capture_index(args.hud_tsv)
    h, w = trows * 8, tcols * 8

    with tempfile.TemporaryDirectory() as tmp:
        png = Path(tmp) / "c.png"
        for frame in args.frames:
            rec = extract_capture(args.lossless, caps[frame], png)
            rec = rec[(rec.shape[0] - h) // 2:, (rec.shape[1] - w) // 2:][:h, :w]
            rc = to_idx(rec).reshape(h // 8, 8, w // 8, 8, 3).transpose(0, 2, 1, 3, 4)
            fp3 = np.zeros((4, 16, 3), np.uint8)
            fp3[:, 1:] = seg_pals[int(frame_seg[frame])]
            seen: dict[bytes, int] = {}
            uniq_pos: list[bytes] = []
            entries = []
            for cell, pal, key in dec["frames"][frame]:
                if key not in seen:
                    seen[key] = len(uniq_pos)
                    uniq_pos.append(key)
                entries.append((int(cell), int(pal), key))
            pattern_rgb = {
                key: fp3[pal][np.frombuffer(key, np.uint8)].reshape(8, 8, 3).tobytes()
                for cell, pal, key in entries
            }
            rgb_to_pos = {}
            for key, pos in seen.items():
                cell_pal = next(p for c, p, k in entries if k == key)
                rgb = fp3[cell_pal][np.frombuffer(key, np.uint8)].reshape(8, 8, 3)
                rgb_to_pos.setdefault(rgb.tobytes(), pos)
            leads = []
            unmatched = 0
            for cell, pal, key in entries:
                r, c = divmod(cell, tcols)
                content = np.ascontiguousarray(rc[r, c]).astype(np.uint8).tobytes()
                got = rgb_to_pos.get(content)
                want = seen[key]
                if got is None:
                    unmatched += 1
                    continue
                leads.append((want, got - want))
            if leads:
                leads.sort()
                zero = sum(1 for _w, l in leads if l == 0)
                nonzero = [(w, l) for w, l in leads if l != 0]
                head = nonzero[:3]
                tail = nonzero[-3:]
                print(
                    f"f{frame}: updates={len(entries)} matched={len(leads)} "
                    f"lead0={zero} shifted={len(nonzero)} unmatched={unmatched} "
                    f"first_shifts={head} last_shifts={tail}")
            else:
                print(f"f{frame}: no matches (updates={len(entries)})")


if __name__ == "__main__":
    main()
