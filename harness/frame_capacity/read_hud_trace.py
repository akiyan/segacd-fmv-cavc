"""Read the first HUD row from LOGVDP stdin into a diagnostic TSV."""

import csv
import re
import sys

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
        if frame != 65535:
            if previous is not None and frame < previous:
                loop += 1
            writer.writerow((loop, frame, *row[4:8], row[8] * 16 + row[9]))
            previous = frame
