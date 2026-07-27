#!/usr/bin/env python3
"""Build the generic/specialized player matrix for issue #21."""

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
import ttrc_routing  # noqa: E402


@dataclass(frozen=True)
class Case:
    name: str
    mode: int
    fps: int
    pattern_supply: bool = False
    tcols: int | None = None
    trows: int = 28


CASES = (
    Case("h32-15", 0, 15),
    Case("h32-24-supply", 0, 24, True),
    Case("h32-30-supply", 0, 30, True),
    Case("h40-15", 1, 15),
    Case("h40-24-supply", 1, 24, True),
    Case("h40-30-supply", 1, 30, True),
    Case("h40-30-centered", 1, 30, True, 36, 25),
)


def find_tool(name: str) -> Path:
    found = shutil.which(name)
    if found:
        return Path(found)
    candidate = Path.home() / "toolchains/mars/m68k-elf/bin" / name
    if candidate.is_file():
        return candidate
    raise SystemExit(f"missing tool: {name}")


def make_header(case: Case) -> bytes:
    tcols = case.tcols if case.tcols is not None else (32 if case.mode == 0 else 40)
    trows = case.trows
    cells = tcols * trows
    frames = 600
    features = ttrc_routing.FEATURE_COLD_RUNS
    if av_config.uses_fixed_n2_cadence(case.fps):
        features |= ttrc_routing.FEATURE_FIXED_N2
    _rate, audio, _control = av_config.audio_frame_layout(case.fps)
    if case.pattern_supply:
        features |= (
            ttrc_routing.FEATURE_PATTERN_SUPPLY
            | ttrc_routing.FEATURE_DICBUF_INDEXED_RUNS)
    audio_fd = av_config.rf5c164_fd(
        audio, av_config.playback_fps_for_content(case.fps))
    prefix = struct.pack(
        ">4s9H4LBB3L6H",
        b"TTRC", ttrc_routing.VERSION, frames, tcols, trows, cells,
        1400, 1, ttrc_routing.FRAME_SECTORS, 1,
        12416, ttrc_routing.routing_sector_count(frames), 194, 12416,
        case.mode, 0, 2, 18 if case.mode else 14,
        av_config.PALTAB_STAGE_KB * 1024 // 2048,
        av_config.vsync_n_for_fps(case.fps), audio, case.fps,
        audio_fd, 30, features,
    )
    sector = bytearray(
        prefix + bytes(128) + bytes(player_constants.SECTOR - 192))
    if case.pattern_supply:
        cold_cap = av_config.baseline_cold_cap_for_fps(case.fps)
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
    """Keep flip branches local and prove the final VBlank guard ordering."""
    disassembly = run([str(objdump), "-d", str(obj)])
    start_match = re.search(r"^([0-9a-f]+) <bf_doflip>:$", disassembly, re.MULTILINE)
    end_match = re.search(r"^([0-9a-f]+) <bf_after_flip>:$", disassembly, re.MULTILINE)
    if not start_match or not end_match:
        raise AssertionError(f"{obj}: missing bf_doflip symbols")
    start = int(start_match.group(1), 16)
    end = int(end_match.group(1), 16)
    block = disassembly[start_match.end():end_match.start()]
    branches = re.findall(
        r"^\s*[0-9a-f]+:\s+(?:[0-9a-f]{4}\s+)+"
        r"(?!bsr)(b[a-z]+)\s+([0-9a-f]+)\s+<",
        block,
        re.MULTILINE,
    )
    escaped = [
        (mnemonic, int(target, 16))
        for mnemonic, target in branches
        if not start <= int(target, 16) <= end
    ]
    if escaped:
        details = ", ".join(f"{op}->0x{target:X}" for op, target in escaped)
        raise AssertionError(f"{obj}: bf_doflip branch escaped its region: {details}")

    guard_match = re.search(
        r"^([0-9a-f]+) <do_flip>:$", disassembly, re.MULTILINE)
    guard_end_match = re.search(
        r"^([0-9a-f]+) <dma_chunk_wr>:$", disassembly, re.MULTILINE)
    if not guard_match or not guard_end_match:
        raise AssertionError(f"{obj}: missing do_flip guard symbols")
    guard_start = int(guard_match.group(1), 16)
    guard_end = int(guard_end_match.group(1), 16)
    guard = disassembly[guard_match.end():guard_end_match.start()]
    status_reads = list(re.finditer(
        r"\bmovew\s+(?:00)?c00004 <VDP_CTRL>,%d0", guard))
    hv_read = re.search(r"\bmovew\s+(?:00)?c00008 <VDP_HV>,%d0", guard)
    tail_check = re.search(r"\bcmpiw\s+#-1024,%d0", guard)
    fresh_wait = re.search(r"\bbsr\w*\s+[^\n]*<wait_vb_start>", guard)
    plane_write = re.search(
        r"\bmovew\s+%d5,(?:00)?c00004 <VDP_CTRL>", guard)
    if (len(status_reads) != 2 or hv_read is None or tail_check is None or
            fresh_wait is None or plane_write is None):
        raise AssertionError(f"{obj}: incomplete final VBlank guard")
    positions = (
        status_reads[0].start(), hv_read.start(), tail_check.start(),
        status_reads[1].start(), fresh_wait.start(), plane_write.start(),
    )
    if positions != tuple(sorted(positions)):
        raise AssertionError(f"{obj}: final VBlank guard is out of order")

    guard_branches = re.findall(
        r"^\s*[0-9a-f]+:\s+(?:[0-9a-f]{4}\s+)+"
        r"(?!bsr)(b[a-z]+)\s+([0-9a-f]+)\s+<",
        guard,
        re.MULTILINE,
    )
    if len(guard_branches) < 3:
        raise AssertionError(f"{obj}: final VBlank guard branches are missing")
    escaped = [
        (mnemonic, int(target, 16))
        for mnemonic, target in guard_branches
        if not guard_start <= int(target, 16) < guard_end
    ]
    if escaped:
        details = ", ".join(f"{op}->0x{target:X}" for op, target in escaped)
        raise AssertionError(f"{obj}: do_flip branch escaped its region: {details}")


