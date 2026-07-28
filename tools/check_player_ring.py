#!/usr/bin/env python3
"""Prove the specialized player's PRG/Word-RAM memory contracts."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import av_config
import ima_adpcm
import pattern_supply
import sp_extension
import ttrc_routing


ROOT = Path(__file__).resolve().parent.parent
SP = ROOT / "boot/movieplay_sp.s"
SP_EXT = ROOT / "boot/movieplay_sp_ext.s"
IP = ROOT / "boot/movieplay_ip.s"
BOOT = ROOT / "boot/movieplay_boot.s"
SP_LD = ROOT / "cfg/sp.ld"
SP_EXT_LD = ROOT / "cfg/sp_ext.ld"
MAKEFILE = ROOT / "Makefile"
QUALIFIED_ADPCM_BOOT_COPY_BYTES = 0x58
QUALIFIED_ADPCM_BOOT_COPY_SHA256 = (
    "bdc2ae6b75cf3fce945cf695aa6c0e1088591aa3d9fad5c2a9041aa79d440257"
)
sp_text = SP.read_text()
sp_ext_text = SP_EXT.read_text()
ip_text = IP.read_text()
boot_text = BOOT.read_text()
sp_ld_text = SP_LD.read_text()
sp_ext_ld_text = SP_EXT_LD.read_text()
make_text = MAKEFILE.read_text()


def equ(source: str, name: str, path: Path) -> int:
    match = re.search(
        rf"^\.equ\s+{re.escape(name)},\s*(0x[0-9A-Fa-f]+|\d+)\b",
        source,
        re.MULTILINE,
    )
    if not match:
        sys.exit(f"check_player_ring: missing numeric `.equ {name}` in {path}")
    return int(match.group(1), 0)


def require(source: str, pattern: str, description: str) -> None:
    if not re.search(pattern, source, re.MULTILINE):
        sys.exit(f"check_player_ring: missing {description}")


parser = argparse.ArgumentParser()
parser.add_argument(
    "--constants",
    type=Path,
    help="generated player_constants.inc for the specialized build",
)
parser.add_argument(
    "--extension",
    required=True,
    type=Path,
    help="linked movieplay_sp_ext.bin",
)
parser.add_argument(
    "--extension-constants",
    required=True,
    type=Path,
    help="generated sp_extension.inc",
)
args = parser.parse_args()

pc_text = args.constants.read_text() if args.constants else ""
extension_bytes = args.extension.read_bytes()
extension_values = sp_extension.metadata(extension_bytes)
extension_include_values = sp_extension.parse_include(
    args.extension_constants.read_text())
if extension_include_values != extension_values:
    sys.exit(
        "check_player_ring: Sub extension constants do not match the linked "
        "binary size/hash/address contract")
qualified_adpcm_entry = extension_bytes[:QUALIFIED_ADPCM_BOOT_COPY_BYTES]
if (
    len(qualified_adpcm_entry) != QUALIFIED_ADPCM_BOOT_COPY_BYTES
    or hashlib.sha256(qualified_adpcm_entry).hexdigest()
    != QUALIFIED_ADPCM_BOOT_COPY_SHA256
):
    sys.exit(
        "check_player_ring: the qualified 88-byte ADPCM boot entry changed")
def pc(name: str) -> int:
    if not pc_text:
        sys.exit(
            "check_player_ring: --constants is required for the variable "
            "Word-RAM layout")
    return equ(pc_text, f"PC_{name}", args.constants)


# The format literals remain source-level invariants.
format_contract = {
    "ROUTING_VERSION": ttrc_routing.VERSION,
    "ROUTING_MAX_FRAMES": ttrc_routing.MAX_FRAMES,
    "ROUTING_SECTOR_BYTES": ttrc_routing.SECTOR_BYTES,
    "ROUTING_CTRL_MASK": ttrc_routing.CTRL_MASK,
    "ROUTING_CTRL_COUNT_MASK": ttrc_routing.CTRL_COUNT_MASK,
    "ROUTING_WORD4_FLAG": ttrc_routing.WORD4_FLAG,
    "ROUTING_TOTAL_SHIFT": ttrc_routing.TOTAL_SHIFT,
    "ROUTING_TOTAL_MASK": ttrc_routing.CTRL_MASK << ttrc_routing.TOTAL_SHIFT,
    "ROUTING_WORD_SHIFT": ttrc_routing.WORD_SHIFT,
    "ROUTING_WORD_MASK": ttrc_routing.WORD_MASK,
    "ROUTING_MAX_ENTRY": ttrc_routing.MAX_ENTRY,
    "FEATURE_COLD_RUNS_BIT": ttrc_routing.FEATURE_COLD_RUNS.bit_length() - 1,
    "FEATURE_FIXED_N_BIT": ttrc_routing.FEATURE_FIXED_N.bit_length() - 1,
    "FEATURE_PATTERN_SUPPLY_BIT": (
        ttrc_routing.FEATURE_PATTERN_SUPPLY.bit_length() - 1),
    "FEATURE_SHADOW_UPDATE_LISTS_BIT": (
        ttrc_routing.FEATURE_SHADOW_UPDATE_LISTS.bit_length() - 1),
    "FEATURE_VRAM_RAW_PREFETCH_BIT": (
        ttrc_routing.FEATURE_VRAM_RAW_PREFETCH.bit_length() - 1),
    "FEATURE_DICBUF_INDEXED_RUNS_BIT": (
        ttrc_routing.FEATURE_DICBUF_INDEXED_RUNS.bit_length() - 1),
    "FEATURE_BOOT_VRAM_SIDECAR_BIT": (
        ttrc_routing.FEATURE_BOOT_VRAM_SIDECAR.bit_length() - 1),
    "FEATURE_WORDBUF_RING_BIT": (
        ttrc_routing.FEATURE_WORDBUF_RING.bit_length() - 1),
}
for name, expected in format_contract.items():
    actual = equ(sp_text, name, SP)
    if actual != expected:
        sys.exit(
            f"check_player_ring: {name}={actual:#x} != Python {expected:#x}")


# Generated layout: one Python calculation owns every offset and capacity.
layout = pattern_supply.word_ram_layout(
    pc("FRAMES"), pc("CELLS"), pc("COLD_CAP"))
layout_contract = {
    "ROUTING_BYTES": layout.routing_bytes,
    "ROUTING_OFFSET": layout.routing_offset,
    "ROUTING_COPY_LONGS": layout.routing_copy_longs,
    "STATUS_OFFSET": layout.status_offset,
    "CTRL_SCR_OFFSET": layout.ctrl_scr_offset,
    "PAD_SCR_OFFSET": layout.pad_scr_offset,
    "ADPCM_TABLE_OFFSET": layout.adpcm_table_offset,
    "PCM_DEC_BUF_OFFSET": layout.pcm_dec_buf_offset,
    "WR0_OFFSET": layout.wr0_offset,
    "WR0_END": layout.wr0_end,
    "WR0_CAPACITY": layout.wr0_patterns,
    "WR1_OFFSET": layout.wr1_offset,
    "WR1_END": layout.wr1_end,
    "WR1_CAPACITY": layout.wr1_patterns,
}
for name, expected in layout_contract.items():
    actual = pc(name)
    if actual != expected:
        sys.exit(
            f"check_player_ring: PC_{name}={actual:#x} != layout {expected:#x}")
if pc("ROUTING_SEC") * ttrc_routing.SECTOR_BYTES != layout.routing_bytes:
    sys.exit("check_player_ring: routing sectors do not match resident allocation")
for parity in (0, 1):
    count = pc(f"WR{parity}_PATTERNS")
    capacity = pc(f"WR{parity}_CAPACITY")
    sectors = pc(f"WR{parity}_SECTORS")
    if not 0 <= count <= capacity:
        sys.exit(
            f"check_player_ring: Wr{parity} count {count} > capacity {capacity}")
    if sectors != (count + 63) // 64:
        sys.exit(
            f"check_player_ring: Wr{parity} sectors {sectors} do not cover "
            f"{count} patterns")
    if pc(f"WR{parity}_OFFSET") + sectors * ttrc_routing.SECTOR_BYTES > layout.status_offset:
        sys.exit(
            f"check_player_ring: Wr{parity} sector padding reaches the fixed tail")
if pc("DIC_PATTERNS") > pattern_supply.DIC_BUF_PATTERNS:
    sys.exit("check_player_ring: DicBuf preload exceeds Main-RAM dictionary")
if pc("BODY_ARM_SEC") != (
        pc("AUDIO_PRELOAD_SEC") + pc("F0_CTRL_SEC") + pc("F0_PAT_SEC")):
    sys.exit(
        "check_player_ring: BODY arm is not audio + frame0 control + patterns")

require(
    sp_text,
    r"^\.equ\s+ROUTING_BYTES,\s*PC_ROUTING_BYTES\s*$",
    "generated routing byte allocation",
)
require(
    sp_text,
    r"^\.equ\s+ROUTING_COPY_LONGS,\s*PC_ROUTING_COPY_LONGS\s*$",
    "generated routing copy length",
)
require(
    sp_text,
    r"^\s*move\.w\s+#ROUTING_COPY_LONGS,\s*d5\s*$",
    "named routing extension-copy length",
)
require(
    sp_text,
    r"^\s*lea\s+WORD_BUF0,\s*a0\s*$",
    "Wr0 preload destination",
)
require(
    sp_text,
    r"^\s*lea\s+WORD_BUF1,\s*a0\s*$",
    "Wr1 preload destination",
)
require(
    sp_text,
    r"^\s*moveq\s+#PC_WR0_SECTORS,\s*d0\s*$",
    "Wr0 sector-rounded preload length",
)
require(
    sp_text,
    r"^\s*moveq\s+#PC_WR1_SECTORS,\s*d0\s*$",
    "Wr1 sector-rounded preload length",
)
require(
    ip_text,
    r"^\.equ\s+WR0_END,\s*PC_WR0_END\s*$",
    "Main Wr0 bound",
)
require(
    ip_text,
    r"^\.equ\s+WR1_END,\s*PC_WR1_END\s*$",
    "Main Wr1 bound",
)

print(
    "check_player_ring: OK  compact Word RAM "
    f"routing={layout.routing_bytes // 1024}KiB "
    f"Wr0={pc('WR0_PATTERNS')}/{layout.wr0_patterns} "
    f"Wr1={pc('WR1_PATTERNS')}/{layout.wr1_patterns} patterns")


# TTRC v21 has one startup command. HEADER contains only static boot state;
# BODY begins with the finite untimed arm. The player-only black state publishes
# F=FFFF, and the timed suffix must remain stopped until Main clears CMD_STREAM
# after publishing frame 0. PCM must then wait for the first timed control
# sector, so ROM_READN startup latency remains outside the movie clock.
for removed in ("STAT_BOOT_VRAM", "arm_body_after_frame0", "body_start_pending"):
    if removed in sp_text or removed in ip_text:
        sys.exit(
            f"check_player_ring: removed second startup handshake returned: "
            f"{removed}")
for source, token, description in (
        (sp_text, "PC_MOVE_W h_body_arm_sec, PC_BODY_ARM_SEC, d1",
         "finite BODY-arm read length"),
        (sp_text, "PC_MOVE_W h_audio_pre_sec, PC_AUDIO_PRELOAD_SEC, d7",
         "BODY-arm PCM drain"),
        (sp_text, "PC_MOVE_W h_f0_ctrl_sec, PC_F0_CTRL_SEC, d0",
         "BODY-arm frame-0 control drain"),
        (sp_text, "PC_MOVE_W h_f0_pat_sec, PC_F0_PAT_SEC, d0",
         "BODY-arm frame-0 pattern drain"),
        (sp_text, "frame0_ready_wait:", "untimed frame-0 handoff wait"),
        (sp_text, "timed_suffix_start:", "post-frame-0 timed start"),
        (sp_text, "startup_ready:", "post-first-slot startup release"),
        (sp_text, "bsr\tpcm_on", "first-sector playback-start PCM edge"),
        (ip_text, "bsr\tshow_frame_minus_one", "frame -1 display"),
        (ip_text, "move.w\t#-1, frame_no", "F=FFFF HUD sentinel"),
        (ip_text, "bsr\tstart_playback", "post-frame-0 command clear"),
):
    if token not in source:
        sys.exit(f"check_player_ring: missing {description}")

startup_order = (
    "frame0_handoff:",
    "move.w\t#STAT_READY, (COMSTAT0).l",
    "frame0_ready_wait:",
    "tst.w\t(COMCMD0).l",
    "timed_suffix_start:",
    "bsr\tissue_file_readn",
    "arm_frame1:",
    "bsr\tpump1_core",
    "bsr\tpcm_on",
    "timed_suffix_armed:",
    "startup_ready:",
    "move.w\t#0, (COMSTAT0).l",
)
cursor = 0
for token in startup_order:
    position = sp_text.find(token, cursor)
    if position < 0:
        sys.exit(
            "check_player_ring: frame-1/frame-0/timed-start order is broken "
            f"at {token!r}")
    cursor = position + len(token)

untimed_wait = sp_text[
    sp_text.index("frame0_handoff:"):sp_text.index("timed_suffix_start:")
]
for forbidden in ("pump_poll_core", "pump1_core", "issue_file_readn"):
    if forbidden in untimed_wait:
        sys.exit(
            "check_player_ring: timed CD service entered the untimed "
            f"frame-1/frame-0 interval through {forbidden}")
print(
    "check_player_ring: OK  v21 BODY arm and one-command "
    "frame -1/frame-0 startup; timed suffix begins at the frame-0 clear edge "
    "and PCM begins on its first control sector")


# Boot stage is consumed through an explicit give/copy/take-back handshake.
if pattern_supply.PALTAB_STAGE_OFFSET != equ(
        sp_text, "PALTAB_STAGE_OFF", SP):
    sys.exit("check_player_ring: Sub PALTAB stage offset differs from Python")
if pattern_supply.PALTAB_STAGE_BYTES != equ(
        sp_text, "PALTAB_STAGE_BYTES", SP):
    sys.exit("check_player_ring: Sub PALTAB stage size differs from Python")
if pattern_supply.PALTAB_STAGE_BYTES != equ(
        ip_text, "PALTAB_STAGE_BYTES", IP):
    sys.exit("check_player_ring: Main PALTAB stage size differs from Python")
if pattern_supply.DIC_STAGE_OFFSET != equ(
        sp_text, "DIC_STAGE_OFF", SP):
    sys.exit("check_player_ring: Sub DicBuf stage offset differs from Python")
if pattern_supply.DIC_STAGE_OFFSET != equ(
        ip_text, "DIC_STAGE_OFF", IP):
    sys.exit("check_player_ring: Main DicBuf stage offset differs from Python")
for source, description in (
        (sp_text, "Sub boot-stage handoff"),
        (ip_text, "Main boot-stage handoff")):
    require(source, r"STAT_BOOT_STAGE", description)
require(
    ip_text,
    r"^\s*bsr\s+consume_boot_stage\s*$",
    "Main boot-stage copy call",
)
stage_start = sp_text.index(
    "/* This handoff is an intentional HEADER read boundary.")
stage_end = sp_text.index(
    "/* The five-sector image holds the unchanged 8,800-byte ADPCM tables",
    stage_start)
stage_handoff = sp_text[stage_start:stage_end]
for token, description in (
        ("BIOSCALL BIOS_CDC_STOP", "planned HEADER pause"),
        ("moveq\t#HEADER_SECTORS+PC_PALTAB_SEC+PC_DIC_SECTORS, d0",
         "exact HEADER restart sector"),
        ("add.l\theader_lba, d0", "absolute HEADER restart LBA"),
        ("move.l\tstream_remaining, d1", "remaining HEADER sector count"),
        ("bsr\treseek_readn", "planned HEADER restart"),
):
    if token not in stage_handoff:
        sys.exit(f"check_player_ring: boot handoff is missing {description}")
if any(symbol in sp_text for symbol in (".equ O_CRAM,", ".equ O_NUPD,", ".equ O_UPDS,")):
    sys.exit("check_player_ring: removed O_CRAM/O_NUPD/O_UPDS allocation returned")
for token, description in (
        (".equ O_PRGMIN, O_STATUS+0x24", "signed PrgBuf HUD status word"),
        (".equ O_PUMPGAP,O_STATUS+0x26", "Sub pump-gap HUD status word"),
        (".equ O_PRGPEAK,O_STATUS+0x28",
         "physical PrgBuf peak HUD status word"),
        (".equ O_READAHEAD,O_STATUS+0x2A",
         "CD reader-lead HUD status word")):
    if token not in sp_text:
        sys.exit(
            f"check_player_ring: missing {description} at its fixed offset")
require(
    ip_text,
    r"^\s*move\.w\s+\(PROBE_BANK\+STATUS_OFF\+0x26\)\.l,\s*d4\s*$",
    "separate Main-side Sub pump-gap HUD read",
)
require(
    ip_text,
    r"^\s*move\.w\s+\(PROBE_BANK\+STATUS_OFF\+0x28\)\.l,\s*d4\s*$",
    "separate Main-side physical PrgBuf peak HUD read",
)
require(
    ip_text,
    r"^\s*move\.w\s+\(PROBE_BANK\+STATUS_OFF\+0x2A\)\.l,\s*d4\s*$",
    "separate Main-side CD reader-lead HUD read",
)
require(
    sp_text,
    r"^\s*lea\s+\(CTRL_SCR\+8\)\.l,\s*a2\s*$",
    "diagnostic update-list output in CTRL_SCR",
)
print(
    "check_player_ring: OK  boot stage uses a planned HEADER read boundary; "
    "diagnostics use CTRL_SCR")


# ADPCM/table and dictionary sizes remain fixed physical contracts. Hashes make
# any codec-table change explicit before the boot copy can silently diverge.
if equ(sp_text, "ADPCM_TABLE_BYTES", SP) != ima_adpcm.FULL_TABLE_BYTES:
    sys.exit("check_player_ring: Sub ADPCM table size differs from Python")
if equ(sp_text, "ADPCM_INDEX_BYTES", SP) != ima_adpcm.FULL_INDEX_BYTES:
    sys.exit("check_player_ring: Sub ADPCM index size differs from Python")
if equ(sp_text, "ADPCM_DELTA_BYTES", SP) != ima_adpcm.FULL_DELTA_BYTES:
    sys.exit("check_player_ring: Sub ADPCM delta size differs from Python")
if equ(sp_text, "ADPCM_LUT_BYTES", SP) != ima_adpcm.OUTPUT_LUT_BYTES:
    sys.exit("check_player_ring: Sub ADPCM output LUT size differs from Python")
full_table = ima_adpcm.full_tables()
indices, deltas, output_lut = ima_adpcm.split_tables(full_table)
hash_contract = {
    "full": (
        hashlib.sha256(full_table).hexdigest(),
        ima_adpcm.FULL_TABLE_SHA256),
    "hot": (
        hashlib.sha256(indices + output_lut).hexdigest(),
        ima_adpcm.HOT_TABLE_SHA256),
    "delta": (
        hashlib.sha256(deltas).hexdigest(),
        ima_adpcm.DELTA_TABLE_SHA256),
}
for name, (actual, expected) in hash_contract.items():
    if actual != expected:
        sys.exit(
            f"check_player_ring: ADPCM {name} table hash {actual} != {expected}")
if pattern_supply.PCM_DEC_BUF_BYTES != av_config.PCM_DEC_BUF_BYTES:
    sys.exit(
        "check_player_ring: A/B-stable Word-RAM PCM reserve differs from "
        "the live PRG buffer size")
expected_adpcm_sectors = (
    ima_adpcm.FULL_TABLE_BYTES + ttrc_routing.SECTOR_BYTES - 1
) // ttrc_routing.SECTOR_BYTES
if equ(sp_text, "ADPCM_TABLE_SECTORS", SP) != expected_adpcm_sectors:
    sys.exit("check_player_ring: Sub ADPCM table sector count differs from Python")
if equ(sp_text, "ADPCM_BANK_COPIES", SP) != 2:
    sys.exit("check_player_ring: ADPCM table must be duplicated in both banks")
if equ(ip_text, "DIC_BUF_PATTERNS", IP) != pattern_supply.DIC_BUF_PATTERNS:
    sys.exit("check_player_ring: Main DicBuf capacity differs from Python")
if equ(ip_text, "DIC_BUF", IP) != pattern_supply.DIC_BUF_BASE:
    sys.exit("check_player_ring: Main DicBuf base differs from Python")
if equ(ip_text, "DIC_BUF_END", IP) != pattern_supply.DIC_BUF_END:
    sys.exit("check_player_ring: Main DicBuf end differs from Python")
if equ(sp_text, "DIC_STAGE_PATTERNS", SP) != pattern_supply.DIC_BUF_PATTERNS:
    sys.exit("check_player_ring: Sub DicBuf stage capacity differs from Python")


# The fixed Main-RAM map holds in every build: PALTAB, PALIDX and DicBuf are
# adjacent, and the dictionary ends below the stack guard.
ip_paltab_ram = equ(ip_text, "PALTAB_RAM", IP)
ip_palidx_ram = equ(ip_text, "PALIDX_RAM", IP)
if equ(ip_text, "PALIDX_ENTRIES", IP) != av_config.PALIDX_ENTRIES:
    sys.exit("check_player_ring: Main PALIDX entry count differs from av_config")
if ip_paltab_ram + av_config.PALTAB_MAX_SEG * 128 != ip_palidx_ram:
    sys.exit("check_player_ring: M-PALIDX does not follow the fixed PALTAB")
if ip_palidx_ram + av_config.PALIDX_BYTES != pattern_supply.DIC_BUF_BASE:
    sys.exit("check_player_ring: M-DIC does not follow M-PALIDX")
if pattern_supply.DIC_BUF_END > 0xFFFB00:
    sys.exit("check_player_ring: M-DIC overlaps the stack guard")

# The player image embeds the pack-written palette tables. Validate the build
# inputs the IP is about to incbin: paltab.bin is n_seg*128 bytes within the
# fixed M-PALTAB capacity, palidx.bin is the sentinel-terminated 16-entry
# switch table.
if args.constants:
    paltab_path = args.constants.parent / "paltab.bin"
    palidx_path = args.constants.parent / "palidx.bin"
    if paltab_path.exists() or palidx_path.exists():
        paltab_bytes = paltab_path.read_bytes()
        if (not paltab_bytes or len(paltab_bytes) % 128
                or len(paltab_bytes) > av_config.PALTAB_MAX_SEG * 128):
            sys.exit(
                f"check_player_ring: paltab.bin is {len(paltab_bytes)} bytes; "
                f"expected n_seg*128 up to {av_config.PALTAB_MAX_SEG * 128}")
        palidx_bytes = palidx_path.read_bytes()
        if len(palidx_bytes) != av_config.PALIDX_BYTES:
            sys.exit(
                f"check_player_ring: palidx.bin is {len(palidx_bytes)} bytes; "
                f"expected {av_config.PALIDX_BYTES}")
        last_frame = int.from_bytes(palidx_bytes[-4:-2], "big")
        if last_frame != av_config.PALIDX_FRAME_SENTINEL:
            sys.exit(
                "check_player_ring: palidx.bin final entry is not the 0xFFFF "
                "frame sentinel")


# PRG-RAM ring and boot-only staging remain independent of movie layout.
ring_size = equ(sp_text, "RING_SIZE", SP)
if ring_size != av_config.RING_SIZE_KB * 1024:
    sys.exit("check_player_ring: physical PrgBuf ring differs from av_config")
ring_base = equ(sp_text, "RING_BASE", SP)
apply_base = equ(sp_text, "APPLY_BASE", SP)
apply_size = equ(sp_text, "APPLY_SIZE", SP)
f0pat_tmp = equ(sp_text, "F0PAT_TMP", SP)
routing_tmp = equ(sp_text, "ROUTING_TMP", SP)
iso_buf = equ(sp_text, "ISO_BUF", SP)
iso_buf_bytes = equ(sp_text, "ISO_BUF_BYTES", SP)
sub_prg_safe_base = equ(sp_text, "SUB_PRG_SAFE_BASE", SP)
sub_prg_safe_end = equ(sp_text, "SUB_PRG_SAFE_END", SP)
pcm_dec_buf = equ(sp_text, "PCM_DEC_BUF", SP)
pcm_dec_buf_bytes = equ(sp_text, "PCM_DEC_BUF_BYTES", SP)
pcm_dec_buf_end = equ(sp_text, "PCM_DEC_BUF_END", SP)
adpcm_indices = equ(sp_text, "ADPCM_INDICES", SP)
adpcm_index_bytes = equ(sp_text, "ADPCM_INDEX_BYTES", SP)
adpcm_indices_end = equ(sp_text, "ADPCM_INDICES_END", SP)
adpcm_lut = equ(sp_text, "ADPCM_LUT", SP)
adpcm_lut_bytes = equ(sp_text, "ADPCM_LUT_BYTES", SP)
adpcm_lut_end = equ(sp_text, "ADPCM_LUT_END", SP)
adpcm_boot_copy = equ(sp_text, "ADPCM_BOOT_COPY", SP)
max_f0_bytes = (
    (40 * 28 * pattern_supply.PATTERN_BYTES
     + ttrc_routing.SECTOR_BYTES - 1)
    // ttrc_routing.SECTOR_BYTES
    * ttrc_routing.SECTOR_BYTES
)
if ring_base + ring_size + ttrc_routing.SECTOR_BYTES != apply_base:
    sys.exit(
        "check_player_ring: PrgBuf plus fourth pending Word sector "
        "does not end at APPLY")
if f0pat_tmp + max_f0_bytes != routing_tmp:
    sys.exit("check_player_ring: routing staging does not follow frame-0 staging")
if routing_tmp + ttrc_routing.ROUTE_BYTES > apply_base + apply_size:
    sys.exit("check_player_ring: maximum routing staging exceeds APPLY")
if (
        iso_buf != av_config.SUB_BOOT_ISO_BUF_BASE
        or iso_buf_bytes != av_config.SUB_BOOT_ISO_BUF_BYTES
        or iso_buf + iso_buf_bytes != av_config.SUB_BOOT_ISO_BUF_END
):
    sys.exit("check_player_ring: boot ISO scratch differs from config")
if iso_buf + iso_buf_bytes > apply_base:
    sys.exit("check_player_ring: boot ISO scratch reaches timed APPLY")
if (
        sub_prg_safe_base != av_config.SUB_PRG_SAFE_BASE
        or sub_prg_safe_end != av_config.SUB_PRG_SAFE_END
):
    sys.exit("check_player_ring: marker-verified Sub PRG range differs from config")
if (
        pcm_dec_buf != av_config.PCM_DEC_BUF_BASE
        or pcm_dec_buf_bytes != av_config.PCM_DEC_BUF_BYTES
        or pcm_dec_buf_end != av_config.PCM_DEC_BUF_END
):
    sys.exit("check_player_ring: live PCM decode buffer differs from config")
if pcm_dec_buf + pcm_dec_buf_bytes != pcm_dec_buf_end:
    sys.exit("check_player_ring: live PCM decode buffer end is inconsistent")
if not sub_prg_safe_base <= pcm_dec_buf < pcm_dec_buf_end <= sub_prg_safe_end:
    sys.exit("check_player_ring: live PCM decode buffer exceeds safe Sub PRG")
prg_adpcm_contract = {
    "ADPCM_INDICES": (
        adpcm_indices, av_config.ADPCM_INDEX_TABLE_BASE),
    "ADPCM_INDEX_BYTES": (
        adpcm_index_bytes, av_config.ADPCM_INDEX_TABLE_BYTES),
    "ADPCM_INDICES_END": (
        adpcm_indices_end, av_config.ADPCM_INDEX_TABLE_END),
    "ADPCM_LUT": (
        adpcm_lut, av_config.ADPCM_OUTPUT_LUT_BASE),
    "ADPCM_LUT_BYTES": (
        adpcm_lut_bytes, av_config.ADPCM_OUTPUT_LUT_BYTES),
    "ADPCM_LUT_END": (
        adpcm_lut_end, av_config.ADPCM_OUTPUT_LUT_END),
    "ADPCM_BOOT_COPY": (
        adpcm_boot_copy, av_config.SUB_BOOT_EXTENSION_EXEC_BASE),
}
for name, (actual, expected) in prg_adpcm_contract.items():
    if actual != expected:
        sys.exit(
            f"check_player_ring: {name}={actual:#x} != config {expected:#x}")
if not (
        adpcm_indices + adpcm_index_bytes == adpcm_indices_end
        and adpcm_indices_end == adpcm_lut
        and adpcm_lut + adpcm_lut_bytes == adpcm_lut_end
        and sub_prg_safe_end <= adpcm_indices
        and adpcm_lut_end <= ring_base
):
    sys.exit("check_player_ring: persistent Sub PRG PCM/table allocations overlap")
if not (
        adpcm_boot_copy == ring_base + ring_size
        and adpcm_boot_copy + extension_values.size <= apply_base
):
    sys.exit(
        "check_player_ring: boot-only Sub extension exceeds the later "
        "fourth pending Word sector")
if (
        extension_values.load_base
        != routing_tmp + ima_adpcm.FULL_TABLE_BYTES
):
    sys.exit(
        "check_player_ring: Sub extension preload does not follow the ADPCM "
        "table in ROUTING_TMP")
adpcm_preload_capacity = expected_adpcm_sectors * ttrc_routing.SECTOR_BYTES
if ima_adpcm.FULL_TABLE_BYTES + extension_values.size > adpcm_preload_capacity:
    sys.exit("check_player_ring: Sub extension exceeds ADPCM sector padding")
if "SUB_BANK_1M+PC_PCM_DEC_BUF_OFFSET" in sp_text:
    sys.exit("check_player_ring: timed PCM decode still addresses Word RAM")
if sp_text.count("lea\tPCM_DEC_BUF,") != 2:
    sys.exit("check_player_ring: decoder/wave PCM buffer references changed")
decoder = sp_text[
    sp_text.index("decode_adpcm_chunk:"):sp_text.index("write_wave_chunk:")
]
for token in (
        "lea\tADPCM_DELTAS, a2",
        "lea\tADPCM_INDICES, a3",
        "lea\tADPCM_LUT, a4",
):
    if token not in decoder:
        sys.exit(f"check_player_ring: split-table decoder is missing {token!r}")
if "ADPCM_TABLE" in decoder:
    sys.exit("check_player_ring: decoder still directly uses the full Word table")


# The BIOS directly loads the multi-sector resident Sub module. Its disc-system
# source range, live PRG destination, and boot-only ISO scratch are independent
# ownership contracts. The packer still places the exact one-shot extension
# after the ADPCM tables in their existing five-sector HEADER preload.
for pattern, description in (
        (r"SP_Addr:\s*\n\s*\.long\s+0x00006000\b",
         "Sub boot source at 0x6000"),
        (r"^\s*\.org\s+0x6000\s*$", "resident Sub boot source"),
        (r"^\s*\.align\s+0x8000\s*$", "32 KiB boot image bound"),
):
    require(boot_text, pattern, description)
require(
    sp_ld_text,
    r'ASSERT\(\.\s*<=\s*0x008000,\s*"resident Sub image exceeds',
    "8 KiB resident Sub linker assertion",
)
if re.search(
        r'^\s*\.incbin\s+"movieplay_sp_ext\.bin"\s*$',
        boot_text, re.MULTILINE):
    sys.exit("check_player_ring: Sub extension must not be BIOS boot-loaded")
for token in (
        ".equ ADPCM_BOOT_COPY_BYTES, 0x0058",
        ".equ ADPCM_BOOT_COPY_LONGS, ADPCM_BOOT_COPY_BYTES/4",
        ".equ ROUTING_EXTENSION_IN_STAGE, 1",
        "lea\tSP_EXTENSION_LOAD_BASE, a0",
        "lea\tSP_EXTENSION_EXEC_BASE, a1",
        "move.w\t#ADPCM_BOOT_COPY_LONGS-1, d0",
        "move.w\t#SP_EXTENSION_LONGS-1, d0",
        "lea\tADPCM_DELTAS, a2",
        "PC_MOVE_L h_prebuf_pat, PC_PREBUF_PAT, d6",
        "lea\tring_head, a4",
        "lea\tdrain_k, a5",
        "jsr\tADPCM_BOOT_COPY",
        "jsr\t(SP_EXTENSION_LOAD_BASE+ADPCM_BOOT_COPY_BYTES).l",
        "jsr\t(SP_EXTENSION_EXEC_BASE+ADPCM_BOOT_COPY_BYTES).l",
):
    if token not in sp_text:
        sys.exit(f"check_player_ring: Sub extension path is missing {token!r}")
if pc("ROUTING_SEC") <= 4:
    staged_extension_start = (
        routing_tmp + ima_adpcm.FULL_TABLE_BYTES + 0x58)
    routing_end = routing_tmp + pc("ROUTING_SEC") * ttrc_routing.SECTOR_BYTES
    if routing_end > staged_extension_start:
        sys.exit(
            "check_player_ring: staged routing reaches the live extension "
            "entry")
require(
    sp_ext_ld_text,
    rf"^\s*\.text\s+0x{av_config.SUB_BOOT_EXTENSION_EXEC_BASE:06X}\s*:",
    "Sub extension link address",
)
require(
    sp_ext_ld_text,
    rf"ASSERT\(\.\s*<=\s*0x{av_config.SUB_BOOT_EXTENSION_EXEC_BASE + av_config.SUB_BOOT_EXTENSION_MAX_BYTES:06X},",
    "Sub extension boot-time ring-tail linker assertion",
)
for token in (
        "lea\tROUTING_TMP, a0",
        "lea\tADPCM_INDEX_TABLE, a1",
        "lea\tROUTING_TMP+ADPCM_OUTPUT_LUT_OFFSET, a0",
        "lea\tADPCM_OUTPUT_LUT, a1",
        "lea\tROUTING_TMP+ADPCM_DELTA_OFFSET, a0",
        "movea.l\ta2, a1",
        "moveq\t#ADPCM_BANK_COPIES-1, d1",
        ".org 0x0058",
        ".global routing_prepare",
        "routing_prepare:",
        "movea.l\ta0, a2",
        "move.w\td5, d0",
        "moveq\t#ROUTING_BANK_COPIES-1, d1",
        "move.l\t#RING_BASE, (a4)+",
        "move.l\t#APPLY_BASE, (a4)+",
        "move.w\t#1, 4(a5)",
):
    if token not in sp_ext_text:
        sys.exit(f"check_player_ring: Sub boot extension is missing {token!r}")
if "rt_validate:" in sp_text or "rt_copy:" in sp_text:
    sys.exit(
        "check_player_ring: boot-only routing preparation returned to the "
        "resident Sub image")
for token in (
        ".equ GA_STOPWATCH_ABS_W,GA_STOPWATCH-0x01000000",
        "move.w\t(GA_STOPWATCH_ABS_W).w, d0",
        "move.w\tpoll_max_gap, (O_PUMPGAP).l",
        "poll_last_tick:",
        "poll_max_gap:",
):
    if token not in sp_text:
        sys.exit(
            f"check_player_ring: inline Sub diagnostic is missing {token!r}")
require(
    make_text,
    rf'if \[ "\$\$bytes" -gt {av_config.SUB_BOOT_IMAGE_MAX_BYTES} \]; then',
    "resident Sub image-size Makefile guard",
)
require(
    make_text,
    r'--sp-extension "\$\(SP_EXTENSION_BIN\)" --verify',
    "Sub extension HEADER preload pack argument",
)


# The live pump must consult routing before selecting a guarded destination.
pump = sp_text[
    sp_text.index("pump_poll_core:"):sp_text.index("pp_done:")
]
for token in (
        "lea\tROUTING, a0",
        "move.l\tring_tail, d0",
        "pp_apply_space:",
        "move.l\tapply_tail, d0",
        "pp_cdc:",
):
    if token not in pump:
        sys.exit(f"check_player_ring: route-aware pump is missing {token!r}")

if pc("FEATURES") & ttrc_routing.FEATURE_WORDBUF_RING:
    if equ(ip_text, "FEATURE_WORDBUF_RING_BIT", IP) != (
            ttrc_routing.FEATURE_WORDBUF_RING.bit_length() - 1):
        sys.exit("check_player_ring: Main WordBuf-ring feature bit differs")
    for source, token, description in (
            (sp_text, ".equ INCLUDE_WORDBUF_RING, 1",
             "specialized WordBuf-ring build switch"),
            (sp_text, "move.l\td0, word_write_ptr0",
             "Wr0 timed write cursor initialization"),
            (sp_text, "move.l\td0, word_write_ptr1",
             "Wr1 timed write cursor initialization"),
            (sp_text, "cmp.w\tframe_idx, d0\n\tblo.s\twag_no",
             "expanded-frame Word refill cutoff (early arrival accepted)"),
            (sp_text, "cmp.w\tword_owned_bank, d1",
             "physical Word-RAM ownership guard"),
            (sp_text, "word_pending_count:",
             "bounded pending Word-sector state"),
            (sp_text, "word_pending2:",
             "third resident pending Word-sector buffer"),
            (sp_text, "bsr\tflush_word_pending",
             "post-swap pending Word-sector commit"),
            (sp_text, "addi.w\t#64, word_level0",
             "Wr0 sector occupancy accounting"),
            (sp_text, "addi.w\t#64, word_level1",
             "Wr1 sector occupancy accounting"),
            (sp_text, "sub.w\td3, word_level0",
             "Wr0 source-run retirement"),
            (sp_text, "sub.w\td3, word_level1",
             "Wr1 source-run retirement"),
            (ip_text, "cmpa.l\t#PROBE_BANK+WR0_END, a3",
             "Main Wr0 ring-end normalization"),
            (ip_text, "cmpa.l\t#PROBE_BANK+WR1_END, a3",
             "Main Wr1 ring-end normalization"),
    ):
        if token not in source:
            sys.exit(
                f"check_player_ring: missing {description}: {token!r}")
    blocking_pump = sp_text[
        sp_text.index("pump1_core:"):sp_text.index("p1_drain:")
    ]
    opportunistic_pump = sp_text[
        sp_text.index("pump_poll_core:"):sp_text.index("pp_not_word:")
    ]
    if "bsr\tword_accept_guard" not in blocking_pump:
        sys.exit(
            "check_player_ring: blocking pump does not reserve a bounded "
            "Word-sector destination")
    if "bsr\tword_accept_guard" not in opportunistic_pump:
        sys.exit(
            "check_player_ring: opportunistic pump does not reserve a bounded "
            "Word-sector destination")
    pending_dispatch = sp_text[
        sp_text.index("p1_word_pending:"):sp_text.index("p1_ring:")
    ]
    for pattern, description in (
            (
                r"movea\.l\s+#WORD_PENDING0,\s*a1\s+"
                r"move\.w\s+drain_frame,\s*word_pending_frame\s+"
                r"bra\.s\s+4f",
                "first pending Word sector -> WORD_PENDING0",
            ),
            (
                r"cmpi\.w\s+#1,\s*d0.*?"
                r"movea\.l\s+#WORD_PENDING1,\s*a1\s+"
                r"bra\.s\s+4f",
                "second pending Word sector -> WORD_PENDING1",
            ),
            (
                r"cmpi\.w\s+#2,\s*d0.*?"
                r"lea\s+word_pending2,\s*a1\s+"
                r"bra\.s\s+4f",
                "third pending Word sector -> word_pending2",
            ),
            (
                r"3:\s+movea\.l\s+#WORD_PENDING3,\s*a1\s+4:",
                "fourth pending Word sector -> WORD_PENDING3",
            ),
    ):
        if not re.search(pattern, pending_dispatch, re.DOTALL):
            sys.exit(
                "check_player_ring: pending Word-sector dispatch does not "
                f"preserve {description}")
    word_pending0 = equ(sp_text, "WORD_PENDING0", SP)
    word_pending1 = equ(sp_text, "WORD_PENDING1", SP)
    word_pending_end = equ(sp_text, "WORD_PENDING_SAFE_END", SP)
    word_pending3 = equ(sp_text, "WORD_PENDING3", SP)
    if not (
            word_pending0 == pcm_dec_buf_end
            and word_pending1 == word_pending0 + ttrc_routing.SECTOR_BYTES
            and word_pending_end
            == word_pending1 + ttrc_routing.SECTOR_BYTES
            and word_pending_end <= sub_prg_safe_end
            and word_pending3 == ring_base + ring_size
            and word_pending3 + ttrc_routing.SECTOR_BYTES == apply_base):
        sys.exit(
            "check_player_ring: pending Word sectors overlap or exceed their "
            "two safe-PRG, resident-tail, and PrgBuf-tail allocations")
    process = sp_text[
        sp_text.index("pf_pump:"):sp_text.index("pf_ready:")
    ]
    for token in (
            "andi.w\t#ROUTING_WORD_MASK, d2",
            "lsr.w\t#ROUTING_WORD_SHIFT, d2",
            "add.w\td2, d1",
    ):
        if token not in process:
            sys.exit(
                "check_player_ring: frame readiness does not include the "
                f"Word payload prefix: {token!r}")

ip_max_seg = equ(ip_text, "PALTAB_MAX_SEG", IP)
if ip_max_seg != av_config.PALTAB_MAX_SEG:
    sys.exit("check_player_ring: Main palette-table capacity differs from config")

print(
    "check_player_ring: OK  PrgBuf, APPLY, PRG PCM/hot ADPCM, "
    "BIOS-loaded resident Sub image, HEADER-preloaded boot extension, "
    "refillable parity WordBuf, Word delta, DicBuf, palette and "
    "route-aware pump contracts")
