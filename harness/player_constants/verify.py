#!/usr/bin/env python3
"""Build and inspect the current generic/specialized player matrix."""

from __future__ import annotations

import re
import shutil
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import av_config  # noqa: E402
import ima_adpcm  # noqa: E402
import pattern_supply  # noqa: E402
import player_constants  # noqa: E402
import sp_extension  # noqa: E402
import cavc_routing  # noqa: E402


@dataclass(frozen=True)
class Case:
    name: str
    fps: int
    pattern_supply: bool = False
    tcols: int | None = None
    trows: int = 28
    cold_cap: int = 200


CASES = (
    Case("h40-15", 15, cold_cap=360),
    Case("h40-24-supply", 24, True, cold_cap=225),
    Case("h40-30-supply", 30, True),
    Case("h40-30-centered", 30, True, 36, 25),
)
TEST_FRAMES = 600


def find_tool(name: str) -> Path:
    found = shutil.which(name)
    if found:
        return Path(found)
    candidate = Path.home() / "toolchains/mars/m68k-elf/bin" / name
    if candidate.is_file():
        return candidate
    raise SystemExit(f"missing tool: {name}")


def make_header(case: Case) -> bytes:
    tcols = case.tcols if case.tcols is not None else 40
    trows = case.trows
    cells = tcols * trows
    frames = TEST_FRAMES
    features = cavc_routing.FEATURE_COLD_RUNS
    if av_config.uses_vblank_cadence(case.fps):
        features |= cavc_routing.FEATURE_VBLANK_CADENCE
    _rate, audio, _control = av_config.audio_frame_layout(case.fps)
    if case.pattern_supply:
        features |= (
            cavc_routing.FEATURE_PATTERN_SUPPLY
            | cavc_routing.FEATURE_DICBUF_INDEXED_RUNS)
    audio_fd = av_config.rf5c164_fd(
        audio, av_config.playback_fps_for_content(case.fps))
    prefix = struct.pack(
        ">4s8H4LBB3L6H",
        b"CAVC", frames, tcols, trows, cells,
        av_config.VRAM_PATTERN_POOL_TILES, 1,
        cavc_routing.FRAME_SECTORS, 1,
        12416, cavc_routing.routing_sector_count(frames), 194, 12416,
        1, 0, 2, 18,
        av_config.PALTAB_STAGE_KB * 1024 // 2048,
        av_config.vsync_n_for_fps(case.fps), audio, case.fps,
        audio_fd, 30, features,
    )
    sector = bytearray(
        prefix + bytes(130) + bytes(player_constants.SECTOR - 192))
    if case.pattern_supply:
        cold_cap = case.cold_cap
        layout = pattern_supply.word_ram_layout(
            frames, cells, cold_cap)
        player_constants.PATTERN_SUPPLY_STRUCT.pack_into(
            sector, player_constants.PATTERN_SUPPLY_OFFSET,
            player_constants.PATTERN_SUPPLY_MAGIC,
            player_constants.PATTERN_SUPPLY_VERSION, 0,
            layout.wr0_patterns,
            layout.wr1_patterns,
            pattern_supply.DIC_BUF_PATTERNS,
            (layout.wr0_patterns + 63) // 64,
            (layout.wr1_patterns + 63) // 64,
            (pattern_supply.DIC_BUF_PATTERNS + 63) // 64,
            cold_cap,
            layout.wr0_load_bytes,
            layout.wr1_load_bytes,
        )
    return player_constants.stamp_header_sector(sector)


@dataclass(frozen=True)
class Build:
    ip_text: int
    ip_bin: int
    sp_text: int
    sp_bin: int
    sp_extension_bin: int


def run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command, cwd=ROOT, check=True, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as exc:
        raise AssertionError(
            f"command failed ({exc.returncode}): {' '.join(command)}\n{exc.stdout}"
        ) from exc
    return result.stdout


def text_size(size: Path, obj: Path) -> int:
    for line in run([str(size), "-A", str(obj)]).splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[0] == ".text":
            return int(fields[1])
    raise AssertionError(f"no .text size in {obj}")


def symbol_address(objdump: Path, obj: Path, name: str) -> int:
    pattern = re.compile(
        rf"^([0-9a-f]+)\s+\w+\s+\.\w+\s+[0-9a-f]+\s+{re.escape(name)}$",
        re.MULTILINE,
    )
    match = pattern.search(run([str(objdump), "-t", str(obj)]))
    if not match:
        raise AssertionError(f"{obj}: missing symbol {name}")
    return int(match.group(1), 16)


