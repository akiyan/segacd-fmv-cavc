"""Read the first HUD row from LOGVDP stdin into a diagnostic TSV."""

import argparse
import csv
import re
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--frames", type=int, default=65535)
args = parser.parse_args()
if not 1 <= args.frames <= 83520:
    parser.error("frames must be 1..83520")

row = []
writer = csv.writer(sys.stdout, delimiter="\t", lineterminator="\n")
writer.writerow(("loop", "frame", "palette_low4", "sector_slip", "control_desync",
                 "audio_resync", "audio_lead_256b"))
previous = None
loop = 0
for line in sys.stdin:
    match = re.search(r"VRAM 0x([0-9a-f]+) write -> 0x([0-9a-f]+)", line)
    if not match:
        continue
    address, word = (int(value, 16) for value in match.groups())
    if address == 0xf000:
        row = []
    if address != 0xf000 + len(row) * 2 or not 1744 <= (word & 0x7ff) < 1760:
        row = []
        continue
    row.append(word & 15)
    if len(row) == 10:
        frame = int("".join(format(value, "x") for value in row[:4]), 16)
        if frame == 65535 and (previous is None
                or (previous + 1) % args.frames != 65535):
            continue  # startup sentinel; a real frame 65535 follows frame 65534
        if previous is not None:
            if frame == 0 and previous == args.frames - 1:
                loop += 1
            else:
                frame |= previous & ~65535
                if frame < previous:
                    frame += 65536
        writer.writerow((loop, frame, *row[4:8], row[8] * 16 + row[9]))
        previous = frame
