#!/usr/bin/env python3
"""Extract per-frame Pass2/CD workload from a packed TTRC stream.

For every timed frame this emits the quantities that bound the fixed
VBlank cadence: cell updates, physical pattern loads by source
(Prg/Wr/Dic), cold-run descriptor structure (count, lengths, short
runs), the Main-CPU Pass2 word total, the palette-switch flag, and the
CD slot schedule (control/payload sectors, rate lead).

Supports the current TTRC v25 stream, including PSUP v4 variable Word-RAM
preload capacities.  The fixed per-frame audio size from HEADER.DAT locates
the cold-run suffix: `n_runs`, then the run descriptors. The descriptors are
cross-validated against the update entries. The low byte of `n_runs` can also
be checked against the DEBUG HUD `cold_runs` column of a recording of the same
stream.

Usage:
  tools/python.sh harness/cold_cap_model/extract_frames.py \
      out/sonic-jam-op-h40 --tsv /tmp/frames_175.tsv
"""

from __future__ import annotations

import argparse
import csv
import struct
import sys
from dataclasses import dataclass
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
sys.path.insert(0, str(TOOLS_DIR))

import av_config  # noqa: E402
import ima_adpcm  # noqa: E402
import player_constants  # noqa: E402

SECTOR = 2048
ROUTING_TOTAL_MAX = 5
FEATURE_COLD_RUNS = 0x0001
FEATURE_VBLANK_CADENCE = 0x0002
FEATURE_PATTERN_SUPPLY = 0x0008
FEATURE_SHADOW_UPDATE_LISTS = 0x0010
FEATURE_VRAM_RAW_PREFETCH = 0x0020
ADPCM_TABLE_SECTORS = 5
SHADOW_UPDATE_LIST_TAG = 0x8000
SHADOW_FRAME_TYPE_MASK = 0x6000
SHADOW_FRAME_TYPE_SHIFT = 13
SHADOW_FRAME_TYPE_RESERVED = 3
SHADOW_UPDATE_COUNT_MASK = 0x1FFF
INLINE_CRAM_BYTES = 128
WORDS_PER_PATTERN = 16
SHORT_RUN_MAX_WORDS = 32
VERSION = 25
CONTROL_SUFFIX_HEADER_BYTES = 2

SOURCE_NAMES = ("prg", "wr", "dic")


@dataclass
class FrameRow:
    frame: int
    n_upd: int
    use_list: bool
    pal_switch: int          # 0 = none; nonzero = full CRAM replacement
    cold_entries: int        # legacy entries with bit15 (0 for list frames)
    n_runs: int
    loads_total: int         # sum of run counts (= physical pattern loads)
    loads_prg: int
    loads_wr: int
    loads_dic: int
    pass2_words: int         # loads_total * 16
    short_runs: int          # runs of <= SHORT_RUN_MAX_WORDS words
    max_run_words: int
    control_bytes: int
    n_ctrl_sec: int
    n_pay_sec: int
    slot_sec: int            # actual physical sectors in this frame's slot
    rated_sec: int           # nominal CD-1x allowance this frame
    lead_sec: int            # cumulative delivery lead after this frame


def die(msg: str) -> None:
    raise AssertionError(msg)


def pattern_supply_sectors(header: bytes, version: int, features: int) -> int:
    if version < 10 or not features & FEATURE_PATTERN_SUPPLY:
        return 0
    values = player_constants.PATTERN_SUPPLY_STRUCT.unpack_from(
        header, player_constants.PATTERN_SUPPLY_OFFSET)
    magic, supply_version, reserved = values[:3]
    if (magic != player_constants.PATTERN_SUPPLY_MAGIC
            or supply_version not in (
                1, 2, player_constants.PATTERN_SUPPLY_VERSION)
            or reserved):
        die(f"invalid pattern-supply extension: {values!r}")
    wr0_sec, wr1_sec, dic_sec = values[6:9]
    return wr0_sec + wr1_sec + dic_sec