def verify_boot_image(
    case_dir: Path, *, assembler: Path, objcopy: Path, objdump: Path,
) -> None:
    """Prove the multi-sector BIOS module and HEADER extension split."""
    ip = (case_dir / "ip-specialized.bin").read_bytes()
    sp = (case_dir / "sp-specialized.bin").read_bytes()
    extension = (case_dir / "sp-ext-specialized.bin").read_bytes()
    (case_dir / "movieplay_ip.bin").write_bytes(ip)
    (case_dir / "movieplay_sp.bin").write_bytes(sp)
    (case_dir / "movieplay_sp_ext.bin").write_bytes(extension)
    boot_obj = case_dir / "movieplay_boot.out"
    boot_bin = case_dir / "movieplay_boot.bin"
    run([
        str(assembler), "-m68000", "--register-prefix-optional", "--bitwise-or",
        "-I", str(case_dir), "-I", str(ROOT / "boot"),
        str(ROOT / "boot/movieplay_boot.s"), "-o", str(boot_obj),
    ])
    run([str(objcopy), "-O", "binary", str(boot_obj), str(boot_bin)])
    boot = boot_bin.read_bytes()
    if len(boot) != av_config.BOOT_IMAGE_BYTES:
        raise AssertionError(
            f"boot image is {len(boot)} bytes, expected "
            f"{av_config.BOOT_IMAGE_BYTES}")
    symbols = {
        name: symbol_address(objdump, boot_obj, name)
        for name in ("SP_Addr", "SP_Size", "SPStart", "SPEnd")
    }
    if struct.unpack_from(">L", boot, symbols["SP_Addr"])[0] != (
            av_config.SUB_BOOT_SOURCE_BASE):
        raise AssertionError("boot header SP source differs from av_config")
    if struct.unpack_from(">L", boot, symbols["SP_Size"])[0] != len(sp):
        raise AssertionError("boot header SP size is not the resident base only")
    if symbols["SPStart"] != av_config.SUB_BOOT_SOURCE_BASE:
        raise AssertionError("resident Sub source differs from av_config")
    if symbols["SPEnd"] != symbols["SPStart"] + len(sp):
        raise AssertionError("resident Sub source end is inconsistent")
    if boot[symbols["SPStart"]:symbols["SPStart"] + len(sp)] != sp:
        raise AssertionError("boot image resident Sub bytes differ")
    preload = sp_extension.adpcm_preload_image(
        ima_adpcm.full_tables(), extension)
    if preload[
            ima_adpcm.FULL_TABLE_BYTES:
            ima_adpcm.FULL_TABLE_BYTES + len(extension)
    ] != extension:
        raise AssertionError("HEADER preload Sub extension bytes differ")
    module_bytes = struct.unpack_from(">L", sp, 20)[0]
    if not (
            0 < module_bytes <= len(sp)
            and len(sp) - module_bytes < 16
            and not any(sp[module_bytes:])):
        raise AssertionError(
            f"Sub module header covers {module_bytes} bytes, resident linked "
            f"base is {len(sp)} bytes")


def verify_flip_control_flow(objdump: Path, obj: Path) -> None:
    """Prove every player publishes one staged NT without a reg2 flip."""
    disassembly = run([str(objdump), "-d", str(obj)])
    symbols = run([str(objdump), "-t", str(obj)])
    for removed in (
            "back_idx", "bf_blit", "publish_dbg", "stamp_dbg_stage",
            "do_flip", "md_codegen_blit", "md_codegen_blit_addr"):
        if re.search(rf"\b{re.escape(removed)}\b", symbols):
            raise AssertionError(
                f"{obj}: removed double-name-table symbol remains: {removed}")

    start = re.search(
        r"^[0-9a-f]+ <bf_publish_frame>:$", disassembly, re.MULTILINE)
    end = re.search(
        r"^[0-9a-f]+ <bf_after_flip>:$", disassembly, re.MULTILINE)
    if not start or not end or start.start() >= end.start():
        raise AssertionError(f"{obj}: missing single-NT publication block")
    publish = disassembly[start.end():end.start()]
    required_calls = ("nt_dma_flip", "hud_dma_flip", "commit_frame")
    positions = []
    for callee in required_calls:
        match = re.search(rf"\bbsr\w*\s+[^\n]*<{callee}>", publish)
        if not match:
            raise AssertionError(f"{obj}: publication path lacks {callee}")
        positions.append(match.start())
    if positions != sorted(positions):
        raise AssertionError(
            f"{obj}: NT/HUD/commit calls are not in publication order")

    commit = re.search(
        r"^[0-9a-f]+ <commit_frame>:$", disassembly, re.MULTILINE)
    next_fn = re.search(
        r"^[0-9a-f]+ <dma_chunk_wr>:$", disassembly, re.MULTILINE)
    if not commit or not next_fn or commit.start() >= next_fn.start():
        raise AssertionError(f"{obj}: missing commit_frame cadence block")
    commit_block = disassembly[commit.end():next_fn.start()]
    if re.search(r"\bmovew\s+[^,]+,(?:00)?c00004 <VDP_CTRL>", commit_block):
        raise AssertionError(f"{obj}: commit_frame still writes Plane A reg2")