def verify_startup_body_arm(objdump: Path, obj: Path) -> None:
    """Prove BODY is acknowledged only after the Main frame-0 build."""
    disassembly = run([str(objdump), "-d", str(obj)])
    loop_match = re.search(
        r"^[0-9a-f]+ <play_loop>:$", disassembly, re.MULTILINE)
    loop_end_match = re.search(
        r"^[0-9a-f]+ <movie_end_md>:$", disassembly, re.MULTILINE)
    if not loop_match or not loop_end_match:
        raise AssertionError(f"{obj}: missing play-loop symbols")
    loop = disassembly[loop_match.end():loop_end_match.start()]
    build_call = re.search(r"\bbsr\w*\s+[^\n]*<build_frame>", loop)
    arm_call = re.search(r"\bbsr\w*\s+[^\n]*<arm_body_after_frame0>", loop)
    if not build_call or not arm_call or build_call.start() >= arm_call.start():
        raise AssertionError(
            f"{obj}: BODY arm does not follow the completed frame-0 build")

    startup_match = re.search(
        r"^[0-9a-f]+ <cmd_wait_startup>:$", disassembly, re.MULTILINE)
    generic_match = re.search(
        r"^[0-9a-f]+ <cmd_wait_ready>:$", disassembly, re.MULTILINE)
    arm_match = re.search(
        r"^[0-9a-f]+ <arm_body_after_frame0>:$", disassembly, re.MULTILINE)
    arm_end_match = re.search(
        r"^[0-9a-f]+ <load_boot_vram_sidecar>:$", disassembly, re.MULTILINE)
    if not all((generic_match, arm_match, arm_end_match)):
        raise AssertionError(f"{obj}: missing startup-handshake symbols")
    start_wait = (
        disassembly[startup_match.end():generic_match.start()]
        if startup_match else "")
    generic_wait = disassembly[generic_match.end():arm_match.start()]
    arm = disassembly[arm_match.end():arm_end_match.start()]
    body_ack = r"\bmovew\s+#1,(?:00)?a12012 <GA_COMCMD1>"
    stage_copy = r"\bbsr\w*\s+[^\n]*<consume_boot_stage>"
    for name, block in (
            ("startup", start_wait),
            ("generic", generic_wait)):
        if not block:
            continue
        if len(re.findall(body_ack, block)) != 1 or not re.search(stage_copy, block):
            raise AssertionError(
                f"{obj}: {name} wait must acknowledge exactly one copied "
                "boot stage")
    if not re.search(body_ack, arm):
        raise AssertionError(f"{obj}: post-frame-0 BODY acknowledgement is missing")


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
    """Prove that fixed-N2 H40 staging centers the encoded grid."""
    disassembly = run([str(objdump), "-dr", str(obj)])
    start_match = re.search(
        r"^[0-9a-f]+ <bf_blit>:$", disassembly, re.MULTILINE)
    end_match = re.search(
        r"^[0-9a-f]+ <bf_dma>:$", disassembly, re.MULTILINE)
    if not start_match or not end_match:
        raise AssertionError(f"{obj}: missing bf_blit/bf_dma symbols")
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
    if not re.search(rf"\bmovew\s+#{trows - 1},%d0", block):
        raise AssertionError(f"{obj}: NT stage row count is not {trows}")

    stage_match = re.search(
        r"\blea\s+0 [^\n]*,%a1\n"
        r"\s+[^\n]*R_68K_32\s+\.bss\+0x([0-9a-f]+)",
        block,
    )
    dma_match = re.search(
        r"^[0-9a-f]+ <nt_dma_flip>:$", disassembly, re.MULTILINE)
    dma_end_match = re.search(
        r"^[0-9a-f]+ <set_vram_write>:$", disassembly, re.MULTILINE)
    if not stage_match or not dma_match or not dma_end_match:
        raise AssertionError(f"{obj}: missing NT stage/DMA symbols")
    dma = disassembly[dma_match.end():dma_end_match.start()]
    base_match = re.search(
        r"\bmovel\s+#0,%d2\n"
        r"\s+[^\n]*R_68K_32\s+\.bss\+0x([0-9a-f]+)",
        dma,
    )
    if not base_match:
        raise AssertionError(f"{obj}: missing NT stage base relocation")
    actual_offset = int(stage_match.group(1), 16) - int(base_match.group(1), 16)
    expected_offset = (((28 - trows) // 2) * 64 + (40 - tcols) // 2) * 2
    if actual_offset != expected_offset:
        raise AssertionError(
            f"{obj}: NT stage offset is {actual_offset}, expected {expected_offset}")
    if "#-27904" not in dma or "#-27641" not in dma:
        raise AssertionError(
            f"{obj}: NT DMA length is not the full 64x28 aperture")


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
    run(common + [
        "--defsym", "MAIN_CODEGEN=1", "--defsym", "DMA_RUN_FASTPATH=1",
    ] + fixed + includes + [str(ROOT / "boot/movieplay_ip.s"), "-o", str(ip_obj)])
    run([
        str(linker), "-nostdlib", "--oformat", "binary",
        "-T", str(ROOT / "cfg/ip.ld"), "-o", str(ip_bin), str(ip_obj),
    ])
    verify_startup_body_arm(objdump, ip_obj)
    if specialized:
        verify_flip_control_flow(objdump, ip_obj)
        if case.mode == 1 and av_config.uses_fixed_n2_cadence(case.fps):
            verify_centered_nt_dma(
                objdump, ip_obj, tcols=case.tcols or 40, trows=case.trows)

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
            (case_dir / "palettes.bin").write_bytes(bytes(128))
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
                if build.ip_bin > 18688:
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
