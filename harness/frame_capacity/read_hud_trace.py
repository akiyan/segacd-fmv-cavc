"""Read the first HUD row from a BlastEm BLSTEL trace into diagnostic TSV."""

import argparse
import csv
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "blastem"))
from event_stream import iter_publications


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("trace", type=Path)
    parser.add_argument("--frames", type=int, default=65535)
    args = parser.parse_args()
    if not 1 <= args.frames <= 83520:
        parser.error("frames must be 1..83520")

    writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
    writer.writerow(("loop", "frame", "palette_low4", "sector_slip", "control_desync",
                     "audio_resync", "audio_lead_256b"))
    ordinal = 0
    for publication in iter_publications(args.trace):
        loop, frame = divmod(ordinal, args.frames)
        expected = frame & 0xFFFF
        if publication.frame in (0xFFFE, 0xFFFF) and publication.frame != expected:
            continue
        if publication.frame != expected:
            raise ValueError(f"loop {loop}: HUD {publication.frame:04X}, expected {expected:04X}")
        digits = publication.hud
        writer.writerow((loop, frame, *digits[4:8], (digits[8] << 4) | digits[9]))
        ordinal += 1
    if not ordinal:
        raise ValueError("trace has no movie HUD publications")


if __name__ == "__main__":
    main()
