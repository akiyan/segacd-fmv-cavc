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
SP_EXT_LD = ROOT / "cfg/sp_ext.ld"
MAKEFILE = ROOT / "Makefile"
sp_text = SP.read_text()
sp_ext_text = SP_EXT.read_text()
ip_text = IP.read_text()
boot_text = BOOT.read_text()
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
    "ROUTING_TOTAL_SHIFT": ttrc_routing.TOTAL_SHIFT,
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
    r"^\s*move\.w\s+#ROUTING_COPY_LONGS-1,\s*d0\s*$",
    "named routing MOVE.L copy length",
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


# Boot stage is consumed through an explicit give/copy/take-back handshake.
if pattern_supply.PALTAB_STAGE_OFFSET != equ(
        sp_text, "PALTAB_STAGE_OFF", SP):
    sys.exit("check_player_ring: Sub PALTAB stage offset differs from Python")
if pattern_supply.PALTAB_STAGE_OFFSET != equ(
        ip_text, "PALTAB_STAGE_OFF", IP):
    sys.exit("check_player_ring: Main PALTAB stage offset differs from Python")
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
if equ(ip_text, "RUN_TABLE", IP) != pattern_supply.DIC_BUF_END:
    sys.exit("check_player_ring: Main DicBuf end differs from Python")


# PRG-RAM ring and boot-only staging remain independent of movie layout.
ring_size = equ(sp_text, "RING_SIZE", SP)
if ring_size != av_config.RING_SIZE_KB * 1024:
    sys.exit("check_player_ring: physical PrgBuf ring differs from av_config")
ring_base = equ(sp_text, "RING_BASE", SP)
apply_base = equ(sp_text, "APPLY_BASE", SP)
apply_size = equ(sp_text, "APPLY_SIZE", SP)
f0pat_tmp = equ(sp_text, "F0PAT_TMP", SP)
routing_tmp = equ(sp_text, "ROUTING_TMP", SP)
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
if ring_base + ring_size != apply_base:
    sys.exit("check_player_ring: PrgBuf does not end at APPLY")
if f0pat_tmp + max_f0_bytes != routing_tmp:
    sys.exit("check_player_ring: routing staging does not follow frame-0 staging")
if routing_tmp + ttrc_routing.ROUTE_BYTES > apply_base + apply_size:
    sys.exit("check_player_ring: maximum routing staging exceeds APPLY")
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
        ring_base <= adpcm_boot_copy
        and adpcm_boot_copy + extension_values.size <= ring_base + ring_size
):
    sys.exit("check_player_ring: boot-only Sub extension exceeds PrgBuf")
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


# The BIOS boot image contains only the resident 4 KiB Sub module. The packer
# places the exact linked extension after the ADPCM tables in their existing
# five-sector HEADER preload; the base copies it to the timed-ring tail.
for pattern, description in (
        (r"SP_Addr:\s*\n\s*\.long\s+0x00007000\b",
         "Sub boot source at 0x7000"),
        (r"^\s*\.org\s+0x7000\s*$", "resident Sub boot source"),
        (r"^\s*\.align\s+0x8000\s*$", "32 KiB boot image bound"),
):
    require(boot_text, pattern, description)
if re.search(
        r'^\s*\.incbin\s+"movieplay_sp_ext\.bin"\s*$',
        boot_text, re.MULTILINE):
    sys.exit("check_player_ring: Sub extension must not be BIOS boot-loaded")
for token in (
        "lea\tSP_EXTENSION_LOAD_BASE, a0",
        "lea\tSP_EXTENSION_EXEC_BASE, a1",
        "move.w\t#SP_EXTENSION_LONGS-1, d0",
        "lea\tADPCM_DELTAS, a2",
        "jsr\tADPCM_BOOT_COPY",
):
    if token not in sp_text:
        sys.exit(f"check_player_ring: Sub extension path is missing {token!r}")
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
):
    if token not in sp_ext_text:
        sys.exit(f"check_player_ring: ADPCM boot copy is missing {token!r}")
require(
    make_text,
    rf'if \[ "\$\$bytes" -gt {av_config.SUB_BOOT_BASE_BYTES} \]; then',
    "resident Sub base-size Makefile guard",
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

ip_max_seg = equ(ip_text, "PALTAB_MAX_SEG", IP)
if ip_max_seg != av_config.PALTAB_MAX_SEG:
    sys.exit("check_player_ring: Main palette-table capacity differs from config")

print(
    "check_player_ring: OK  PrgBuf, APPLY, PRG PCM/hot ADPCM, "
    "HEADER-preloaded extension, Word delta, DicBuf, palette and "
    "route-aware pump contracts")