def verify_shared_deadline_vblank(
    objdump: Path, obj: Path, *, tcols: int, trows: int,
) -> None:
    """Prove fixed-cadence pattern and display DMAs share one safe blank."""
    disassembly = run([str(objdump), "-dr", str(obj)])

    def block(start_name: str, end_name: str) -> str:
        start = re.search(
            rf"^[0-9a-f]+ <{re.escape(start_name)}>:$",
            disassembly,
            re.MULTILINE,
        )
        end = re.search(
            rf"^[0-9a-f]+ <{re.escape(end_name)}>:$",
            disassembly,
            re.MULTILINE,
        )
        if not start or not end or start.start() >= end.start():
            raise AssertionError(
                f"{obj}: missing or reordered {start_name}/{end_name}")
        return disassembly[start.end():end.start()]

    dma_entry = block("bf_dma", "bf_run_lp")
    clear_state = re.search(r"\bclrw\s+0 [^\n]*", dma_entry)
    load_runs = re.search(r"\bmovew\s+0 [^\n]*,%d4", dma_entry)
    branch_empty = re.search(
        r"\bbeq\w*\s+[^\n]*<bf_flip>", dma_entry)
    if not clear_state or not load_runs or not branch_empty:
        raise AssertionError(
            f"{obj}: missing shared-state clear/n_runs/empty-frame branch")
    if not clear_state.start() < load_runs.start() < branch_empty.start():
        raise AssertionError(
            f"{obj}: shared-state clear overwrites the n_runs zero flag")
    ready_sample = re.search(
        r"\bmovew\s+(?:00)?c00008 <VDP_HV>,%d0", dma_entry)
    budget_wait = re.search(
        r"\bbsr\w*\s+[^\n]*<bf_start_vbudget>", dma_entry)
    if (
        not ready_sample
        or not budget_wait
        or ready_sample.start() >= budget_wait.start()
    ):
        raise AssertionError(
            f"{obj}: pattern DMA readiness is not sampled before the "
            "fresh-blank wait")

    run_loop = block("bf_run_lp", "bf_split_run")
    repair_charge = re.search(r"\baddqw\s+#4,%d6", run_loop)
    residual_compare = re.search(r"\bcmpw\s+%d7,%d6", run_loop)
    split_crossing = re.search(
        r"\bbra\w*\s+[^\n]*<bf_split_run>", run_loop)
    if not all((repair_charge, residual_compare, split_crossing)):
        raise AssertionError(
            f"{obj}: missing CPU-weighted residual-boundary split")
    if not (
        repair_charge.start()
        < residual_compare.start()
        < split_crossing.start()
    ):
        raise AssertionError(
            f"{obj}: CPU-weighted residual split is out of order")

    start_budget = block("bf_start_vbudget", "bf_refill_vbudget")
    if not re.search(r"\bmovew\s+(?:00)?c00004 <VDP_CTRL>,%d0", start_budget):
        raise AssertionError(f"{obj}: initial VBlank budget lacks status guard")
    if not re.search(r"\bmovew\s+(?:00)?c00008 <VDP_HV>,%d0", start_budget):
        raise AssertionError(f"{obj}: initial VBlank budget lacks HV guard")
    if not re.search(r"\bcmpiw\s+#224,%d0", start_budget):
        raise AssertionError(f"{obj}: initial VBlank budget is not limited to E0")
    if len(re.findall(r"<bf_refill_vbudget>", start_budget)) < 2:
        raise AssertionError(
            f"{obj}: active and mid-blank budget entries do not refill")

    refill = block("bf_refill_vbudget", "bf_debug_snapshot_vbudget")
    if not re.search(r"\bbsr\w*\s+[^\n]*<wait_vb_start>", refill):
        raise AssertionError(f"{obj}: budget refill lacks a fresh VBlank wait")
    expected_budget = 3200
    if not re.search(rf"\bmovew\s+#{expected_budget},%d7", refill):
        raise AssertionError(
            f"{obj}: budget refill is not {expected_budget} words")
    if not re.search(r"\bsubw\s+[^\n]*,%d7", refill):
        raise AssertionError(
            f"{obj}: cadence-final budget does not withhold display work")
    target_addr = symbol_address(objdump, obj, "pace_target_vblanks")
    if not re.search(
            rf"\bcmpw\s+0 [^\n]*,%d0\n"
            rf"\s+[^\n]*R_68K_32\s+\.bss\+0x{target_addr:x}", refill):
        raise AssertionError(
            f"{obj}: final reserve is not keyed to the current cadence target")

    if "<bf_short_run>" in disassembly:
        raise AssertionError(f"{obj}: removed short-run CPU path is still linked")

    split_run = block("bf_split_run", "bf_run_done")
    if not re.search(r"\bsubqw\s+#4,%d7", split_run):
        raise AssertionError(
            f"{obj}: split Word-RAM DMA lacks its CPU-repair charge")

    shared = block("bf_wait_fixed_flip_vblank", "bf_patch_dbg_row")
    required = (
        (r"\bbsr\w*\s+[^\n]*<wait_fixed_flip>", "fixed cadence arm"),
        (r"\bcmpw\s+%d6,%d7", "residual-word reserve check"),
        (r"\bmovew\s+(?:00)?c00008 <VDP_HV>,%d0", "terminal-HV guard"),
        (r"\bcmpiw\s+#-1024,%d0", "terminal FC00 comparison"),
        (r"\bbsr\w*\s+[^\n]*<wait_vb_start>", "fresh-VBlank fallback"),
    )
    for pattern, description in required:
        if not re.search(pattern, shared):
            raise AssertionError(f"{obj}: shared deadline path lacks {description}")
    if len(re.findall(
            r"\bmovew\s+(?:00)?c00004 <VDP_CTRL>,%d0", shared)) != 2:
        raise AssertionError(
            f"{obj}: shared deadline path lacks its two status reads")

    publish = block("bf_publish_frame", "bf_after_flip")
    screen_cols = 40
    band_words = (trows - 1) * 64 + tcols
    hud_words = screen_cols + (43 - screen_cols) * 4
    normal_reserve = band_words + hud_words + 128
    if not re.search(rf"\bmovew\s+#{normal_reserve},%d6", publish):
        raise AssertionError(
            f"{obj}: missing exact grid/HUD/guard reserve ({normal_reserve} words)")
    if not re.search(r"\baddiw\s+#256,%d6", publish):
        raise AssertionError(f"{obj}: optional CRAM reserve is not 256 words")
    for callee in (
            "bf_wait_fixed_flip_vblank", "bf_patch_dbg_row",
            "nt_dma_flip", "hud_dma_flip", "commit_frame"):
        if len(re.findall(rf"\bbsr\w*\s+[^\n]*<{callee}>", publish)) != 1:
            raise AssertionError(
                f"{obj}: publication path must call {callee} exactly once")
    if "<publish_dbg>" in publish:
        raise AssertionError(
            f"{obj}: display path still republishes HUD through the VDP port")


