#!/usr/bin/env python3
"""Check actual VRAM writes around the first complete movie loop in LOGVDP."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import ExitStack
import csv
import gzip
import hashlib
import json
import pickle
from pathlib import Path
import re
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gpgx_logvdp"))
from extract_frame_tsv import DMA_RE, dma_events, infer_dma_pcs, log_lines
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from tmpfs_workspace import lease_managed_path

# LOGVDP prints address before 'write ->', followed by the data word.
WRITE = re.compile(r"\[\d+\((\d+)\)\]\[\d+\(\d+\)\] "
                   r"(VRAM|CRAM) 0x([0-9a-fA-F]+) write ->")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("compact", type=Path)
    ap.add_argument("full", type=Path)
    ap.add_argument("--frames", type=int, required=True)
    ap.add_argument("--tsv", type=Path, required=True)
    ap.add_argument("--sim-out", type=Path, help="matching completed SIM; required for scrolling movies")
    args = ap.parse_args()
    with ExitStack() as leases:
        for path in (args.compact, args.full, *([args.sim_out] if args.sim_out else [])):
            lease = lease_managed_path(path)
            if lease:
                leases.callback(lease.release)
        check(args)


def check(args):
    events = dma_events(log_lines(args.compact))
    expected_final = None
    if args.sim_out:
        with (args.sim_out / "decisions.pkl").open("rb") as source:
            decisions = pickle.load(source)
        if len(decisions["frames"]) != args.frames:
            raise SystemExit("SIM frame count differs")
        cols, height, _, _ = decisions["geom"]
        nt_words = (height - 1) * 64 + cols
        nt_counts = Counter(pc for typ, _, _, _, count, pc in events
                            if typ == 1 and count == nt_words)
        if not nt_counts:
            raise SystemExit("no movie-table DMA site")
        nt_pc = nt_counts.most_common(1)[0][0]
        nt_lengths = np.full(args.frames, nt_words)
        scroll = decisions.get("scroll") or {}
        for i, active in enumerate(scroll.get("active", [])):
            if active:
                nt_lengths[i] = (32 if scroll["positions"][i][1] else height) * 64
        expected_final = decisions["pattern_transfers"].get("final_vblank_tiles")
    else:
        _, nt_pc, nt_words, _ = infer_dma_pcs(events, args.frames)
        nt_lengths = np.full(args.frames, nt_words)
    fields = ("frame", "pattern_active_words", "pattern_blank_words",
              "final_active_words", "final_blank_words", "final_edge_words",
              "nt_active_words", "nt_blank_words", "nt_edge_words",
              "display_active_words", "display_blank_words", "display_edge_words")
    rows = [dict.fromkeys(fields, 0) for _ in range(args.frames)]
    for i, row in enumerate(rows):
        row["frame"] = i
    upcoming, displayed, nt_written = 0, -1, 0
    with gzip.open(args.full, "rt", errors="replace") as source:
        for line in source:
            if "DMA type " in line:
                m = DMA_RE.search(line)
                if (m and int(m[1]) == 1 and int(m[5]) == nt_lengths[min(upcoming, args.frames-1)]
                        and int(m[6], 16) & 0xFFFF == nt_pc):
                    displayed = upcoming
                    upcoming += 1
                    nt_written = 0
                    if displayed >= args.frames:
                        break
                continue
            if " write -> " not in line:
                continue
            m = WRITE.search(line)
            if not m:
                continue
            v, kind, addr = int(m[1]), m[2], int(m[3], 16)
            if (displayed == args.frames - 1 and nt_written == nt_lengths[displayed]
                    and kind == "VRAM" and (addr < 0xDA00 or 0xE000 <= addr < 0xF000)):
                break  # Next-loop clearing, after this frame's HUD and CRAM.
            phase = "blank" if 224 <= v <= 260 else (
                "edge" if v in (223, 261) else "active")
            if (0 <= displayed < args.frames and (kind == "CRAM" or
                    0xDC00 <= addr < 0xDE80 or 0xF000 <= addr < 0xF050)):
                rows[displayed][f"display_{phase}_words"] += 1
            elif kind == "VRAM" and 0x20 <= addr < 0xDA00 and 0 < upcoming < args.frames:
                row = rows[upcoming]
                if phase != "edge":
                    row[f"pattern_{phase}_words"] += 1
                if addr >= 0xD880:
                    row[f"final_{phase}_words"] += 1
            elif 0xE000 <= addr < 0xF000 and 0 <= displayed < args.frames:
                rows[displayed][f"nt_{phase}_words"] += 1
                nt_written += 1
    if upcoming < args.frames:
        raise SystemExit(f"incomplete movie: {upcoming}/{args.frames} NT markers")
    if any(sum(row[f"nt_{p}_words"] for p in ("active", "blank", "edge"))
           != nt_lengths[row["frame"]] for row in rows):
        raise SystemExit("incomplete or unexpected movie-table writes")
    if expected_final is not None:
        for row, tiles in zip(rows[1:], expected_final[1:]):
            actual = sum(row[f"final_{p}_words"] for p in ("active", "blank", "edge"))
            if actual != int(tiles) * 16:
                raise SystemExit(f"frame {row['frame']}: final-tail writes {actual} != {int(tiles)*16}")
    with args.tsv.open("w", newline="") as target:
        writer = csv.DictWriter(target, fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    totals = {key: sum(row[key] for row in rows[1:]) for key in fields[1:]}
    # Ambiguous edge writes cannot establish a complete publication blank.
    bad = [row for row in rows[1:] if any(row[key] for key in (
        "final_active_words", "final_edge_words", "nt_active_words", "nt_edge_words",
        "display_active_words", "display_edge_words"))]
    receipt = dict(compact=str(args.compact.resolve()), full=str(args.full.resolve()),
                   frames=args.frames, nt_pc=nt_pc, nt_words=nt_words,
                   totals=totals, failing_frames=bad, passed=not bad)
    if args.sim_out:
        receipt["sim_out"] = str(args.sim_out.resolve())
        with (args.sim_out / "decisions.pkl").open("rb") as source:
            receipt["decisions_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    for key, path in (("compact", args.compact), ("full", args.full)):
        with path.open("rb") as source:
            receipt[f"{key}_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
    args.tsv.with_suffix(".json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))
    raise SystemExit(bool(bad))


if __name__ == "__main__":
    main()