def decode_routes(routing: bytes, nframes: int) -> list[tuple[int, int]]:
    if not nframes or routing[0] != 0:
        die("v7+ frame 0 routing entry must be zero")
    routes = []
    for frame, packed in enumerate(routing[:nframes]):
        # bits 6-7 carry the WordBuf payload prefix; ctrl bit 2 is the
        # 4-sector escape (base 3 in the word field).
        n_word = (packed >> 6) & 3
        ctrl_field = packed & 0x07
        n_ctrl = ctrl_field
        if ctrl_field & 4:
            if n_word != 3:
                die(f"frame {frame}: WordBuf-4 escape lacks base 3 in 0x{packed:02X}")
            n_ctrl = ctrl_field & 3
            n_word = 4
        total = (packed >> 3) & 0x07
        if total > ROUTING_TOTAL_MAX or n_ctrl > total or n_word > total - n_ctrl:
            die(f"frame {frame}: bad routing entry 0x{packed:02X}")
        routes.append((total - n_ctrl, n_ctrl))
    return routes


def decode_run_words(raw: bytes, pos: int, k: int, pool: int,
                     seq: int) -> list[tuple[int, int, int, int]] | None:
    """Decode k descriptors at pos; None when any descriptor is invalid."""
    runs = []
    for i in range(k):
        w0, w1 = struct.unpack_from(">HH", raw, pos + i * 4)
        slot = w0 & 0x07FF
        count = w1 & 0x07FF
        source = (w1 >> 14) & 0x3
        dic_idx = ((w0 >> 11) & 0x1F) << 3 | ((w1 >> 11) & 0x7)
        if source == 3:
            # Dic 512: source 3 is Dic with the index biased by 256.
            source = 2
            dic_idx += 256
        if count == 0 or slot + count > pool:
            return None
        if source != 2 and dic_idx:
            return None
        runs.append((slot, count, source, dic_idx))
    return runs


def parse_runs_at(raw: bytes, seq: int, pool: int,
                  suffix_pos: int) -> list[tuple[int, int, int, int]]:
    """Decode the suffix at a known position and require an exact fit."""
    if suffix_pos + CONTROL_SUFFIX_HEADER_BYTES > len(raw):
        die(f"frame {seq}: run suffix is truncated")
    k = struct.unpack_from(">H", raw, suffix_pos)[0]
    descriptor_pos = suffix_pos + CONTROL_SUFFIX_HEADER_BYTES
    if descriptor_pos + 4 * k != len(raw):
        die(f"frame {seq}: suffix at {suffix_pos} with n_runs={k} "
            f"does not end the {len(raw)}-byte block")
    runs = decode_run_words(raw, descriptor_pos, k, pool, seq)
    if runs is None:
        die(f"frame {seq}: invalid run descriptor in positional parse")
    return runs


def parse_frame(raw: bytes, seq: int, cells: int, pool: int,
                features: int, audio_control_bytes: int) -> FrameRow:
    total_len, packed_seq, raw_count = struct.unpack_from(">HHH", raw)
    if total_len != len(raw):
        die(f"frame {seq}: total_len {total_len} != {len(raw)}")
    if packed_seq != seq & 0xFFFF:
        die(f"frame {seq}: packed sequence is {packed_seq}")
    n_upd = raw_count & SHADOW_UPDATE_COUNT_MASK
    use_list = bool(raw_count & SHADOW_UPDATE_LIST_TAG)
    frame_type = (
        raw_count & SHADOW_FRAME_TYPE_MASK) >> SHADOW_FRAME_TYPE_SHIFT
    if n_upd > cells:
        die(f"frame {seq}: n_upd {n_upd} exceeds {cells} cells")
    if frame_type == SHADOW_FRAME_TYPE_RESERVED:
        die(f"frame {seq}: reserved frame type")
    if frame_type and (n_upd or use_list):
        die(f"frame {seq}: fade control carries updates")
    pos = 6

    cold_entries: int | None = None
    if frame_type:
        pos += INLINE_CRAM_BYTES
    elif use_list:
        pos += n_upd * 4
    else:
        bitmap_len = (cells + 7) // 8
        entries_pos = (pos + bitmap_len + 1) & ~1
        if any(raw[pos + bitmap_len:entries_pos]):
            die(f"frame {seq}: bitmap alignment pad is nonzero")
        entries = struct.unpack_from(f">{n_upd}H", raw, entries_pos)
        cold_entries = sum(1 for e in entries if e & 0x8000)
        pos = entries_pos + n_upd * 2

    suffix_pos = pos + audio_control_bytes
    if suffix_pos & 1:
        if suffix_pos >= len(raw) or raw[suffix_pos] != 0:
            die(f"frame {seq}: cold-run alignment pad is missing or nonzero")
        suffix_pos += 1
    runs = parse_runs_at(raw, seq, pool, suffix_pos)

    if (not frame_type and not use_list
            and not features & FEATURE_VRAM_RAW_PREFETCH
            and sum(r[1] for r in runs) != cold_entries):
        die(f"frame {seq}: run loads disagree with {cold_entries} cold entries")

    loads = [0, 0, 0]
    short_runs = 0
    max_run_words = 0
    for _slot, count, source, _idx in runs:
        loads[source] += count
        words = count * WORDS_PER_PATTERN
        max_run_words = max(max_run_words, words)
        if words <= SHORT_RUN_MAX_WORDS:
            short_runs += 1
    loads_total = sum(loads)
    row = FrameRow(
        frame=seq, n_upd=n_upd, use_list=use_list,
        pal_switch=int(bool(frame_type)),
        cold_entries=cold_entries if cold_entries is not None else -1,
        n_runs=len(runs),
        loads_total=loads_total,
        loads_prg=loads[0], loads_wr=loads[1], loads_dic=loads[2],
        pass2_words=loads_total * WORDS_PER_PATTERN,
        short_runs=short_runs, max_run_words=max_run_words,
        control_bytes=total_len, n_ctrl_sec=0, n_pay_sec=0,
        slot_sec=0, rated_sec=0, lead_sec=0,
    )
    return row