def verify_early_nonblocking_swap(
    objdump: Path, obj: Path, *, expected_frames: int, specialized: bool,
) -> None:
    """Prove every bank exchange starts after Word RAM and before display DMA."""
    disassembly = run([str(objdump), "-dr", str(obj)])

    def block(start_name: str, end_name: str) -> str:
        start = re.search(
            rf"^[0-9a-f]+ <{re.escape(start_name)}>:$",
            disassembly,
            re.MULTILINE,
        )
        end = re.search(
            rf"^[0-9a-f]+ <{re.escape(end_name)}>:$",
            disassembly,
            re.MULTILINE,
        )
        if not start or not end or start.start() >= end.start():
            raise AssertionError(
                f"{obj}: missing or reordered {start_name}/{end_name}")
        return disassembly[start.end():end.start()]

    def bss_reference(
        text: str, instruction: str, symbol_name: str,
    ) -> re.Match[str] | None:
        address = symbol_address(objdump, obj, symbol_name)
        return re.search(
            rf"{instruction}[^\n]*\n"
            rf"(?:\s+[0-9a-f]+:\s+[^\n]*\n){{0,2}}"
            rf"\s+[0-9a-f]+:\s+R_68K_32\s+\.bss\+0x{address:x}",
            text,
        )

    play_loop = block("play_loop", "movie_end_md")
    pending_test = bss_reference(
        play_loop, r"\btstw\s+0 ", "swap_request_pending")
    synchronous_begin = re.search(
        r"\bbsr\w*\s+[^\n]*<swap_begin>", play_loop)
    finish = re.search(
        r"\bbsr\w*\s+[^\n]*<swap_finish_or_end>", play_loop)
    if not all((pending_test, synchronous_begin, finish)):
        raise AssertionError(f"{obj}: play loop lacks split swap state handling")
    if not pending_test.start() < synchronous_begin.start() < finish.start():
        raise AssertionError(f"{obj}: play-loop swap begin/finish order is wrong")

    frame_tail = block("bf_flip", "bf_update_list")
    early_calls = list(re.finditer(
        r"\bbsr\w*\s+[^\n]*<swap_begin>", frame_tail))
    if len(early_calls) != 1:
        raise AssertionError(
            f"{obj}: expected one early swap request, found {len(early_calls)}")
    early = early_calls[0]
    guarded_prefix = frame_tail[:early.start()]
    frame_zero_guard = bss_reference(
        guarded_prefix, r"\btstw\s+0 ", "frame_no")
    final_guard = (
        re.search(rf"\bcmpiw\s+#{expected_frames - 1},%d0", guarded_prefix)
        if specialized
        else bss_reference(guarded_prefix, r"\bcmpw\s+0 [^,]*,%d0", "md_final_frame")
    )
    if not frame_zero_guard or not final_guard:
        raise AssertionError(
            f"{obj}: early swap lacks frame-0/final-frame guards")
    if (
        not re.search(r"\bbeq\w*\s+", guarded_prefix[frame_zero_guard.end():])
        or not re.search(r"\bbcc\w*\s+", guarded_prefix[final_guard.end():])
    ):
        raise AssertionError(
            f"{obj}: early swap frame guards do not branch around the request")
    waits = list(re.finditer(
        r"\bbsr\w*\s+[^\n]*<(?:bf_wait_fixed_flip_vblank|wait_vb_start)>",
        frame_tail))
    if not waits or any(early.start() >= wait.start() for wait in waits):
        raise AssertionError(
            f"{obj}: bank exchange is not ahead of every display-deadline wait")

    after_early = frame_tail[early.end():]
    direct_word_ram = re.search(
        r"\b(?:move|lea|cmp|tst)[a-z]*\s+(?:00)?[23][0-9a-f]{5}\b",
        after_early,
    )
    indirect_word_cursor = re.search(
        r"%(?:a2|a3)@", after_early)
    if direct_word_ram or indirect_word_cursor:
        raise AssertionError(
            f"{obj}: Main still references Word RAM after early bank exchange")
    allowed_calls = {
        "bf_wait_fixed_flip_vblank",
        "wait_vb_start",
        "bf_patch_dbg_row",
        "nt_dma_flip",
        "hud_dma_flip",
        "commit_frame",
    }
    calls = set(re.findall(
        r"\bbsr\w*\s+[^\n]*<([^>]+)>", after_early))
    if calls - allowed_calls:
        raise AssertionError(
            f"{obj}: unaudited post-swap call(s): "
            f"{', '.join(sorted(calls - allowed_calls))}")

    begin = block("swap_begin", "swap_finish_or_end")
    if not bss_reference(
            begin, r"\bmovew\s+#1,0 ", "swap_request_pending"):
        raise AssertionError(f"{obj}: swap_begin does not mark the request pending")
    if not re.search(
            r"\bmovew\s+#81,(?:00)?a12010 <GA_COMCMD0>", begin):
        raise AssertionError(f"{obj}: swap_begin does not assert CMD_SWAP")
    if re.search(r"\bmovew\s+(?:00)?a12020 <GA_COMSTAT0>", begin):
        raise AssertionError(f"{obj}: swap_begin blocks on Sub status")

    finish_block = block("swap_finish_or_end", "show_frame_minus_one")
    for status in (-32765, -32764):
        if not re.search(rf"\bcmpiw\s+#{status},%d0", finish_block):
            raise AssertionError(
                f"{obj}: swap_finish_or_end lacks status {status}")
    if re.search(r"\bmovew\s+#81,(?:00)?a12010 <GA_COMCMD0>", finish_block):
        raise AssertionError(f"{obj}: swap finish reissues CMD_SWAP")
    if not re.search(
            r"\bmovew\s+#0,(?:00)?a12010 <GA_COMCMD0>", finish_block):
        raise AssertionError(f"{obj}: swap finish does not clear CMD_SWAP")
    if not bss_reference(
            finish_block, r"\bclrw\s+0 ", "swap_request_pending"):
        raise AssertionError(f"{obj}: swap finish leaves the request pending")


