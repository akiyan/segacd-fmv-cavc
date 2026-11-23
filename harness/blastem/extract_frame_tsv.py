#!/usr/bin/env python3
"""Align physical BlastEm VDP writes to the first DEBUG movie loop."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

from event_stream import iter_events, publications


WRITE_COLUMNS = (
    "pattern_vram_write_bytes",
    "name_table_vram_write_bytes",
    "cram_write_bytes",
)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def timed_writes(trace, anchors):
    counts = dict.fromkeys(WRITE_COLUMNS, 0)

    def count_events():
        for event in iter_events(trace):
            start = event.address
            end = start + len(event.data)
            if event.kind == "CRAM":
                counts["cram_write_bytes"] += len(event.data)
            elif event.kind == "VRAM":
                counts["pattern_vram_write_bytes"] += max(0, min(end, 0xDA00) - start)
                counts["name_table_vram_write_bytes"] += max(
                    0, min(end, 0xF000) - max(start, 0xE000))
            yield event

    rows = []
    previous = None
    for publication in publications(count_events()):
        if rows or previous == 0xFFFF and publication.frame == 0:
            frame = len(rows)
            if publication.frame != frame & 0xFFFF or publication.capture_index != anchors[frame]:
                raise ValueError(f"BlastEm publication does not match HUD frame {frame}")
            rows.append({"frame": frame, **counts})
            if len(rows) == len(anchors):
                return rows
        previous = publication.frame
        counts.update(dict.fromkeys(WRITE_COLUMNS, 0))
    raise ValueError("BlastEm trace ended before the complete first HUD loop")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--hud-tsv", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.hud_tsv.suffix != ".tsv" or args.output.suffix != ".tsv":
        parser.error("HUD input and output must have .tsv extensions")
    try:
        with args.hud_tsv.open(encoding="utf-8", newline="") as source:
            hud = [row for row in csv.DictReader(source, delimiter="\t") if row["loop"] == "0"]
        if not hud or [int(row["frame"]) for row in hud] != list(range(len(hud))):
            raise ValueError("HUD TSV requires an ordered first loop starting at frame zero")
        rows = timed_writes(args.trace, [int(row["capture_first"]) for row in hud])
        with args.output.open("w", encoding="utf-8", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=("frame", *WRITE_COLUMNS),
                                    delimiter="\t", lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        receipt = {
            "kind": "blastem-vdp-frame-writes",
            "trace": str(args.trace.resolve()),
            "trace_sha256": digest(args.trace),
            "hud_tsv_sha256": digest(args.hud_tsv),
            "output_tsv_sha256": digest(args.output),
            "frames": len(rows),
        }
        args.output.with_suffix(".tsv.json").write_text(
            json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    except (OSError, KeyError, ValueError) as exc:
        parser.exit(1, f"BlastEm VDP extraction: {exc}\n")
    print(f"BlastEm VDP TSV: {args.output} ({len(rows)} frame publications)")


if __name__ == "__main__":
    main()