def read_pack(pack_dir: Path) -> tuple[list[FrameRow], dict]:
    header = (pack_dir / "HEADER.DAT").read_bytes()
    body = (pack_dir / "BODY.DAT").read_bytes()
    magic, version, nfr, cols, rows, cells, pool = struct.unpack_from(
        ">4sHHHHHH", header)
    if magic != b"TTRC" or version != VERSION:
        die(f"expected TTRC v{VERSION}, got {magic!r} v{version}")
    if cols * rows != cells:
        die(f"grid {cols}x{rows} != {cells} cells")
    routing_sec = struct.unpack_from(">L", header, 26)[0]
    prebuf_sec = struct.unpack_from(">L", header, 30)[0]
    f0_ctrl_sec, f0_pat_sec, paltab_sec = struct.unpack_from(">LLL", header, 40)
    vsync_n = struct.unpack_from(">H", header, 52)[0]
    audio_samples = struct.unpack_from(">H", header, 54)[0]
    audio_control_bytes = ima_adpcm.encoded_bytes(audio_samples)
    fps = struct.unpack_from(">H", header, 56)[0] or 15
    audio_preload_sec = struct.unpack_from(">H", header, 60)[0]
    features = struct.unpack_from(">H", header, 62)[0]
    if not features & FEATURE_COLD_RUNS:
        die("stream has no cold-run suffix; nothing to extract")
    table_sec = ADPCM_TABLE_SECTORS
    supply_sec = pattern_supply_sectors(header, version, features)

    frame0_offset = audio_preload_sec * SECTOR
    frame0_len = struct.unpack_from(">H", body, frame0_offset)[0]
    row0 = parse_frame(
        body[frame0_offset:frame0_offset + frame0_len], 0, cells, pool,
        features, audio_control_bytes)
    rows_out = [row0]

    # v25: segment palette switches are the player-embedded PALIDX table written by
    # pack as palidx.bin beside the split stream (frame.u16, segment.u16
    # entries terminated by a 0xFFFF frame sentinel).
    palidx_switches: dict[int, int] = {}
    palidx_path = pack_dir / "palidx.bin"
    if palidx_path.exists():
        palidx = palidx_path.read_bytes()
        for entry in range(len(palidx) // 4):
            frame, seg = struct.unpack_from(">HH", palidx, entry * 4)
            if frame == 0xFFFF:
                break
            palidx_switches[frame] = seg + 1

    routing_offset = (
        1 + paltab_sec + table_sec + supply_sec
    ) * SECTOR
    routes = decode_routes(
        header[routing_offset:routing_offset + routing_sec * SECTOR], nfr)

    if not (version >= 24 and features & FEATURE_VBLANK_CADENCE):
        die("only authoritative v25 VBlank cadence is supported")
    rate_numerators, rate_modulus = av_config.cd_sector_rate_steps(fps)

    accumulator = 0
    lead = 0
    body_pos = (
        audio_preload_sec + f0_ctrl_sec + f0_pat_sec
    ) * SECTOR
    control_stream = bytearray()
    schedule = [(0, 0, 0, 0, 0)]
    for seq in range(1, nfr):
        n_pay, n_ctrl = routes[seq]
        accumulator += rate_numerators[(seq - 1) % len(rate_numerators)]
        rated, accumulator = divmod(accumulator, rate_modulus)
        actual = n_pay + n_ctrl
        sectors = max(actual, rated - lead)
        lead += sectors - rated
        schedule.append((n_pay, n_ctrl, sectors, rated, lead))
        slot = body[body_pos:body_pos + sectors * SECTOR]
        if len(slot) != sectors * SECTOR:
            die(f"frame {seq}: BODY.DAT slot is truncated")
        control_stream += slot[:n_ctrl * SECTOR]
        body_pos += sectors * SECTOR
    if body_pos != len(body):
        die(f"BODY.DAT has {len(body) - body_pos} unrouted trailing bytes")

    control_pos = 0
    for seq in range(1, nfr):
        block_len = struct.unpack_from(">H", control_stream, control_pos)[0]
        if block_len < 8 or block_len & 1:
            die(f"frame {seq}: invalid control length {block_len}")
        row = parse_frame(
            bytes(control_stream[control_pos:control_pos + block_len]),
            seq, cells, pool, features, audio_control_bytes)
        row.pal_switch = palidx_switches.get(seq, row.pal_switch)
        (row.n_pay_sec, row.n_ctrl_sec, row.slot_sec, row.rated_sec,
         row.lead_sec) = schedule[seq]
        rows_out.append(row)
        control_pos = block_len + control_pos

    meta = dict(version=version, nframes=nfr, cells=cells, pool=pool,
                fps=fps, vsync_n=vsync_n, features=features)
    return rows_out, meta


def cross_check_hud(rows: list[FrameRow], hud_tsv: Path) -> None:
    """Verify parsed run-count low bytes against a HUD OCR series."""
    by_frame = {}
    with hud_tsv.open() as fh:
        for rec in csv.DictReader(fh, delimiter="\t"):
            if rec["loop"] != "0":
                continue
            by_frame[int(rec["frame"])] = int(rec["cold_runs"])
    mismatches = []
    checked = 0
    for row in rows:
        hud_cold_runs = by_frame.get(row.frame)
        if hud_cold_runs is None:
            continue
        checked += 1
        if row.n_runs & 0xFF != hud_cold_runs:
            mismatches.append((row.frame, row.n_runs, hud_cold_runs))
    if mismatches:
        for frame, n_runs, hud_cold_runs in mismatches[:10]:
            print(f"  MISMATCH frame {frame}: parsed n_runs={n_runs} "
                  f"HUD cold_runs={hud_cold_runs}", file=sys.stderr)
        die(
            f"{len(mismatches)}/{checked} HUD cold_runs mismatches "
            f"against {hud_tsv}"
        )
    print(
        f"HUD cross-check OK: {checked} frames match cold_runs ({hud_tsv})"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("pack_dir", type=Path,
                    help="directory containing HEADER.DAT + BODY.DAT")
    ap.add_argument("--tsv", type=Path, required=True,
                    help="output TSV path")
    ap.add_argument("--hud-tsv", type=Path,
                    help="optional HUD OCR TSV of the same stream; "
                         "validates parsed n_runs against cold_runs")
    args = ap.parse_args()
    if args.tsv.suffix.lower() != ".tsv":
        ap.error("--tsv output must use the .tsv extension")
    if args.hud_tsv is not None and args.hud_tsv.suffix.lower() != ".tsv":
        ap.error("--hud-tsv input must use the .tsv extension")

    rows, meta = read_pack(args.pack_dir)
    print(f"{args.pack_dir}: TTRC v{meta['version']} frames={meta['nframes']} "
          f"cells={meta['cells']} pool={meta['pool']} "
          f"features=0x{meta['features']:04X}")

    if args.hud_tsv:
        cross_check_hud(rows, args.hud_tsv)

    fields = [f for f in FrameRow.__dataclass_fields__]
    with args.tsv.open("w", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(fields)
        for row in rows:
            writer.writerow([getattr(row, f) for f in fields])
    print(f"wrote {len(rows)} rows -> {args.tsv}")


if __name__ == "__main__":
    main()