def verify_transfer_cleanup(objdump: Path, obj: Path) -> None:
    """Prove removed transfer paths and unnamed trailing storage are absent."""

    disassembly = run([str(objdump), "-dr", str(obj)])
    symbols = run([str(objdump), "-t", str(obj)])
    for removed in (
        "bf_short_run",
        "CPU_DIRECT_MAX_WORDS",
        "DMA_RUN_FASTPATH",
        "VBLANK_RUN_SPLIT",
    ):
        if re.search(rf"\b{re.escape(removed)}\b", symbols):
            raise AssertionError(f"{obj}: removed symbol is still linked: {removed}")

    run_start = re.search(
        r"^[0-9a-f]+ <bf_run_lp>:$", disassembly, re.MULTILINE)
    run_end = re.search(
        r"^[0-9a-f]+ <bf_run_done>:$", disassembly, re.MULTILINE)
    if not run_start or not run_end or run_start.start() >= run_end.start():
        raise AssertionError(f"{obj}: missing pattern-run transfer block")
    run_block = disassembly[run_start.end():run_end.start()]
    if not re.search(r"\bbra\w*\s+[^\n]*<bf_split_run>", run_block):
        raise AssertionError(f"{obj}: residual overflow does not enter split path")
    if re.search(r"\bmovel\s+%a3@\+,[^\n]*<VDP_DATA>", run_block):
        raise AssertionError(f"{obj}: removed CPU pattern-body writer is still linked")

    headers = run([str(objdump), "-h", str(obj)])
    bss = re.search(
        r"^\s*\d+\s+\.bss\s+([0-9a-fA-F]+)\b",
        headers,
        re.MULTILINE,
    )
    end = re.search(
        r"^([0-9a-fA-F]+)\s+\w\s+\.bss\s+[0-9a-fA-F]+\s+"
        r"player_bss_end$",
        symbols,
        re.MULTILINE,
    )
    if not bss or not end:
        raise AssertionError(f"{obj}: cannot prove named BSS boundary")
    if int(end.group(1), 16) != int(bss.group(1), 16):
        raise AssertionError(
            f"{obj}: unnamed trailing BSS remains after player_bss_end")


def verify_runtime_vblank_cadence(
    objdump: Path, obj: Path,
) -> None:
    """Prove runtime diagnostics follow the current periodic cadence target."""
    disassembly = run([str(objdump), "-dr", str(obj)])
    start = re.search(
        r"^[0-9a-f]+ <bf_wait_fixed_flip_vblank>:$",
        disassembly, re.MULTILINE)
    end = re.search(
        r"^[0-9a-f]+ <bf_patch_dbg_row>:$",
        disassembly, re.MULTILINE)
    if not start or not end or start.start() >= end.start():
        raise AssertionError(f"{obj}: missing runtime cadence block")
    shared = disassembly[start.end():end.start()]
    target_addr = symbol_address(objdump, obj, "pace_target_vblanks")
    if not re.search(
            rf"\bcmpw\s+0 [^\n]*,%d0\n"
            rf"\s+[^\n]*R_68K_32\s+\.bss\+0x{target_addr:x}", shared):
        raise AssertionError(
            f"{obj}: transfer-window accounting ignores the periodic target")

    addresses = [
        symbol_address(objdump, obj, f"pattern_vblank{index}_words")
        for index in range(1, 5)
    ]
    if addresses != list(range(addresses[0], addresses[0] + 8, 2)):
        raise AssertionError(
            f"{obj}: four runtime VBlank word counters are not contiguous")
    snapshot_start = re.search(
        r"^[0-9a-f]+ <bf_debug_snapshot_vbudget>:$",
        disassembly, re.MULTILINE)
    snapshot_end = re.search(
        r"^[0-9a-f]+ <bf_next_vbudget>:$",
        disassembly, re.MULTILINE)
    if not snapshot_start or not snapshot_end:
        raise AssertionError(f"{obj}: missing runtime VBlank snapshot helper")
    snapshot = disassembly[snapshot_start.end():snapshot_end.start()]
    if not re.search(r"\bmovel\s+%a1,%d0", snapshot):
        raise AssertionError(
            f"{obj}: runtime VBlank HUD words are not kept separate from cost")
    if not re.search(r"\bcmpiw\s+#4,%d6", snapshot):
        raise AssertionError(
            f"{obj}: runtime VBlank snapshot is still limited to two groups")


def verify_startup_body_arm(objdump: Path, obj: Path) -> None:
    """Prove the single startup command spans frame -1 through frame 0."""
    disassembly = run([str(objdump), "-d", str(obj)])

    def function_block(name: str) -> str:
        match = re.search(
            rf"^[0-9a-f]+ <{re.escape(name)}>:$", disassembly, re.MULTILINE)
        if not match:
            raise AssertionError(f"{obj}: missing {name}")
        next_match = re.search(
            r"^[0-9a-f]+ <[^>]+>:$",
            disassembly[match.end():],
            re.MULTILINE,
        )
        end = match.end() + next_match.start() if next_match else len(disassembly)
        return disassembly[match.end():end]

    loop_match = re.search(
        r"^[0-9a-f]+ <play_loop>:$", disassembly, re.MULTILINE)
    loop_end_match = re.search(
        r"^[0-9a-f]+ <movie_end_md>:$", disassembly, re.MULTILINE)
    if not loop_match or not loop_end_match:
        raise AssertionError(f"{obj}: missing play-loop symbols")
    loop = disassembly[loop_match.end():loop_end_match.start()]
    build_call = re.search(r"\bbsr\w*\s+[^\n]*<build_frame>", loop)
    start_call = re.search(r"\bbsr\w*\s+[^\n]*<start_playback>", loop)
    if not build_call or not start_call or build_call.start() >= start_call.start():
        raise AssertionError(
            f"{obj}: playback start does not follow the completed frame-0 build")

    start_wait = (
        function_block("cmd_wait_startup")
        if re.search(
            r"^[0-9a-f]+ <cmd_wait_startup>:$", disassembly, re.MULTILINE)
        else ""
    )
    generic_wait = function_block("cmd_wait_ready")
    start = function_block("start_playback")
    stage_ack = r"\bmovew\s+#1,(?:00)?a12012 <GA_COMCMD1>"
    stage_copy = r"\bbsr\w*\s+[^\n]*<consume_boot_stage>"
    command_clear = r"\bmovew\s+#0,(?:00)?a12010 <GA_COMCMD0>"
    for name, block in (
            ("startup", start_wait),
            ("generic", generic_wait)):
        if not block:
            continue
        if len(re.findall(stage_ack, block)) != 1 or not re.search(stage_copy, block):
            raise AssertionError(
                f"{obj}: {name} wait must acknowledge exactly one copied "
                "boot stage")
        if re.search(command_clear, block):
            raise AssertionError(
                f"{obj}: {name} clears CMD_STREAM before frame 0 is visible")
    if len(re.findall(command_clear, start)) != 1:
        raise AssertionError(
            f"{obj}: start_playback must clear exactly one CMD_STREAM command")
    if re.search(stage_ack, start):
        raise AssertionError(
            f"{obj}: start_playback reintroduces a second startup handshake")

    frame_minus_one = function_block("show_frame_minus_one")
    if not re.search(r"\bmovew\s+#-1,", frame_minus_one):
        raise AssertionError(f"{obj}: frame -1 does not publish frame=FFFF")
    for callee in ("prepare_dbg", "hud_dma_flip", "wait_vblank"):
        if not re.search(
                rf"\bbsr\w*\s+[^\n]*<{callee}>", frame_minus_one):
            raise AssertionError(
                f"{obj}: frame -1 is missing its {callee} call")


def verify_adpcm_decode_pump(
    objdump: Path, obj: Path, *, expected: bool,
) -> None:
    """Require the low-rate specialized decoder to service the CDC mid-chunk."""
    disassembly = run([str(objdump), "-d", str(obj)])
    start_match = re.search(
        r"^[0-9a-f]+ <decode_adpcm_chunk>:$", disassembly, re.MULTILINE)
    end_match = re.search(
        r"^[0-9a-f]+ <write_wave_chunk>:$", disassembly, re.MULTILINE)
    if not start_match or not end_match:
        raise AssertionError(f"{obj}: missing ADPCM decoder symbols")
    block = disassembly[start_match.end():end_match.start()]
    found = bool(re.search(r"\bbsr\w*\s+[^\n]*<pump_poll>", block))
    if found != expected:
        state = "present" if found else "absent"
        wanted = "present" if expected else "absent"
        raise AssertionError(
            f"{obj}: decoder pump is {state}, expected {wanted}")


def verify_centered_nt_dma(
    objdump: Path, obj: Path, *, tcols: int, trows: int,
) -> None:
    """Prove the logical grid becomes one exact centered 64-pitch DMA band."""
    disassembly = run([str(objdump), "-dr", str(obj)])
    start_match = re.search(
        r"^[0-9a-f]+ <bf_stage_nt>:$", disassembly, re.MULTILINE)
    end_match = re.search(
        r"^[0-9a-f]+ <bf_dma>:$", disassembly, re.MULTILINE)
    if not start_match or not end_match:
        raise AssertionError(f"{obj}: missing bf_stage_nt/bf_dma symbols")
    block = disassembly[start_match.end():end_match.start()]
    long_copies = len(re.findall(r"\bmovel\s+%a0@\+,%a1@\+", block))
    word_copies = len(re.findall(r"\bmovew\s+%a0@\+,%a1@\+", block))
    if (long_copies, word_copies) != (tcols // 2, tcols & 1):
        raise AssertionError(
            f"{obj}: NT stage row copies {long_copies} longs/{word_copies} words, "
            f"expected {tcols // 2}/{tcols & 1}")
    row_skip = (64 - tcols) * 2
    if not re.search(rf"\blea\s+%a1@\({row_skip}\),%a1", block):
        raise AssertionError(f"{obj}: NT stage row skip is not {row_skip} bytes")
    if not re.search(rf"\bmove(?:w|q)\s+#{trows},%d0", block):
        raise AssertionError(f"{obj}: NT stage row count is not {trows}")

    dma_match = re.search(
        r"^[0-9a-f]+ <nt_dma_flip>:$", disassembly, re.MULTILINE)
    dma_end_match = re.search(
        r"^[0-9a-f]+ <hud_dma_flip>:$", disassembly, re.MULTILINE)
    if not dma_match or not dma_end_match:
        raise AssertionError(f"{obj}: missing NT stage/DMA symbols")
    dma = disassembly[dma_match.end():dma_end_match.start()]
    screen_cols = 40
    expected_dst = (
        0xE000
        + (((28 - trows) // 2) * 64 + (screen_cols - tcols) // 2) * 2
    )
    expected_words = (trows - 1) * 64 + tcols
    dst = re.search(r"\bmovel\s+#(-?\d+),%d3", dma)
    words = re.search(r"\bmovew\s+#(-?\d+),%d6", dma)
    if not dst or int(dst.group(1)) & 0xFFFF != expected_dst:
        actual = None if not dst else int(dst.group(1)) & 0xFFFF
        raise AssertionError(
            f"{obj}: NT DMA destination is {actual}, expected {expected_dst}")
    if not words or int(words.group(1)) & 0xFFFF != expected_words:
        actual = None if not words else int(words.group(1)) & 0xFFFF
        raise AssertionError(
            f"{obj}: NT DMA length is {actual}, expected {expected_words}")
    if not re.search(r"\bbra\w*\s+[^\n]*<dma_chunk>", dma):
        raise AssertionError(f"{obj}: name-table transfer is not one Main-RAM DMA")


def build_case(
    case: Case, case_dir: Path, *, specialized: bool,
    assembler: Path, linker: Path, size: Path, objdump: Path,
) -> Build:
    tag = "specialized" if specialized else "generic"
    common = [
        str(assembler), "-m68000", "--register-prefix-optional", "--bitwise-or",
        "--defsym", "DEBUG=1",
    ]
    fixed = ["--defsym", "PLAYER_SPECIALIZED=1"] if specialized else []
    includes = ["-I", str(case_dir), "-I", str(ROOT / "boot")]

    sp_extension_obj = case_dir / f"sp-ext-{tag}.o"
    sp_extension_bin = case_dir / f"sp-ext-{tag}.bin"
    run(common[:4] + fixed + includes + [
        str(ROOT / "boot/movieplay_sp_ext.s"),
        "-o", str(sp_extension_obj),
    ])
    run([
        str(linker), "-nostdlib", "--oformat", "binary",
        "-T", str(ROOT / "cfg/sp_ext.ld"),
        "-o", str(sp_extension_bin), str(sp_extension_obj),
    ])
    extension_constants = case_dir / "sp_extension.inc"
    sp_extension.generate(sp_extension_bin, extension_constants)
    run([
        sys.executable, str(TOOLS / "check_player_ring.py"),
        "--constants", str(case_dir / "player_constants.inc"),
        "--extension", str(sp_extension_bin),
        "--extension-constants", str(extension_constants),
    ])

    ip_obj = case_dir / f"ip-{tag}.o"
    ip_bin = case_dir / f"ip-{tag}.bin"
    run(common + ["--defsym", "MAIN_CODEGEN=1"] + fixed + includes + [
        str(ROOT / "boot/movieplay_ip.s"), "-o", str(ip_obj)])
    run([
        str(linker), "-nostdlib", "--oformat", "binary",
        "-T", str(ROOT / "cfg/ip.ld"), "-o", str(ip_bin), str(ip_obj),
    ])
    verify_startup_body_arm(objdump, ip_obj)
    verify_transfer_cleanup(objdump, ip_obj)
    verify_flip_control_flow(objdump, ip_obj)
    verify_early_nonblocking_swap(
        objdump, ip_obj, expected_frames=TEST_FRAMES,
        specialized=specialized)
    if specialized:
        tcols = case.tcols or 40
        verify_centered_nt_dma(
            objdump, ip_obj, tcols=tcols, trows=case.trows)
        if av_config.uses_fixed_n_cadence(case.fps):
            verify_shared_deadline_vblank(
                objdump, ip_obj, tcols=tcols, trows=case.trows)
            verify_runtime_vblank_cadence(
                objdump, ip_obj)
            release_ip_obj = case_dir / "ip-specialized-release.o"
            run(common[:4] + ["--defsym", "MAIN_CODEGEN=1"] + fixed + includes + [
                str(ROOT / "boot/movieplay_ip.s"), "-o", str(release_ip_obj)])
            verify_early_nonblocking_swap(
                objdump, release_ip_obj, expected_frames=TEST_FRAMES,
                specialized=True)

    sp_obj = case_dir / f"sp-{tag}.o"
    sp_bin = case_dir / f"sp-{tag}.bin"
    run(common + fixed + includes + [
        str(ROOT / "boot/movieplay_sp.s"), "-o", str(sp_obj),
    ])
    run([
        str(linker), "-nostdlib", "--oformat", "binary",
        "-T", str(ROOT / "cfg/sp.ld"), "-o", str(sp_bin), str(sp_obj),
    ])
    if specialized:
        verify_adpcm_decode_pump(
            objdump, sp_obj, expected=case.fps < 24)

    return Build(
        ip_text=text_size(size, ip_obj),
        ip_bin=ip_bin.stat().st_size,
        sp_text=text_size(size, sp_obj),
        sp_bin=sp_bin.stat().st_size,
        sp_extension_bin=sp_extension_bin.stat().st_size,
    )


def main() -> None:
    assembler = find_tool("m68k-elf-as")
    linker = find_tool("m68k-elf-ld")
    size = find_tool("m68k-elf-size")
    objdump = find_tool("m68k-elf-objdump")
    objcopy = find_tool("m68k-elf-objcopy")
    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)

    print("case      IP generic->specialized   SP generic->specialized")
    with tempfile.TemporaryDirectory(prefix="player_constants_", dir=tmp_root) as td:
        matrix_dir = Path(td)
        for case in CASES:
            case_dir = matrix_dir / case.name
            case_dir.mkdir()
            header = make_header(case)
            header_path = case_dir / "HEADER.DAT"
            header_path.write_bytes(header)
            # Minimal player-embedded palette tables: one all-black segment
            # and an all-sentinel switch table.
            (case_dir / "paltab.bin").write_bytes(bytes(128))
            (case_dir / "palidx.bin").write_bytes(
                struct.pack(">HH", 0xFFFF, 0) * 16)
            constants = player_constants.generate_include(
                header_path, case_dir / "player_constants.inc")

            generic = build_case(
                case, case_dir, specialized=False,
                assembler=assembler, linker=linker, size=size, objdump=objdump)
            specialized = build_case(
                case, case_dir, specialized=True,
                assembler=assembler, linker=linker, size=size, objdump=objdump)
            verify_boot_image(
                case_dir, assembler=assembler, objcopy=objcopy, objdump=objdump)

            for label, build in (("generic", generic), ("specialized", specialized)):
                if build.ip_bin > 18944:
                    raise AssertionError(
                        f"{case.name}: {label} IP is {build.ip_bin} bytes")
                if (
                    label == "specialized"
                    and build.sp_bin > av_config.SUB_BOOT_IMAGE_MAX_BYTES
                ):
                    raise AssertionError(
                        f"{case.name}: {label} SP is {build.sp_bin} bytes")
                if build.sp_extension_bin > av_config.SUB_BOOT_EXTENSION_MAX_BYTES:
                    raise AssertionError(
                        f"{case.name}: {label} SP extension is "
                        f"{build.sp_extension_bin} bytes")

            sp_bytes = (case_dir / "sp-specialized.bin").read_bytes()
            if struct.pack(">L", constants.signature) not in sp_bytes:
                raise AssertionError(
                    f"{case.name}: SP does not contain HEADER signature immediate")
            if struct.pack(">H", 0xBAD1) not in sp_bytes:
                raise AssertionError(f"{case.name}: SP has no mismatch diagnostic")

            print(
                f"{case.name:<9} "
                f"{generic.ip_bin:4}->{specialized.ip_bin:4}B "
                f"(text {generic.ip_text:4}->{specialized.ip_text:4})   "
                f"{generic.sp_bin:4}->{specialized.sp_bin:4}B "
                f"(text {generic.sp_text:4}->{specialized.sp_text:4}) "
                f"ext {generic.sp_extension_bin}->{specialized.sp_extension_bin}B")

    print("player constant build matrix: OK")


if __name__ == "__main__":
    main()
