#!/usr/bin/env python3
"""実機用の差分ストリーム(TTRC, B方式=セクタ間ストリーム分離)を決定ログから生成する。

唯一の真実源 = sim: simが CBRSIM_EMIT_DEC で吐く決定ログ(更新セル(cell,pal,key)＋
区間パレット)を再生してストリーム化。keyは64B(idx1..15)内包=32Bパターン復元可。

B方式の狙い: 連続CD読み(シーク無し=絶対ルール)を保ったまま、PRGリングへの書込を
**完全DMA(CDC_TRN)化**する(連続読み中のCPU-PRGバースト書込はSub-CPUを固める)。そのため
2ストリームをセクタ粒度でインタリーブ:
  payload: cold pattern(32B)連続 -> リングへDMA
  control: 毎フレーム apply-list+audio 可変長ブロック連続 -> apply-bufferへDMA(CPUはカーソルで処理)
control連続化でセクタ整列の無駄を回避 -> 149フル画質でPRGに収まる(A方式のセクタ整列は256/枚<消費で不可)。

TTRCレイアウト(v23): HEADER.DAT = Header(1sec) + BOOT_STAGE(optional boot-VRAM
              sidecar) + Dic + [ADPCM/WR0/WR1 preloads]
              + routing(1B/frame: total<<3 | n_ctrl_sec)
              + prebuffer(payload先頭Bpat)
              BODY.DAT = arm[startup audio][frame0 control][frame0 patterns]
              + frame1以降の [control][payload][rate pad]
MOVIE.DAT はツール互換用の HEADER.DAT || BODY.DAT 連結コンテナ。
パレット(PALTAB全区間)と切替表(PALIDX)はディスクに載せず、pack が
paltab.bin / palidx.bin としてplayerビルド入力へ書き、Main-IPイメージが内蔵する。
control block: >H total_len >H frame_seq >H n_upd
               ceil(cells/8) bitmap n_upd*(>H entry) audio [even pad]
               >H n_runs n_runs*(>H slot_start >H count)
  palette切替はboot搭載のM-PALIDX表起点(controlに切替バイトは無い)。
"""
import argparse
import dataclasses
import math
import pickle
import struct
import sys
from pathlib import Path
from collections import deque
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import av_config
import ima_adpcm
import player_constants
import pattern_supply
import physical_budget
import shadow_updates
import sp_extension
import stream_schedule
import ttrc_routing
import wordbuf_ring
import resource_tokens
import tmpfs_workspace
from encode_config import load_profile
from cbr_paths import sim_work_dir
from quantize_global4_tiles import pals_to_bytes
from quantize_md_video import rgb333_to_rgb888
from tile_alloc import (
    TileAllocator,
    cold_transfer_order,
    slot_runs,
)

SECTOR = 2048
MAGIC = b"TTRC"             # Tile Texture Reuse Codec
VERSION = ttrc_routing.VERSION
BASE = 1                     # POOL_TILE_BASE (VRAM tile index = BASE+slot)
FRAME_SECTORS = ttrc_routing.FRAME_SECTORS
PAT = 32
PAT_PER_SEC = SECTOR // PAT  # 64
NTSC_VSYNC = av_config.NTSC_VSYNC
# These values are populated from the decision log by configure_from_log().
# They are intentionally not read from CBRSIM_*: the log is the frozen encoder
# contract, and an unrelated inherited shell must not change the packed disc.
TCOLS = TROWS = C_CELLS = 0
TILE = 8
PATTERN_BYTES = 32
FPS = 0.0
VSYNC_N = 0
PLAYBACK_FPS = 0.0
AUDIO_RATE = 0
AUDIO_PCM = 0
AUDIO_CONTROL = 0
STARTUP_AUDIO_FRAMES = av_config.STARTUP_AUDIO_PREFETCH_FRAMES
PACK_FILL = av_config.PACK_FORWARD_FILL
PCM_SYNC_LEAD = 0x3000
PCM_SYNC_MAX = 0x6800
PCM_WAVE_RING_END = 0x8000
PCM_STARTUP_MARGIN = 0x0200
# リング諸元は tools/av_config.py の単一真実源から取る(sim/pack/playerで二重管理しない)。
# RING_SIZE はプレイヤの実 .equ RING_SIZE と一致(ビルド時 check_player_ring.py が検証)。
# Runtime profile fps selects the normal prebuffer ceiling and the scheduled
# delivery ceiling. The player physical ring and back-pressure stay fixed.
RING_SIZE_KB = av_config.RING_SIZE_KB
RING_CAP_KB = av_config.RING_CAP_KB
RING_CAP_PAT = RING_CAP_KB * 1024 // PAT
RING_DELIVERY_CAP_KB = av_config.scheduled_delivery_cap_kb(30)
RING_DELIVERY_CAP_PAT = RING_DELIVERY_CAP_KB * 1024 // PAT
RING_JITTER_HEADROOM_KB = av_config.RING_JITTER_HEADROOM_KB

FEATURE_COLD_RUNS = ttrc_routing.FEATURE_COLD_RUNS
FEATURE_FIXED_N = ttrc_routing.FEATURE_FIXED_N
FEATURE_PATTERN_SUPPLY = ttrc_routing.FEATURE_PATTERN_SUPPLY
FEATURE_SHADOW_UPDATE_LISTS = ttrc_routing.FEATURE_SHADOW_UPDATE_LISTS
FEATURE_VRAM_RAW_PREFETCH = ttrc_routing.FEATURE_VRAM_RAW_PREFETCH
FEATURE_DICBUF_INDEXED_RUNS = ttrc_routing.FEATURE_DICBUF_INDEXED_RUNS
FEATURE_BOOT_VRAM_SIDECAR = ttrc_routing.FEATURE_BOOT_VRAM_SIDECAR
FEATURE_WORDBUF_RING = ttrc_routing.FEATURE_WORDBUF_RING
ADPCM_TABLE_SECTORS = math.ceil(ima_adpcm.FULL_TABLE_BYTES / SECTOR)
ROUTING_MAX_FRAMES = ttrc_routing.MAX_FRAMES


def pack_key(key):
    a = np.frombuffer(key, np.uint8)
    out = bytearray()
    for y in range(8):
        for x in range(0, 8, 2):
            out.append((int(a[y * 8 + x]) << 4) | int(a[y * 8 + x + 1]))
    return bytes(out)


def load_log(path):
    with open(path, "rb") as f:
        return pickle.load(f)


def configure_from_log(log):
    """Populate pack constants from one frozen decision log.

    Legacy logs are accepted through their existing top-level fields.  No
    CBRSIM_* value participates in this function.
    """
    global TCOLS, TROWS, C_CELLS, TILE, PATTERN_BYTES
    global FPS, VSYNC_N, PLAYBACK_FPS, AUDIO_RATE
    global AUDIO_PCM, AUDIO_CONTROL
    global RING_CAP_KB, RING_CAP_PAT
    global RING_DELIVERY_CAP_KB, RING_DELIVERY_CAP_PAT
    global RING_JITTER_HEADROOM_KB

    cfg = log.get("config") or {}
    video = cfg.get("video") or {}
    timing = cfg.get("timing") or {}
    audio = cfg.get("audio") or {}
    hardware = cfg.get("hardware") or {}
    geom = log.get("geom")
    if geom is None:
        geom = (video.get("cols"), video.get("rows"), video.get("cells"), video.get("tile"))
    if not geom or any(value is None for value in geom):
        raise SystemExit("decision log has no complete geometry")
    TCOLS, TROWS, C_CELLS, TILE = map(int, geom)
    if TILE != 8 or C_CELLS != TCOLS * TROWS:
        raise SystemExit(
            f"invalid decision geometry: {TCOLS}x{TROWS} cells={C_CELLS} tile={TILE}")
    PATTERN_BYTES = 32

    FPS = float(timing.get("fps", log.get("fps", 0)))
    if FPS <= 0:
        raise SystemExit("decision log has no valid fps")
    expected_vsync_n = av_config.vsync_n_for_fps(FPS)
    VSYNC_N = int(timing.get("vsync_n", expected_vsync_n))
    if VSYNC_N != expected_vsync_n:
        raise SystemExit(
            f"decision log vsync_n={VSYNC_N} disagrees with fps={FPS} ({expected_vsync_n})")
    expected_playback_fps = av_config.playback_fps_for_content(FPS)
    PLAYBACK_FPS = float(timing.get("playback_fps", expected_playback_fps))
    if not math.isclose(PLAYBACK_FPS, expected_playback_fps, rel_tol=0, abs_tol=1e-9):
        raise SystemExit(
            f"decision log playback_fps={PLAYBACK_FPS} disagrees with fps={FPS} "
            f"({expected_playback_fps})")

    RING_CAP_KB = av_config.prg_buf_cap_kb(FPS)
    RING_CAP_PAT = RING_CAP_KB * 1024 // PAT
    RING_DELIVERY_CAP_KB = av_config.scheduled_delivery_cap_kb(FPS)
    RING_DELIVERY_CAP_PAT = RING_DELIVERY_CAP_KB * 1024 // PAT
    RING_JITTER_HEADROOM_KB = av_config.ring_jitter_headroom_kb(FPS)

    AUDIO_RATE = int(audio.get("rate", log.get("audio_rate", 0)))
    AUDIO_CONTROL = int(audio.get(
        "control_bytes", audio.get("frame_bytes", log.get("audio_frame_bytes", 0))))
    AUDIO_PCM = int(audio.get(
        "pcm_bytes", log.get("audio_pcm_bytes", AUDIO_CONTROL)))
    if AUDIO_RATE <= 0 or AUDIO_CONTROL <= 0 or AUDIO_PCM <= 0:
        raise SystemExit("decision log has no valid audio rate/frame size")
    try:
        expected_rate, expected_pcm, expected_control = av_config.audio_frame_layout(FPS)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    if (AUDIO_RATE, AUDIO_PCM, AUDIO_CONTROL) != (
            expected_rate, expected_pcm, expected_control):
        raise SystemExit(
            "decision log audio layout "
            f"rate={AUDIO_RATE} pcm={AUDIO_PCM} control={AUDIO_CONTROL} "
            f"disagrees with ADPCM/{FPS:g}fps "
            f"({expected_rate}, {expected_pcm}, {expected_control})")
    checkpoint_bytes = int(audio.get("checkpoint_bytes", 0))
    expected_checkpoint = av_config.IMA_CHECKPOINT_BYTES
    if checkpoint_bytes != expected_checkpoint:
        raise SystemExit(
            f"decision log checkpoint_bytes={checkpoint_bytes} != "
            f"{expected_checkpoint} for ADPCM")

    sim_prg_buf = int(hardware.get(
        "prg_buf_kb",
        log.get("prg_buf_kb", log.get("tank_kb", RING_CAP_KB))))
    if sim_prg_buf != RING_CAP_KB:
        raise SystemExit(
            f"decision log prg_buf_kb={sim_prg_buf} != "
            f"hardware PrgBuf cap={RING_CAP_KB}; "
            "re-run sim with the current tools/av_config.py")
    sim_delivery_cap = int(hardware.get(
        "prg_delivery_cap_kb",
        log.get("prg_delivery_cap_kb", RING_DELIVERY_CAP_KB)))
    if sim_delivery_cap != RING_DELIVERY_CAP_KB:
        raise SystemExit(
            f"decision log prg_delivery_cap_kb={sim_delivery_cap} != "
            f"hardware delivery limit={RING_DELIVERY_CAP_KB}; "
            "re-run sim with the current tools/av_config.py")


def display_mode_name(log):
    """Return the frozen display mode without consulting the shell."""
    mode = str(
        log.get("mode")
        or (log.get("config") or {}).get("video", {}).get("mode", "")
    ).strip().upper()
    if not mode:
        mode = "H40" if TCOLS == 40 else "H32"
    if mode not in {"H32", "H40", "MODE4"}:
        raise SystemExit(
            f"pack: unsupported display mode in decision log: {mode!r}")
    return mode


def require_canonical_p0_debug_colours(log):
    """Reject stale logs without the fixed dark background and bright text."""
    seg_pals = log.get("seg_pals")
    if not seg_pals:
        raise SystemExit("pack v23: decision log has no segment palettes; re-run sim")
    for seg, pals in enumerate(seg_pals):
        a = np.asarray(pals, np.uint8)
        if a.shape != (4, 15, 3):
            raise SystemExit(
                f"pack v23: segment {seg} palette shape is {a.shape}, expected (4, 15, 3); "
                "re-run sim")
        brightness = a.astype(np.int16).sum(axis=2)
        if int(brightness[0, 0]) != int(brightness.min()):
            raise SystemExit(
                f"pack v23: decision log segment {seg} P0 index1 is not tied for globally "
                "darkest usable CRAM colour (RGB sum); re-run sim with the current encoder")
        if int(brightness[0, 14]) != int(brightness.max()):
            raise SystemExit(
                f"pack v23: decision log segment {seg} P0 index15 is not tied for globally "
                "brightest usable CRAM colour (RGB sum); re-run sim with the current encoder")


def pals_to_bytes_128(pal_4x15):
    b = pals_to_bytes([np.asarray(pal_4x15[p], np.uint8) for p in range(4)])
    assert len(b) == 128, len(b)
    return b


def build_bitmap(cells):
    return shadow_updates.build_bitmap(cells, C_CELLS)


def resolve(log, POOL, mode="lru"):
    """検証済み LRU+ダブルバッファ保護スロットモデルで cold を検出。
       mode="contig": クロックハンド円環走査でフレーム内coldを昇順(なるべく連番)スロットへ
       割当 -> MD側が連続ランを少数の大DMAにまとめられる。
       per=[(cells,entries,colds)], transfer_orders, n_load, n_upd, pal_w,
       P(物理slot順cold pattern 32B) を返す。"""
    frames = log["frames"]
    frame_seg = np.asarray(log["frame_seg"], np.int64)
    nfr = len(frames)
    alloc = TileAllocator(C_CELLS, POOL, BASE)   # 共有割り当て(連続)。sim も同一 = cap=realized
    per = []
    transfer_orders = []
    n_load = np.zeros(nfr, np.int64)
    n_upd = np.zeros(nfr, np.int64)
    pal_w = np.zeros(nfr, np.int64)
    Plist = []
    raw_prefetch = log.get("raw_prefetch") or {}
    prefetch_enabled = bool(raw_prefetch.get("enabled", False))
    raw_requests = raw_prefetch.get("requests", ())
    if prefetch_enabled and len(raw_requests) != nfr:
        raise SystemExit("pack: raw-prefetch frame count differs from decisions")
    prefetch_per = []
    physical_patterns = [None] * POOL
    displayed_slots = np.full(C_CELLS, -1, np.int64)
    expected_patterns = [None] * C_CELLS

    for i in range(nfr):
        fr = sorted(frames[i], key=lambda t: t[0])
        results = alloc.place_frame(
            [(int(cell), key) for (cell, pal, key) in fr], i)
        transfer_order = cold_transfer_order(results)
        pal_w[i] = 1 if (i == 0 or frame_seg[i] != frame_seg[i - 1]) else 0
        cells, entries, colds = [], [], []
        for (cell, pal, key), (slot, cold) in zip(fr, results):
            if cold:
                n_load[i] += 1
            cells.append(int(cell))
            entries.append((int(pal) << 13) | (BASE + slot))
            colds.append(cold)
            n_upd[i] += 1
        Plist.extend(pack_key(fr[index][2]) for index in transfer_order)
        for index in transfer_order:
            physical_patterns[results[index][0]] = fr[index][2]
        frame_prefetch = []
        if prefetch_enabled:
            for request in raw_requests[i]:
                if len(request) == 2:
                    key, deadline = request
                    forced_slot = None
                elif len(request) == 3:
                    key, deadline, forced_slot = request
                else:
                    raise SystemExit(
                        f"pack: malformed raw-prefetch request at frame {i}")
                result = alloc.prefetch(
                    key, i, int(deadline), forced_slot=forced_slot)
                if result is None:
                    raise SystemExit(
                        f"pack: raw-prefetch allocation diverged at frame {i}")
                physical_slot, cold = result
                if cold:
                    n_load[i] += 1
                    physical_patterns[physical_slot] = key
                frame_prefetch.append(
                    (physical_slot, bool(cold), key, int(deadline)))
        # The prefetch suffix is independent of visible name updates. Emit its
        # payload in physical-slot order so its run descriptors describe the
        # same long transfers modeled by sim.
        frame_prefetch.sort(key=lambda item: int(item[0]))
        Plist.extend(
            pack_key(item[2]) for item in frame_prefetch if bool(item[1]))
        for (cell, _pal, key), (physical_slot, _cold) in zip(fr, results):
            displayed_slots[int(cell)] = int(physical_slot)
            expected_patterns[int(cell)] = key
        for cell, expected in enumerate(expected_patterns):
            if expected is None:
                continue
            physical_slot = int(displayed_slots[cell])
            if physical_patterns[physical_slot] != expected:
                raise SystemExit(
                    f"pack: slot display mismatch at frame {i}, "
                    f"cell {cell}, physical slot {physical_slot}")
        prefetch_per.append(frame_prefetch)
        transfer_orders.append(transfer_order)
        per.append((cells, entries, colds))
        if (i + 1) % 400 == 0:
            print(f"  resolve {i+1}/{nfr}", flush=True)
    frozen_cold = np.asarray(raw_prefetch.get("cold", ()), np.int64)
    if prefetch_enabled:
        actual_cold = np.asarray([
            sum(bool(item[1]) for item in frame) for frame in prefetch_per
        ], np.int64)
        if frozen_cold.shape != actual_cold.shape or not np.array_equal(
                frozen_cold, actual_cold):
            raise SystemExit("pack: raw-prefetch cold trace differs from simulation")
    print(
        f"  physical-slot display照合: {nfr}/{nfr} frames exact")
    return (
        per, prefetch_per, tuple(transfer_orders), n_load, n_upd, pal_w,
        Plist, alloc.tearing)


def sourced_cold_runs(entries, colds, sources, dic_indices=None):
    """Return indexed runs split on slot, source, or DicBuf index gaps."""
    if dic_indices is None:
        dic_indices = (-1,) * len(entries)
    runs = []
    start = previous = source = start_dic = previous_dic = None
    count = 0
    for entry, cold, item_source, item_dic in zip(
            entries, colds, sources, dic_indices):
        if not cold:
            continue
        slot = (int(entry) & 0x07FF) - BASE
        item_source = int(item_source)
        item_dic = int(item_dic)
        split_dic = (
            bool(count) and item_source == pattern_supply.SOURCE_DIC
            and (item_dic != previous_dic + 1
                 or item_dic % pattern_supply.DIC_RUN_BLOCK == 0))
        if count and (
                slot != previous + 1 or item_source != source or split_dic):
            runs.append((start, count, source, start_dic))
            count = 0
        if not count:
            start = slot
            source = item_source
            start_dic = item_dic if item_source == pattern_supply.SOURCE_DIC else 0
        previous = slot
        previous_dic = item_dic
        count += 1
    if count:
        runs.append((start, count, source, start_dic))
    return runs


def sourced_transfer_runs(
        entries, colds, sources, prefetch=(), dic_indices=None,
        transfer_order=None):
    """Return update cold runs followed by optional Prg prefetch runs."""
    if transfer_order is None:
        transfer_order = tuple(
            index for index, cold in enumerate(colds) if cold)
    else:
        transfer_order = tuple(int(index) for index in transfer_order)
    expected = {index for index, cold in enumerate(colds) if cold}
    if len(transfer_order) != len(expected) or set(transfer_order) != expected:
        raise ValueError("transfer order must cover every cold update exactly once")
    slots = [
        (int(entries[index]) & 0x07FF) - BASE
        for index in transfer_order
    ]
    item_sources = [
        int(sources[index])
        for index in transfer_order
    ]
    cold_prefetch = sorted(
        (item for item in prefetch if bool(item[1])),
        key=lambda item: int(item[0]),
    )
    slots.extend(int(item[0]) for item in cold_prefetch)
    item_sources.extend(
        pattern_supply.SOURCE_PRG for _item in cold_prefetch)
    if dic_indices is None:
        dic_indices = (-1,) * len(entries)
    run_dic_indices = [
        int(dic_indices[index]) for index in transfer_order
    ]
    run_dic_indices.extend(-1 for _item in cold_prefetch)
    return list(pattern_supply.source_runs(
        slots, item_sources, run_dic_indices))


def split_boot_prefetch(log, prefetch_per):
    """Split frame-0 prefetch into the ordinary control path and boot sidecar."""
    if not prefetch_per:
        return tuple(prefetch_per), ()
    raw = log.get("raw_prefetch") or {}
    schema = int(raw.get("schema_version", 0))
    frame0 = tuple(prefetch_per[0])
    cold_count = sum(bool(item[1]) for item in frame0)
    if schema < 3:
        inline_count = cold_count
        sidecar_count = 0
    else:
        inline_count = int(raw.get("boot_inline_requests", -1))
        sidecar_count = int(raw.get("boot_sidecar_requests", -1))
        if min(inline_count, sidecar_count) < 0:
            raise SystemExit(
                "pack: schema-3 boot prefetch lacks inline/sidecar counts")
        if inline_count + sidecar_count != cold_count:
            raise SystemExit(
                "pack: boot-prefetch split differs from resolved frame 0")
    if any(not bool(item[1]) for item in frame0):
        raise SystemExit("pack: frame-0 boot prefetch must be entirely cold")
    inline = list(tuple(frame) for frame in prefetch_per)
    inline[0] = frame0[:inline_count]
    return tuple(inline), frame0[inline_count:inline_count + sidecar_count]


def run_stats(
        per, sources=None, prefetch_per=None, dic_indices=None,
        transfer_orders=None, boot_sidecar=(), loads_caps=None,
        word_capacities=None):
    """フレーム内cold tile数とplayer cold-run record数を返して表示する。"""
    runs_per_frame = np.zeros(len(per), np.int64)
    colds_per_frame = np.zeros(len(per), np.int64)
    if sources is None:
        sources = tuple(tuple(pattern_supply.SOURCE_PRG for _ in entries)
                        for _cells, entries, _colds in per)
    if prefetch_per is None:
        prefetch_per = tuple(() for _ in per)
    if dic_indices is None:
        dic_indices = tuple(tuple(-1 for _ in entries)
                            for _cells, entries, _colds in per)
    if transfer_orders is None:
        transfer_orders = tuple(None for _ in per)
    prg_per_frame = np.zeros(len(per), np.int64)
    wr_per_frame = np.zeros(len(per), np.int64)
    dic_per_frame = np.zeros(len(per), np.int64)
    word_cursors = [0, 0]
    for i, ((cells, entries, colds), frame_sources, frame_prefetch,
            frame_dic_indices, transfer_order) in enumerate(
            zip(per, sources, prefetch_per, dic_indices, transfer_orders)):
        runs = sourced_transfer_runs(
            entries, colds, frame_sources, frame_prefetch,
            frame_dic_indices, transfer_order)
        if word_capacities is not None:
            parity = i & 1
            runs, word_cursors[parity] = pattern_supply.split_word_ring_runs(
                runs,
                capacity=int(word_capacities[parity]),
                cursor=word_cursors[parity],
            )
        runs_per_frame[i] = len(runs)
        colds_per_frame[i] = sum(count for _slot, count, _source, _dic in runs)
        for _slot, count, source, _dic in runs:
            if source == pattern_supply.SOURCE_PRG:
                prg_per_frame[i] += count
            elif source == pattern_supply.SOURCE_WR:
                wr_per_frame[i] += count
            elif source == pattern_supply.SOURCE_DIC:
                dic_per_frame[i] += count
    # The boot sidecar writes directly from the temporary boot-stage handoff.
    # It is Cold work, but it is neither a PrgBuf source nor an O_LOADS run.
    sidecar_count = sum(bool(item[1]) for item in boot_sidecar)
    if sidecar_count:
        colds_per_frame[0] += sidecar_count
    tot_c = int(colds_per_frame.sum())
    tot_r = int(runs_per_frame.sum())
    run_colds_per_frame = colds_per_frame.copy()
    run_colds_per_frame[0] -= sidecar_count
    run_cold_total = int(run_colds_per_frame.sum())
    heavy = run_colds_per_frame >= 300
    msg = (f"run_stats: cold計{tot_c} run対象cold計{run_cold_total} run計{tot_r} "
           f"平均ラン長{run_cold_total / max(1, tot_r):.1f} "
           f"フレーム最大run数{int(runs_per_frame.max())}")
    if sidecar_count:
        msg += f" boot backside={sidecar_count}"
    if heavy.any():
        msg += (f"  重量フレーム(cold>=300, {int(heavy.sum())}枚): "
                f"平均run数{runs_per_frame[heavy].mean():.1f} "
                f"平均ラン長{(run_colds_per_frame[heavy].sum() / max(1, runs_per_frame[heavy].sum())):.1f}")
    print(msg)
    print(f"  source patterns: Prg={int(prg_per_frame.sum())} "
          f"Wr0={int(wr_per_frame[::2].sum())} Wr1={int(wr_per_frame[1::2].sum())} "
          f"Dic={int(dic_per_frame.sum())} BootSidecar={sidecar_count}")
    # O_LOADS v2 stores one VDP-ready 22-byte record per run and only ordinary
    # Prg patterns inline.
    # Wr/Dic runs point at their persistent preload instead of copying bytes.
    loads_bytes = (
        prg_per_frame * PAT
        + runs_per_frame * pattern_supply.OUTPUT_RUN_RECORD_BYTES
    )
    if loads_caps is not None:
        caps = tuple(int(value) for value in loads_caps)
        if len(caps) != 2:
            raise ValueError("O_LOADS capacities must contain Wr0 and Wr1")
        over = np.flatnonzero(
            loads_bytes > np.asarray(
                [caps[frame & 1] for frame in range(len(loads_bytes))],
                np.int64,
            )
        )
        if over.size:
            frame = int(over[0])
            raise SystemExit(
                f"pack: frame {frame} O_LOADS={int(loads_bytes[frame])}B "
                f"exceeds Wr{frame & 1} capacity {caps[frame & 1]}B")
        print(
            f"  loads領域 最大{int(loads_bytes.max())}B / "
            f"Wr0 {caps[0]}B, Wr1 {caps[1]}B")
    return colds_per_frame, runs_per_frame


def cold_runs(entries, colds):
    """Return the exact packed/player cold-run records for one frame."""
    return slot_runs(
        (int(entry) & 0x07FF) - BASE
        for entry, cold in zip(entries, colds)
        if cold
    )


def verify_sim_pattern_transfers(
        log, packed_tiles, packed_runs, supply_plan=None):
    """Require frozen sim transfer counts to match pack/player counts exactly.

    Old decision logs predate these fields and remain packable.  Every newly
    generated log carries them, turning a future run-grouping change into a
    pack-time failure instead of a misleading analysis meter.
    """
    frozen = log.get("pattern_transfers")
    if frozen is None:
        print("  pattern transfer照合: 旧decision logのため省略 (再simで有効化)")
        return False
    schema = int(frozen.get("schema_version", 0))
    if schema not in (1, 2, 3):
        raise SystemExit(
            "pack: unsupported pattern_transfers schema "
            f"{frozen.get('schema_version')!r}")

    expected = {
        "tiles": np.asarray(packed_tiles, np.int64),
        "runs": np.asarray(packed_runs, np.int64),
    }
    if schema >= 2:
        if supply_plan is None:
            raise SystemExit(
                "pack: schema-2 pattern transfer verification requires "
                "the materialized supply plan")
        expected.update({
            "prg": np.asarray(supply_plan.prg_loads, np.int64),
            "wr0": np.asarray(supply_plan.wr0_loads, np.int64),
            "wr1": np.asarray(supply_plan.wr1_loads, np.int64),
            "dic": np.asarray(supply_plan.dic_loads, np.int64),
        })
    if schema >= 3:
        expected["word_stage_sectors"] = np.asarray(
            supply_plan.word_stage_sectors, np.int64)
    for name, actual in expected.items():
        simulated = np.asarray(frozen.get(name, ()), np.int64)
        if simulated.shape != actual.shape:
            raise SystemExit(
                f"pack: sim/pack pattern {name} length mismatch: "
                f"sim={simulated.shape} pack={actual.shape}")
        mismatch = np.flatnonzero(simulated != actual)
        if mismatch.size:
            frame = int(mismatch[0])
            raise SystemExit(
                f"pack: sim/pack pattern {name} mismatch at frame {frame}: "
                f"sim={int(simulated[frame])} pack={int(actual[frame])}. "
                "TileAllocator/run grouping changed after simulation; re-run sim.")
    detail = "tiles/runs/sources" if schema >= 2 else "tiles/runs"
    print(f"  pattern transfer照合: {len(packed_runs)} frames {detail} exact")
    return True


def verify_sim_stream_schedule(log, packed_schedule):
    """Require the analysis BODY/RING trace to match the packed schedule."""
    frozen = log.get("stream_schedule")
    if frozen is None:
        raise SystemExit(
            "pack: decision log has no BODY delivery trace; re-run sim")
    if int(frozen.get("schema_version", 0)) != stream_schedule.STREAM_SCHEDULE_SCHEMA_VERSION:
        raise SystemExit(
            "pack: unsupported stream_schedule schema "
            f"{frozen.get('schema_version')!r}; re-run sim")

    expected = {
        "block_lengths": np.asarray(packed_schedule["blk_len"], np.int64),
        "ring_occupancy": np.asarray(
            packed_schedule["ring_occupancy"], np.int64),
        "ring_occupancy_before_consume": np.asarray(
            packed_schedule["ring_occupancy_before_consume"], np.int64),
        "payload_sectors": np.asarray(
            packed_schedule["n_pay_sec"], np.int64),
        "control_sectors": np.asarray(
            packed_schedule["n_ctrl_sec"], np.int64),
        "body_useful_payload_bytes": np.asarray(
            packed_schedule["body_useful_payload_bytes"], np.int64),
        "body_useful_control_bytes": np.asarray(
            packed_schedule["body_useful_control_bytes"], np.int64),
        "body_pad_bytes": np.asarray(
            packed_schedule["body_pad_bytes"], np.int64),
        "body_physical_bytes": np.asarray(
            packed_schedule["body_physical_bytes"], np.int64),
    }
    if "word_stage_sectors" in frozen:
        expected["word_stage_sectors"] = np.asarray(
            packed_schedule.get(
                "word_stage_sectors",
                np.zeros(len(expected["payload_sectors"]), np.int64),
            ),
            np.int64,
        )
    if "word_occupancy" in frozen:
        expected["word_occupancy"] = np.asarray(
            packed_schedule.get(
                "word_occupancy",
                np.zeros((len(expected["payload_sectors"]), 2), np.int64),
            ),
            np.int64,
        )
    for name, actual in expected.items():
        simulated = np.asarray(frozen.get(name, ()), np.int64)
        if simulated.shape != actual.shape:
            raise SystemExit(
                f"pack: sim/pack {name} length mismatch: "
                f"sim={simulated.shape} pack={actual.shape}")
        mismatch = np.argwhere(simulated != actual)
        if mismatch.size:
            frame = int(mismatch[0, 0])
            index = tuple(int(value) for value in mismatch[0])
            raise SystemExit(
                f"pack: sim/pack {name} mismatch at frame {frame}: "
                f"sim={int(simulated[index])} pack={int(actual[index])}. "
                "Control layout or delivery scheduling changed after simulation; "
                "re-run sim.")
    print(f"  BODY配送/RING照合: {len(expected['ring_occupancy'])} slots exact")
    return True


def verify_body_delivery_file(
        body_path, body_arm, stream_ctrl, stream_pay, schedule, *,
        stream_word=(b"", b""),
        prebuf_patterns):
    """Check the BODY arm prefix and every timed slot byte-for-byte."""
    n_pay = np.asarray(schedule["n_pay_sec"], np.int64)
    n_ctrl = np.asarray(schedule["n_ctrl_sec"], np.int64)
    n_word = np.asarray(
        schedule.get("word_stage_sectors", np.zeros(len(n_pay), np.int64)),
        np.int64,
    )
    fsec = np.asarray(schedule["fsec"], np.int64)
    useful_pay = np.asarray(schedule["body_useful_payload_bytes"], np.int64)
    useful_ctrl = np.asarray(schedule["body_useful_control_bytes"], np.int64)
    pad = np.asarray(schedule["body_pad_bytes"], np.int64)
    if len(fsec) > 1 and int(n_ctrl[1]) < 1:
        raise AssertionError(
            "BODY.DAT frame 1 must start with a control sector so the "
            "player can anchor PCM start to its arrival")
    cc = 0
    pc = int(prebuf_patterns) * PAT
    wc = [0, 0]
    seen_pay = np.zeros(len(fsec), np.int64)
    seen_ctrl = np.zeros(len(fsec), np.int64)
    seen_pad = np.zeros(len(fsec), np.int64)
    with Path(body_path).open("rb") as body:
        actual_arm = body.read(len(body_arm))
        if actual_arm != body_arm:
            raise AssertionError("BODY.DAT arm prefix differs from packed input")
        for i in range(1, len(fsec)):
            ncb = int(n_ctrl[i]) * SECTOR
            nwb = int(n_word[i]) * SECTOR
            npb = (int(n_pay[i]) - int(n_word[i])) * SECTOR
            slot_size = int(fsec[i]) * SECTOR
            slot = body.read(slot_size)
            if len(slot) != slot_size:
                raise AssertionError(f"BODY.DAT slot {i} is truncated")

            ctrl_src = stream_ctrl[cc:cc + ncb]
            parity = i & 1
            word_src = stream_word[parity][wc[parity]:wc[parity] + nwb]
            pay_src = stream_pay[pc:pc + npb]
            ctrl_area = slot[:ncb]
            word_area = slot[ncb:ncb + nwb]
            pay_area = slot[ncb + nwb:ncb + nwb + npb]
            rate_area = slot[ncb + nwb + npb:]
            if ctrl_area[:len(ctrl_src)] != ctrl_src or any(ctrl_area[len(ctrl_src):]):
                raise AssertionError(f"BODY.DAT control bytes/pad mismatch at slot {i}")
            if (
                word_area[:len(word_src)] != word_src
                or any(word_area[len(word_src):])
            ):
                raise AssertionError(
                    f"BODY.DAT WordBuf bytes/pad mismatch at slot {i}")
            if pay_area[:len(pay_src)] != pay_src or any(pay_area[len(pay_src):]):
                raise AssertionError(f"BODY.DAT payload bytes/pad mismatch at slot {i}")
            if any(rate_area):
                raise AssertionError(f"BODY.DAT rate-match pad is nonzero at slot {i}")

            seen_ctrl[i] = len(ctrl_src)
            seen_pay[i] = len(word_src) + len(pay_src)
            seen_pad[i] = (
                slot_size - len(ctrl_src) - len(word_src) - len(pay_src))
            cc += ncb
            wc[parity] += nwb
            pc += npb
        if body.read(1):
            raise AssertionError("BODY.DAT has bytes beyond the slot schedule")
    for parity in (0, 1):
        if wc[parity] < len(stream_word[parity]):
            raise AssertionError(
                f"BODY.DAT omitted {len(stream_word[parity]) - wc[parity]} "
                f"WordBuf{parity} refill bytes")
    for name, actual, traced in (
            ("useful control", seen_ctrl, useful_ctrl),
            ("useful payload", seen_pay, useful_pay),
            ("pad", seen_pad, pad)):
        mismatch = np.flatnonzero(actual != traced)
        if mismatch.size:
            i = int(mismatch[0])
            raise AssertionError(
                f"BODY.DAT {name} trace mismatch at slot {i}: "
                f"file={int(actual[i])} trace={int(traced[i])}")
    print(
        f"  BODY.DAT arm/slot照合: arm={len(body_arm) // SECTOR} sectors; "
        f"{len(fsec) - 1} timed slots exact; useful "
        f"control={int(seen_ctrl.sum())}B payload={int(seen_pay.sum())}B "
        f"pad={int(seen_pad.sum())}B")


def _read_audio_samples(audio_path):
    """Read the mono signed-16 WAV/raw source used by the ADPCM encoder."""
    try:
        import wave as _wave
        with _wave.open(str(audio_path), "rb") as wav:
            if wav.getnchannels() != 1:
                raise ValueError(f"audio must be mono, got {wav.getnchannels()} channels")
            width = wav.getsampwidth()
            rate = wav.getframerate()
            raw = wav.readframes(wav.getnframes())
        if rate != AUDIO_RATE:
            raise ValueError(f"audio rate is {rate}, expected {AUDIO_RATE}")
    except (OSError, EOFError):
        raw = Path(audio_path).read_bytes()
        width = 2
    if width != 2:
        raise ValueError(
            f"ADPCM source sample width is {width}, expected 2")
    if len(raw) & 1:
        raise ValueError("s16 ADPCM source has an odd byte count")
    return np.frombuffer(raw, "<i2").copy()


def build_audio_chunks(audio_path, frame_count):
    """Return fixed on-disc chunks and their reconstructed RF5C164 PCM."""
    raw = _read_audio_samples(audio_path)
    target_samples = int(frame_count) * AUDIO_PCM
    source_len = len(raw)
    pcm16 = ima_adpcm.retime_pcm_s16(raw, target_samples)
    if len(pcm16) != source_len:
        print(f"  PCM retime: {source_len} -> {len(pcm16)} samples "
              f"({AUDIO_PCM} samples/frame x {frame_count} frames)")
    control_chunks, pcm_chunks = ima_adpcm.encode_decode_chunks(
        pcm16, AUDIO_PCM)
    if any(len(chunk) != AUDIO_CONTROL for chunk in control_chunks):
        raise AssertionError("IMA control chunk size drift")
    if any(len(chunk) != AUDIO_PCM for chunk in pcm_chunks):
        raise AssertionError("IMA decoded PCM chunk size drift")
    return control_chunks, pcm_chunks


def build_control(
        log, per, n_upd, audio_path, sources=None, update_lists=None,
        prefetch_per=None, dic_indices=None, transfer_orders=None,
        word_capacities=None):
    """Build control blocks and return their reconstructed source PCM chunks."""
    seg_cram = [pals_to_bytes_128(p) for p in log["seg_pals"]]
    audio_chunks, pcm_chunks = build_audio_chunks(audio_path, len(per))
    # CRAM pre-load(PALTAB): パレット本体はplayerイメージ内蔵(paltab.bin)で、実機は
    # boot時にMain-RAM表へコピー済み。切替トリガも内蔵のPALIDX表(frame番号+区間番号)で、
    # controlブロックに切替バイトは存在しない(到着タイミング非依存=スリップ回復に強い)。
    # 区間数は av_config.PALTAB_MAX_SEG が上限(実機表の容量)。
    n_seg = len(seg_cram)
    cap_seg = min(int(av_config.PALTAB_MAX_SEG), 255)
    if n_seg > cap_seg:
        raise SystemExit(
            f"palette segments {n_seg} > PALTAB capacity {cap_seg} "
            f"(av_config.PALTAB_MAX_SEG — raise it and the player equ together)")
    if sources is None:
        sources = tuple(tuple(pattern_supply.SOURCE_PRG for _ in entries)
                        for _cells, entries, _colds in per)
    if prefetch_per is None:
        prefetch_per = tuple(() for _ in per)
    if dic_indices is None:
        dic_indices = tuple(tuple(-1 for _ in entries)
                            for _cells, entries, _colds in per)
    if transfer_orders is None:
        transfer_orders = tuple(None for _ in per)
    if update_lists is None:
        update_lists = np.zeros(len(per), np.bool_)
    update_lists = np.asarray(update_lists, np.bool_)
    if update_lists.shape != (len(per),):
        raise ValueError("shadow update-list flags must match frame count")
    blocks = []
    word_cursors = [0, 0]
    for i in range(len(per)):
        cells, entries, colds = per[i]
        frame_sources = sources[i]
        body = bytearray()
        # 同期マーカー: frame_seq(下位16bit)。実機は control 読み出し時に期待フレーム番号と
        # 照合し、ズレたら desync 検知(CDCセクタ落ち等)して復帰できる。total_len に含む。
        body += struct.pack(">H", i & 0xFFFF)
        use_list = bool(update_lists[i])
        body += struct.pack(">H", shadow_updates.encode_count(n_upd[i], use_list))
        sourced_entries = []
        for e, cold, source in zip(entries, colds, frame_sources):
            sourced_entry = pattern_supply.encode_entry_source(
                e, source if cold else pattern_supply.SOURCE_PRG)
            sourced_entries.append((0x8000 if cold else 0) | sourced_entry)
        if use_list:
            body += shadow_updates.build_update_list(cells, sourced_entries, C_CELLS)
        else:
            body += build_bitmap(cells)
            # TTRC v23 keeps the 16-bit entry array word-aligned even when
            # ceil(cells/8) is odd (for example H40 40x19 = 95 bytes).
            if len(body) & 1:
                body += b"\0"
            for sourced_entry in sourced_entries:
                body += struct.pack(">H", sourced_entry)
        body += audio_chunks[i]
        # Keep the legacy audio offset unchanged.  The suffix is aligned so the
        # 68000 can read its words directly; old players simply ignore it.
        if len(body) & 1:
            body += b"\0"
        runs = sourced_transfer_runs(
            entries, colds, frame_sources, prefetch_per[i], dic_indices[i],
            transfer_orders[i])
        if word_capacities is not None:
            parity = i & 1
            runs, word_cursors[parity] = pattern_supply.split_word_ring_runs(
                runs,
                capacity=int(word_capacities[parity]),
                cursor=word_cursors[parity],
            )
        body += struct.pack(">H", len(runs))
        for slot, count, source, dic_index in runs:
            body += struct.pack(
                ">HH", *pattern_supply.encode_run_descriptor(
                    slot, count, source, dic_index))
        # total_len は「先頭2Bを含むブロック全長」。実機は apply_cur を total_len で進めるので
        # パディング込みの偶数にする(奇数だと1B/フレームずつ desync する)。
        total = len(body) + 2
        if total & 1:
            body += b"\0"
            total += 1
        blocks.append(struct.pack(">H", total) + bytes(body))
    return blocks, pcm_chunks


def control_audio_bounds(block):
    """Return the fixed-size on-disc audio slice in one control block."""
    n_upd, use_list = shadow_updates.decode_count(
        struct.unpack_from(">H", block, 4)[0])
    update_bytes = (
        n_upd * shadow_updates.LIST_ITEM_BYTES if use_list
        else shadow_updates.aligned_bitmap_bytes(C_CELLS)
        + n_upd * shadow_updates.SHADOW_ENTRY_BYTES)
    pos = 6 + update_bytes
    return pos, pos + AUDIO_CONTROL


def control_audio(block):
    """Return the fixed-size encoded/PCM chunk embedded in one control block."""
    start, end = control_audio_bounds(block)
    chunk = block[start:end]
    if len(chunk) != AUDIO_CONTROL:
        raise ValueError(
            f"control audio truncated: got {len(chunk)}, expected {AUDIO_CONTROL}")
    return chunk


def replace_control_audio(block, chunk):
    """Replace one on-disc audio chunk without changing the block length."""
    if len(chunk) != AUDIO_CONTROL:
        raise ValueError(
            f"replacement audio is {len(chunk)} bytes, expected {AUDIO_CONTROL}")
    start, end = control_audio_bounds(block)
    out = bytearray(block)
    if len(out[start:end]) != AUDIO_CONTROL:
        raise ValueError("control audio replacement points outside the block")
    out[start:end] = chunk
    if len(out) != len(block):
        raise AssertionError("audio replacement changed the control block length")
    return bytes(out)


def rate_deltas(nfr):
    """Return the CD-1x sector allowance for BODY frames 1..N-1.

    Frame 0 lives in HEADER.DAT, so its allowance is zero.  The accumulator is
    intentionally identical to the player and to the BODY writer. Qualified
    content uses the exact allowance of each VBlank interval, including the
    24fps 2/3 pattern. Unqualified rates retain 75/nominal-fps pacing.
    """
    try:
        return stream_schedule.rate_deltas(nfr, FPS)
    except stream_schedule.ScheduleError as exc:
        raise SystemExit(f"pack: {exc}") from exc


def rate_match_fsec(n_pay_sec, n_ctrl_sec):
    """Apply the player's bounded CD-rate accumulator to a routing table."""
    try:
        return stream_schedule.rate_match_sectors(
            n_pay_sec, n_ctrl_sec, fps=FPS)
    except stream_schedule.ScheduleError as exc:
        raise SystemExit(f"pack: {exc}") from exc


def schedule(per, n_load, blocks, *, control_sector_envelope=None):
    """Materialize the already-funded control and payload sector route."""
    blk_len = np.array([len(b) for b in blocks], np.int64)
    if len(per) != len(n_load) or len(per) != len(blocks):
        raise SystemExit("pack: schedule inputs have different frame counts")
    try:
        return stream_schedule.schedule_payload_ring(
            n_load,
            blk_len,
            fps=FPS,
            ring_capacity_patterns=RING_DELIVERY_CAP_PAT,
            prebuffer_capacity_patterns=RING_CAP_PAT,
            frame_sectors=FRAME_SECTORS,
            fill=PACK_FILL,
            control_sector_envelope=control_sector_envelope,
        )
    except (ValueError, stream_schedule.ScheduleError) as exc:
        raise SystemExit(f"pack: {exc}") from exc


def decode_verify(
        log, per, blocks, supply_plan, sc, compare_dir=None, sample_dir=None,
        boot_sidecar=()):
    """Simulate the current control-first player and compare it with sim output.

    The current slot's BODY payload may arrive while Main still displays the
    previous frame, before this frame consumes its already-armed cold patterns.
    Model that live order so the physical PrgBuf peak includes the overlap.
    """
    frame_seg = np.asarray(log["frame_seg"], np.int64)
    seg_pals = log["seg_pals"]
    n_pay_sec = sc["n_pay_sec"]; blk_len = sc["blk_len"]; B = sc["prebuf_pat"]
    word_stage_sec = np.asarray(
        sc.get("word_stage_sectors", np.zeros(len(per), np.int64)),
        np.int64,
    )
    ctrl = b"".join(blocks)
    POOL = int(log["vram_tiles"])
    cmp = Path(compare_dir) if compare_dir else None
    if sample_dir:
        sample_dir = Path(sample_dir); sample_dir.mkdir(parents=True, exist_ok=True)
    samples = set(range(0, len(per), max(1, len(per) // 6)))
    # v2 frame0ヘッダ: frame0のパターンはストリーミングのリングではなくヘッダのF0PATブロック
    # から供給される(実機の boot ロード)。よって decode_verify も frame0 は別deque(f0_ring)から
    # popし、リングは prebuffer(Plist[nl0:nl0+B])で種蒔く。ストリーム payload カーソルは nl0+B から。
    # (これを分けないと frame0 のパターンをリングから食い、末尾で nl0 個ぶん枯渇して見える。)
    f0h = bool(sc.get("f0_header", False))
    nl0 = int(sc.get("f0_cold", 0)) if f0h else 0
    sidecar_count = sum(bool(item[1]) for item in boot_sidecar)
    f0_inline = nl0 - sidecar_count
    if f0_inline < 0:
        raise ValueError("boot sidecar exceeds frame-0 pattern payload")
    prg_patterns = supply_plan.prg_patterns
    f0_ring = deque(prg_patterns[:f0_inline])
    ring = deque(prg_patterns[nl0:nl0 + B]); pc = nl0 + B; cc = 0
    word = [deque(supply_plan.wr0_patterns), deque(supply_plan.wr1_patterns)]
    word_refill = [
        supply_plan.wr0_refill_patterns,
        supply_plan.wr1_refill_patterns,
    ]
    word_refill_cursor = [0, 0]
    dic = tuple(supply_plan.dic_patterns)
    tile = [None] * (POOL + BASE + 2)
    sidecar_patterns = prg_patterns[f0_inline:nl0]
    if len(sidecar_patterns) != sidecar_count:
        raise ValueError("boot sidecar pattern stream is truncated")
    for item, pattern in zip(boot_sidecar, sidecar_patterns):
        slot = int(item[0])
        if not 0 <= slot < POOL:
            raise ValueError(f"boot sidecar slot {slot} is outside the pool")
        tile[slot + BASE] = pattern
    nt_slot = np.zeros(C_CELLS, np.int64); nt_pal = np.zeros(C_CELLS, np.int64)
    diffs = []; ring_peak = len(ring); bad = 0
    for i in range(len(per)):
        parity = i & 1
        stage = int(word_stage_sec[i]) * PAT_PER_SEC
        if stage:
            start = word_refill_cursor[parity]
            stop = start + stage
            staged = word_refill[parity][start:stop]
            if len(staged) != stage:
                raise ValueError(
                    f"frame {i}: WordBuf{parity} refill stream is truncated")
            word[parity].extend(staged)
            word_refill_cursor[parity] = stop
        add = (
            int(n_pay_sec[i]) - int(word_stage_sec[i])
        ) * PAT_PER_SEC
        prg_src = f0_ring if (f0h and i == 0) else ring
        # The live player may pump this BODY payload while Main still displays
        # frame i-1. Append before consuming frame i so the verifier measures
        # the same safety-critical PrgBuf peak as hardware.
        for k in range(pc, min(pc + add, len(prg_patterns))):
            ring.append(prg_patterns[k])
        pc += add
        ring_peak = max(ring_peak, len(ring))
        blk = ctrl[cc:cc + int(blk_len[i])]; cc += int(blk_len[i])
        p = 2                                         # skip total_len
        p += 2                                        # skip frame_seq(同期マーカー)
        nupd, use_list = shadow_updates.decode_count(
            struct.unpack(">H", blk[p:p + 2])[0]); p += 2
        if use_list:
            update_items = []
            for _ in range(nupd):
                offset, ent = struct.unpack_from(">HH", blk, p); p += 4
                if offset & 1 or offset >= C_CELLS * 2:
                    raise ValueError(f"invalid shadow offset {offset} in frame {i}")
                update_items.append((offset // 2, ent))
        else:
            bmbytes = (C_CELLS + 7) // 8
            bm = blk[p:p + bmbytes]; p += bmbytes
            if p & 1:
                if blk[p] != 0:
                    raise ValueError(f"nonzero bitmap alignment pad in frame {i}")
                p += 1
            cells = [c for c in range(C_CELLS) if bm[c >> 3] & (1 << (c & 7))]
            update_items = []
            for c in cells:
                e = struct.unpack_from(">H", blk, p)[0]; p += 2
                update_items.append((c, e & pattern_supply.NAME_ENTRY_MASK))

        # The source-aware run suffix is authoritative for physical pattern
        # delivery in both update formats. The list intentionally contains only
        # completed name-table values and therefore carries no cold/source bits.
        runs_pos = p + AUDIO_CONTROL
        if runs_pos & 1:
            runs_pos += 1
        packed_run_count = struct.unpack_from(">H", blk, runs_pos)[0]
        runs_pos += 2
        for _ in range(packed_run_count):
            word0, word1 = struct.unpack_from(">HH", blk, runs_pos)
            runs_pos += 4
            slot, count, source, dic_index = (
                pattern_supply.decode_run_descriptor(word0, word1))
            if source == pattern_supply.SOURCE_PRG:
                src = prg_src
            elif source == pattern_supply.SOURCE_WR:
                src = word[parity]
            elif source == pattern_supply.SOURCE_DIC:
                src = dic[dic_index:dic_index + count]
            else:
                src = ()
            for offset in range(count):
                if not src or slot + offset >= POOL:
                    bad += 1
                elif source == pattern_supply.SOURCE_DIC:
                    tile[slot + offset + BASE] = src[offset]
                else:
                    tile[slot + offset + BASE] = src.popleft()
        if runs_pos != len(blk):
            raise ValueError(
                f"frame {i}: run suffix ends at {runs_pos}, "
                f"control length is {len(blk)}")
        for c, ent in update_items:
            nt_pal[c] = (ent >> 13) & 3
            nt_slot[c] = (ent & 0x07FF) - BASE
        need_img = (cmp is not None) or (sample_dir is not None and i in samples)
        if not need_img:
            continue
        full16 = np.zeros((4, 16, 3), np.uint8)
        full16[:, 1:] = np.asarray(seg_pals[int(frame_seg[i])], np.uint8)
        img = np.zeros((C_CELLS, TILE, TILE, 3), np.uint8)
        for c in range(C_CELLS):
            pat = tile[int(nt_slot[c]) + BASE]
            if pat is None:
                continue
            a = np.frombuffer(pat, np.uint8); idx = np.zeros(64, np.uint8)
            idx[0::2] = a >> 4; idx[1::2] = a & 0xF
            img[c] = rgb333_to_rgb888(full16[nt_pal[c], idx].reshape(8, 8, 3))
        fr = img.reshape(TROWS, TCOLS, TILE, TILE, 3).transpose(0, 2, 1, 3, 4).reshape(
            TROWS * TILE, TCOLS * TILE, 3)
        if sample_dir is not None and i in samples:
            Image.fromarray(fr, "RGB").save(sample_dir / f"decoded_{i:05d}.png")
        if cmp is not None:
            ref_p = cmp / f"{i:05d}.png"
            if ref_p.exists():
                ref = np.asarray(Image.open(ref_p).convert("RGB"))[:TROWS * TILE, :TCOLS * TILE]
                diffs.append((i, int(np.abs(fr.astype(np.int32) - ref.astype(np.int32)).max())))
        if (i + 1) % 400 == 0:
            print(f"  decode {i+1}/{len(per)}", flush=True)
    if any(
            word_refill_cursor[parity] != len(word_refill[parity])
            for parity in (0, 1)):
        raise ValueError("WordBuf refill stream was not fully staged")
    cache_left = len(word[0]) + len(word[1])
    if cache_left:
        bad += cache_left
    print(f"decode: ring_peak {ring_peak*PAT/1024:.0f}KB "
          f"preload_left {cache_left} 未配信pop(表示破壊) {bad}")
    if diffs:
        da = np.array([x[1] for x in diffs])
        nd = int((da > 0).sum())
        print(f"sim preview一致: 比較{len(da)}枚 差分ありフレーム={nd} 画素最大差={int(da.max())}")
        if nd:
            print("  差分フレーム(先頭10):", [x[0] for x in diffs if x[1] > 0][:10])


def _decode_control_chunk(chunk):
    decoded, _state = ima_adpcm.decode_chunk(chunk, AUDIO_PCM)
    return ima_adpcm.pcm16_to_sign_magnitude(decoded)


def write_stream(
        path, log, per, blocks, source_pcm_chunks, supply_plan,
        wordram_layout, sc, POOL,
        boot_sidecar=(), sp_extension_bytes=b""):
    """Write the v23 split stream and a combined tooling container.

    HEADER.DAT:
      Header(1sec) | BOOT_STAGE | [Dic] | [ADPCM_TABLE] | [WR0] | [WR1]
                   | ROUTING(0..N-1,[0]=0,0) | PREBUF1(frame1用RING_CAP)
    BODY.DAT:
      ARM_AUDIO | ARM_FRAME0(control+patterns)
                | FRAMES(1..N-1), each [control sectors][payload sectors][rate pad]
    MOVIE.DAT (``path``) is the off-disc HEADER.DAT || BODY.DAT container.

    BODY arm is read before the playback clock. Frame 0 never enters the timed
    Prg ring; frame 1 therefore still begins from the HEADER prebuffer.
    BOOT_STAGE = 任意の裏VRAMパターン(BVRM sidecar)。Mainはboot時にVRAMの
    指定slotへコピーする。パレット表と切替表はplayerイメージ内蔵
    (paltab.bin / palidx.bin)でディスクには載らない。"""
    n_pay_sec = sc["n_pay_sec"]; n_ctrl_sec = sc["n_ctrl_sec"]
    word_stage_sec = np.asarray(
        sc.get("word_stage_sectors", np.zeros(len(per), np.int64)),
        np.int64,
    )
    Bpat = int(sc["prebuf_pat"])
    frame_seg = np.asarray(log["frame_seg"], np.int64)
    if int(frame_seg[0]) != 0:
        raise SystemExit(
            "pack: frame 0 must display palette segment 0 "
            "(the player's initial CRAM is paltab.bin entry 0)")
    nfr = len(per)
    if nfr > ROUTING_MAX_FRAMES:
        raise SystemExit(
            f"pack: {nfr} frames exceed the player's {ROUTING_MAX_FRAMES}-frame "
            "routing table; split or shorten the source")
    f0_header = bool(sc.get("f0_header", False))
    nl0 = int(sc.get("f0_cold", 0))
    sidecar_count = sum(bool(item[1]) for item in boot_sidecar)
    f0_inline = nl0 - sidecar_count
    if f0_inline < 0:
        raise SystemExit("pack: boot sidecar exceeds frame-0 pattern payload")
    f0_ctrl_len = int(sc.get("f0_ctrl_len", 0))
    payload = b"".join(supply_plan.prg_patterns)
    wr0_blob = b"".join(supply_plan.wr0_patterns)
    wr1_blob = b"".join(supply_plan.wr1_patterns)
    word_refill = (
        b"".join(supply_plan.wr0_refill_patterns),
        b"".join(supply_plan.wr1_refill_patterns),
    )
    dic_blob = b"".join(supply_plan.dic_patterns)
    wr0_sec = -(-len(wr0_blob) // SECTOR)
    wr1_sec = -(-len(wr1_blob) // SECTOR)
    dic_sec = -(-len(dic_blob) // SECTOR)

    # Queue the first N reconstructed PCM chunks from the BODY arm, then make each
    # live control carry the next future PCM or checkpointed ADPCM chunk.
    # The old duplicate-and-skip layout consumed the
    # entire startup reserve by frame N and left the writer next to the play
    # head. Shifting fixed-size chunks keeps block lengths and sector scheduling
    # unchanged while preserving the exact source sample order.
    safe_audio_prefetch = max(0, min(
        (PCM_SYNC_MAX - PCM_SYNC_LEAD) // max(1, AUDIO_PCM),
        (PCM_WAVE_RING_END - PCM_SYNC_LEAD - PCM_STARTUP_MARGIN)
        // max(1, AUDIO_PCM)))
    audio_prefetch_frames = (
        min(nfr, STARTUP_AUDIO_FRAMES, safe_audio_prefetch) if f0_header else 0)
    source_audio_chunks = [control_audio(block) for block in blocks]
    silence_chunk, _state = ima_adpcm.encode_chunk(
        np.zeros(AUDIO_PCM, dtype=np.int16), ima_adpcm.State())
    disc_blocks = [
        replace_control_audio(
            block,
            source_audio_chunks[i + audio_prefetch_frames]
            if i + audio_prefetch_frames < nfr else silence_chunk)
        for i, block in enumerate(blocks)
    ]
    queued_pcm = (
        list(source_pcm_chunks[:audio_prefetch_frames])
        + [_decode_control_chunk(control_audio(block)) for block in disc_blocks]
    )
    if queued_pcm[:nfr] != list(source_pcm_chunks):
        raise AssertionError(
            "BODY-arm audio prefetch changed reconstructed sample order")
    silence_pcm = b"\0" * AUDIO_PCM
    if any(chunk != silence_pcm for chunk in queued_pcm[nfr:]):
        raise AssertionError("BODY-arm audio prefetch tail is not silent")
    if [len(block) for block in disc_blocks] != [len(block) for block in blocks]:
        raise AssertionError("startup PCM prefetch changed control block lengths")
    print(f"  audio prefetch: {audio_prefetch_frames} chunks queued; "
          f"source order verified for {nfr} playback chunks")

    control = b"".join(disc_blocks)
    # Split frame 0 from the timed stream. It remains an untimed exact
    # construction, but v23 carries its bytes in the BODY arm rather than HEADER.
    if f0_header:
        f0_ctrl = control[:f0_ctrl_len]
        f0_pat = payload[:f0_inline * PAT]
        stream_ctrl = control[f0_ctrl_len:]          # frames1+ の control連結
        stream_pay = payload[nl0 * PAT:]             # frames1+ の payload連結
        f0_ctrl_sec = -(-len(f0_ctrl) // SECTOR)
        f0_pat_sec = -(-len(f0_pat) // SECTOR)
        if f0_pat_sec * SECTOR > av_config.FRAME0_PATTERN_STAGING_KB * 1024:
            raise SystemExit(
                f"pack: frame0 needs {f0_pat_sec} pattern sectors, beyond the "
                f"{av_config.FRAME0_PATTERN_STAGING_KB}KB boot staging area")
    else:
        f0_ctrl = f0_pat = b""
        stream_ctrl = control
        stream_pay = payload
        f0_ctrl_sec = f0_pat_sec = 0
    if len(n_pay_sec) != nfr or len(n_ctrl_sec) != nfr:
        raise AssertionError(
            f"routing array length mismatch: frames={nfr}, "
            f"pay={len(n_pay_sec)}, ctrl={len(n_ctrl_sec)}")
    routing = bytearray()
    for frame, (n_pay, n_ctrl, n_word) in enumerate(zip(
            n_pay_sec, n_ctrl_sec, word_stage_sec, strict=True)):
        try:
            routing.append(
                ttrc_routing.encode_route(n_pay, n_ctrl, n_word))
        except ValueError as exc:
            raise SystemExit(f"pack: invalid routing at frame {frame}: {exc}") from exc
    routing_sec = ttrc_routing.routing_sector_count(nfr)
    routing_blob = bytes(routing).ljust(routing_sec * SECTOR, b"\0")
    try:
        ttrc_routing.validate_route_table(routing_blob, nfr, routing_sec)
    except ValueError as exc:
        raise AssertionError(f"packer produced an invalid routing table: {exc}") from exc
    prebuf_bytes = stream_pay[:Bpat * PAT]           # frame1用プリバッファ(RING_CAP)
    prebuf_sec = -(-len(prebuf_bytes) // SECTOR)
    ring_peak = int(sc["ring_peak"])
    # The sim decision log is the source of truth. Never let a changed shell
    # environment silently turn an H32 stream into H40.
    mode_name = display_mode_name(log)
    _mode = {"H32": 0, "H40": 1, "MODE4": 2}[mode_name]
    # The first boot handoff stages one 24 KiB image at the bank front holding
    # only the optional boot-VRAM sidecar records. Main copies this image
    # before Sub reuses the front for frame output and the parity-specific
    # WordBuf. Palette data does not ride the disc: the full segment table and
    # the switch table are player-image build inputs (paltab.bin/palidx.bin).
    palette_table = b"".join(
        pals_to_bytes_128(p) for p in log["seg_pals"])
    # PALIDX: player-embedded palette-switch table. frame_seg is forward-only,
    # so each (frame.u16, segment.u16) entry advances to a strictly later
    # frame. The player advances while next_switch <= frame_no; the 0xFFFF
    # frame sentinel terminates the table.
    switches = [
        (i, int(frame_seg[i]))
        for i in range(1, nfr)
        if frame_seg[i] != frame_seg[i - 1]
    ]
    if len(switches) > av_config.PALIDX_ENTRIES - 1:
        raise SystemExit(
            f"pack: {len(switches)} palette switches exceed the "
            f"{av_config.PALIDX_ENTRIES - 1}-entry PALIDX capacity")
    if len(switches) != len(log["seg_pals"]) - 1 or any(
            seg != index + 1 for index, (_frame, seg) in enumerate(switches)):
        raise SystemExit(
            "pack: frame_seg is not a forward-only segment progression")
    palidx = bytearray()
    for frame, seg in switches:
        palidx += struct.pack(">HH", frame, seg)
    while len(palidx) < av_config.PALIDX_BYTES:
        palidx += struct.pack(">HH", av_config.PALIDX_FRAME_SENTINEL, 0)
    sidecar_patterns = supply_plan.prg_patterns[f0_inline:nl0]
    if len(sidecar_patterns) != sidecar_count:
        raise SystemExit("pack: boot sidecar pattern stream is truncated")
    stage_bytes = av_config.PALTAB_STAGE_KB * 1024
    stage = bytearray(stage_bytes)
    region_offsets = (
        0x0000,
        0x1000,
        0x5000,
    )
    region_capacities = (
        av_config.BOOT_VRAM_REGION_A_BYTES
        // av_config.BOOT_VRAM_SIDECAR_ENTRY_BYTES,
        av_config.BOOT_VRAM_REGION_B_BYTES
        // av_config.BOOT_VRAM_SIDECAR_ENTRY_BYTES,
        av_config.BOOT_VRAM_REGION_C_BYTES
        // av_config.BOOT_VRAM_SIDECAR_ENTRY_BYTES,
    )
    if sum(region_capacities) < sidecar_count:
        raise SystemExit(
            f"pack: boot sidecar needs {sidecar_count} records, preserved "
            f"Word-RAM regions hold {sum(region_capacities)}")
    region_counts = []
    source_index = 0
    for offset, capacity in zip(region_offsets, region_capacities):
        count = min(capacity, sidecar_count - source_index)
        region_counts.append(count)
        cursor = offset
        for item, pattern in zip(
                boot_sidecar[source_index:source_index + count],
                sidecar_patterns[source_index:source_index + count]):
            slot = int(item[0])
            if not 0 <= slot < POOL:
                raise SystemExit(
                    f"pack: boot sidecar slot {slot} is outside pool {POOL}")
            record = struct.pack(">H", slot) + pattern
            stage[cursor:cursor + len(record)] = record
            cursor += len(record)
        source_index += count
    if source_index != sidecar_count:
        raise AssertionError("boot sidecar region split lost records")
    if sidecar_count:
        struct.pack_into(
            ">4sHHH", stage, 0x0FC0, b"BVRM", *region_counts)
    paltab_sec = len(stage) // SECTOR
    # One reconstructed PCM chunk per sector lets the Sub write each chunk without
    # cross-sector staging. Offset 58 carries the RF5C164 frequency delta; offset
    # 60 tells the player how many BODY-arm sectors to queue before PCM starts.
    audio_preload = b"".join(
        source_pcm_chunks[i].ljust(SECTOR, b"\0")
        for i in range(audio_prefetch_frames)
    )
    audio_preload_sec = audio_prefetch_frames
    # v4: 可変フレーム(5セクタ固定paddingを廃止=各frameは n_pay+n_ctrl セクタ)＋ vsync/コマ N。
    # CDレート累積器が実際のfpsを決める。Nは整数VBlank cadenceのヒントで、24fpsのN2を
    # 29.97fpsへ丸める指定ではない。AUDIOも実効fps由来。FRAME_SECTORS(=5)は最大スロット。
    vsync_n = VSYNC_N                                  # N: 近似VBLANK間隔(30/24→2, 15→4)
    fps_int = int(round(FPS))                         # 名目fps。FEATURE_FIXED_N時はvsync_n由来のCD rate
    audio_fd = av_config.rf5c164_fd(AUDIO_PCM, PLAYBACK_FPS)
    if not f0_header:
        raise SystemExit("pack v23 requires an untimed frame0 BODY arm")
    features = FEATURE_COLD_RUNS | FEATURE_DICBUF_INDEXED_RUNS
    if av_config.uses_fixed_n_cadence(FPS):
        features |= FEATURE_FIXED_N
    if supply_plan.enabled:
        features |= FEATURE_PATTERN_SUPPLY
    if any(struct.unpack_from(">H", block, 4)[0] & shadow_updates.LIST_TAG
           for block in blocks):
        features |= FEATURE_SHADOW_UPDATE_LISTS
    if bool((log.get("raw_prefetch") or {}).get("enabled", False)):
        features |= FEATURE_VRAM_RAW_PREFETCH
    if sidecar_count:
        features |= FEATURE_BOOT_VRAM_SIDECAR
    if any(word_stage_sec):
        features |= FEATURE_WORDBUF_RING
    header = struct.pack(">4sHHHHHHHHH", MAGIC, VERSION, nfr, TCOLS, TROWS, C_CELLS,
                         POOL, BASE, FRAME_SECTORS, len(log["seg_pals"]))
    header += struct.pack(">LLLL", Bpat, routing_sec, prebuf_sec, ring_peak)
    header += bytes([_mode])                          # offset 38: display mode
    header += b"\0"                                   # offset 39: pad
    header += struct.pack(">LL", f0_ctrl_sec, f0_pat_sec)  # offset 40,44: frame0ブロック
    header += struct.pack(">L", paltab_sec)          # offset 48: boot-stage sectors(v13)
    # Offset 54 is the decoded RF5C164 sample count. TTRC v23 always derives
    # the control size as checkpoint(4) + AUDIO_PCM/2.
    header += struct.pack(">HH", vsync_n, AUDIO_PCM)
    header += struct.pack(">H", fps_int)             # offset 56: 名目fps(レートマッチpadding用) (v4)
    header += struct.pack(">HH", audio_fd, audio_preload_sec)  # offset 58: RF5C164 FD; 60: prefetch sectors
    header += struct.pack(">H", features)          # offset 62: optional stream features
    # v23: offset 64..191 is pad. The initial CRAM image is paltab.bin entry 0
    # inside the player image, not a header field.
    header += b"\0" * (SECTOR - len(header))
    header = bytearray(header)
    if supply_plan.enabled:
        player_constants.PATTERN_SUPPLY_STRUCT.pack_into(
            header, player_constants.PATTERN_SUPPLY_OFFSET,
            player_constants.PATTERN_SUPPLY_MAGIC,
            player_constants.PATTERN_SUPPLY_VERSION, 0,
            len(supply_plan.wr0_patterns),
            len(supply_plan.wr1_patterns),
            len(supply_plan.dic_patterns),
            wr0_sec, wr1_sec, dic_sec,
            int(log["max_cold"]),
            wordram_layout.wr0_load_bytes,
            wordram_layout.wr1_load_bytes,
        )
    header = player_constants.stamp_header_sector(header)
    frame0_blk = (f0_ctrl.ljust(f0_ctrl_sec * SECTOR, b"\0")
                  + f0_pat.ljust(f0_pat_sec * SECTOR, b"\0"))
    adpcm_table_blob = sp_extension.adpcm_preload_image(
        ima_adpcm.full_tables(), sp_extension_bytes, SECTOR)
    if len(adpcm_table_blob) != ADPCM_TABLE_SECTORS * SECTOR:
        raise AssertionError("ADPCM table/extension preload size changed")
    header_blob = (header
                   + stage.ljust(paltab_sec * SECTOR, b"\0")
                   + dic_blob.ljust(dic_sec * SECTOR, b"\0")
                   + adpcm_table_blob
                   + wr0_blob.ljust(wr0_sec * SECTOR, b"\0")
                   + wr1_blob.ljust(wr1_sec * SECTOR, b"\0")
                   + routing_blob
                   + prebuf_bytes.ljust(prebuf_sec * SECTOR, b"\0"))
    if len(header_blob) % SECTOR:
        raise AssertionError(f"HEADER.DAT is not sector aligned: {len(header_blob)} bytes")

    out_path = Path(path)
    if out_path.name.upper() in {"HEADER.DAT", "BODY.DAT"}:
        raise SystemExit(
            "--output names the combined tooling container; "
            "use a name other than HEADER.DAT/BODY.DAT")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header_path = out_path.with_name("HEADER.DAT")
    body_path = out_path.with_name("BODY.DAT")
    # The Main-IP binary embeds the full segment-palette table and the switch
    # table.  Keep both build inputs beside the split stream and derive them
    # from the same canonical decision log, so a stale table cannot disagree
    # with the packed BODY's segment progression.
    paltab_path = out_path.with_name("paltab.bin")
    paltab_path.write_bytes(palette_table)
    palidx_path = out_path.with_name("palidx.bin")
    palidx_path.write_bytes(bytes(palidx))
    with header_path.open("wb") as f:
        f.write(header_blob)
    constants_path = out_path.with_name("player_constants.inc")
    player_constants.generate_include(header_path, constants_path)

    body_arm = audio_preload + frame0_blk
    arm_sectors = len(body_arm) // SECTOR
    if len(body_arm) % SECTOR:
        raise AssertionError("BODY.DAT arm is not sector aligned")
    pc = Bpat * PAT; cc = 0
    wc = [0, 0]
    fsec_schedule = sc["fsec"]
    with body_path.open("wb") as f:
        f.write(body_arm)
        # Rate-match every frame to its exact CD-1x cadence allowance. The
        # player retains the same bounded lead accumulator, but construction
        # requires rate_lead_peak=0: a heavy slot's elapsed display delay
        # cannot be undone by omitting pad in a later light slot. schedule()
        # has already filled only same-slot spare allowance with useful
        # payload, so write the proven control/payload/pad route directly.
        fsec_list = []
        for i in range(nfr):
            if f0_header and i == 0:
                continue                              # frame0 は FRAMES に出さない(ヘッダ側)
            fsec = int(fsec_schedule[i])
            fsec_list.append(fsec)
            nwb = int(word_stage_sec[i]) * SECTOR
            npb = (
                int(n_pay_sec[i]) - int(word_stage_sec[i])
            ) * SECTOR
            ncb = int(n_ctrl_sec[i]) * SECTOR
            # v6+ physical order: complete the current control first, then
            # stage the parity WordBuf prefix, then carry ordinary Prg payload.
            fr = stream_ctrl[cc:cc + ncb].ljust(ncb, b"\0"); cc += ncb
            parity = i & 1
            fr += word_refill[parity][
                wc[parity]:wc[parity] + nwb
            ].ljust(nwb, b"\0")
            wc[parity] += nwb
            fr += stream_pay[pc:pc + npb].ljust(npb, b"\0"); pc += npb
            fr = fr.ljust(fsec * SECTOR, b"\0")       # レートマッチpad(超過ぶんは捨てセクタ)
            f.write(fr)
    if cc < len(stream_ctrl):
        raise AssertionError(f"BODY.DAT omitted {len(stream_ctrl) - cc} control bytes")
    if pc < len(stream_pay):
        raise AssertionError(f"BODY.DAT omitted {len(stream_pay) - pc} payload bytes")
    for parity in (0, 1):
        if wc[parity] < len(word_refill[parity]):
            raise AssertionError(
                f"BODY.DAT omitted {len(word_refill[parity]) - wc[parity]} "
                f"WordBuf{parity} refill bytes")
    frames_stream_sec = int(sum(fsec_list))
    if body_path.stat().st_size != (arm_sectors + frames_stream_sec) * SECTOR:
        raise AssertionError("BODY.DAT size disagrees with frame sector schedule")
    verify_body_delivery_file(
        body_path,
        body_arm,
        stream_ctrl,
        stream_pay,
        sc,
        stream_word=word_refill,
        prebuf_patterns=Bpat,
    )

    # Preserve MOVIE.DAT for offline tools.  Derive it from the two physical
    # disc files so there cannot be a third, subtly different representation.
    with out_path.open("wb") as dst, header_path.open("rb") as src:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)
    with out_path.open("ab") as dst, body_path.open("rb") as src:
        while chunk := src.read(1024 * 1024):
            dst.write(chunk)

    header_sec = len(header_blob) // SECTOR
    total = header_sec + arm_sectors + frames_stream_sec
    if out_path.stat().st_size != total * SECTOR:
        raise AssertionError("combined MOVIE.DAT size disagrees with HEADER.DAT + BODY.DAT")
    print(f"wrote {header_path} {header_sec}sec + {body_path} "
          f"{arm_sectors}+{frames_stream_sec}sec; "
          f"combined {out_path} {total}sec (mode {mode_name} stage {paltab_sec} "
          f"BODY arm audio {audio_prefetch_frames}f "
          f"preload Wr0/Wr1/Dic={len(supply_plan.wr0_patterns)}/"
          f"{len(supply_plan.wr1_patterns)}/{len(supply_plan.dic_patterns)} "
          f"frame0 {f0_ctrl_sec}+{f0_pat_sec} backside={sidecar_count} "
          f"routing {routing_sec} prebuf {prebuf_sec} frames {frames_stream_sec}) "
          f"ring_peak {ring_peak*PAT/1024:.0f}KB  v{VERSION} N={vsync_n}"
          f"(={PLAYBACK_FPS:.3f}fps) AUDIO=adpcm22 "
          f"control={AUDIO_CONTROL}B pcm={AUDIO_PCM}B FD=0x{audio_fd:04X}")
    print(f"  player palette tables: {paltab_path} ({len(palette_table)}B, "
          f"{len(log['seg_pals'])} segments) + {palidx_path} "
          f"({len(palidx)}B, {len(switches)} switches)")
    print(f"  player constants: {constants_path}")
    print(f"  実機定数: NUM_FRAMES={nfr} FRAME_SECTORS={FRAME_SECTORS}(最大スロット) PALTAB_SEC={paltab_sec} "
          f"F0_CTRL_SEC={f0_ctrl_sec} F0_PAT_SEC={f0_pat_sec} ROUTING_SEC={routing_sec} "
          f"PREBUF_SEC={prebuf_sec} PREBUF_PAT={Bpat} RING_PEAK_PAT={ring_peak} VSYNC_N={vsync_n}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", help="per-source TOML profile (used to locate and authenticate decisions.pkl)")
    ap.add_argument("--dec-log", default="")
    ap.add_argument("--pool-slots", type=int, default=0)
    ap.add_argument("--alloc", choices=["lru", "contig"], default="contig",
                    help="スロット割当: contig=フレーム内cold連番(MD大DMA向け, 既定) / lru=旧方式")
    ap.add_argument("--output", default="")
    ap.add_argument("--audio", default="")
    ap.add_argument(
        "--sp-extension", required=True, type=Path,
        help="linked Sub extension embedded in ADPCM preload padding")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--compare", default="")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()
    sp_extension_bytes = args.sp_extension.read_bytes()
    extension_values = sp_extension.metadata(sp_extension_bytes)
    print(
        f"  Sub extension preload: {extension_values.size}B "
        f"crc32=0x{extension_values.crc32:08X}")

    profile = None
    if args.config:
        try:
            profile = load_profile(args.config)
        except (OSError, ValueError) as exc:
            raise SystemExit(f"invalid encode profile: {exc}") from exc
    dec_log = Path(args.dec_log) if args.dec_log else (
        profile.decision_log if profile else sim_work_dir() / "decisions.pkl")
    log = load_log(dec_log)
    if profile is not None:
        recorded = ((log.get("config") or {}).get("profile") or {})
        if not recorded:
            raise SystemExit(
                f"{dec_log}: decision log predates TOML profile authentication; re-run sim")
        if recorded.get("sha256") != profile.sha256:
            raise SystemExit(
                f"{dec_log}: profile hash mismatch; the TOML changed after sim. "
                "Re-run sim before packing.")
    configure_from_log(log)
    require_canonical_p0_debug_colours(log)
    # The frozen PrgBuf capacity and the packer's physical schedule cap must be
    # identical. A mismatch means the stream was simulated against another
    # memory map.
    sim_prg_buf = log.get("prg_buf_kb", log.get("tank_kb"))
    sim_cold = log.get("max_cold")
    print(f"  encode params from sim: max_cold={sim_cold} "
          f"PrgBuf={sim_prg_buf}KB + jitter={RING_JITTER_HEADROOM_KB}KB  "
          f"delivery limit={RING_DELIVERY_CAP_KB}KB "
          f"(physical ring {RING_SIZE_KB}KB)  "
          f"{TCOLS*8}x{TROWS*8} {FPS:g}fps AUDIO=adpcm22 "
          f"control={AUDIO_CONTROL}B pcm={AUDIO_PCM}B")
    # A configured build is always namespaced by the TOML filename.
    output = args.output or str(
        profile.pack_output if profile is not None else "out/movieplay/MOVIE.DAT")
    audio_path = args.audio
    if not audio_path:
        audio_name = ((log.get("config") or {}).get("audio") or {}).get("file")
        if not audio_name:
            audio_name = "audio_22k05_s16_mono.wav"
        candidate = dec_log.parent / str(audio_name)
        if not candidate.exists():
            raise SystemExit(
                f"decision audio is missing: {candidate}; re-run sim or pass --audio explicitly")
        audio_path = str(candidate)
    compare = args.compare or str(dec_log.parent / "preview")
    POOL = args.pool_slots or int(log["vram_tiles"])
    (per, prefetch_per, transfer_orders, n_load, n_upd, pal_w,
     Plist, tearing) = resolve(log, POOL, mode=args.alloc)
    inline_prefetch_per, boot_sidecar = split_boot_prefetch(
        log, prefetch_per)
    print(f"resolve[{args.alloc}]: tearing={tearing} M(payload)={len(Plist)} frames={len(per)}")
    supply_meta = log.get("pattern_supply") or {}
    supply_enabled = bool(supply_meta.get("enabled", False))
    if not supply_enabled:
        raise SystemExit(
            "pack v23 requires the unified Prg/Wr0/Wr1/Dic pattern supply; "
            "re-run sim with the current encoder")
    frozen_layout = supply_meta.get("word_ram_layout")
    if frozen_layout is None:
        raise SystemExit(
            "pack requires a decision log with a frozen Word-RAM layout; "
            "re-run sim with the current encoder")
    supply_schema = int(supply_meta.get("schema_version", 0))
    if supply_schema != 5:
        raise SystemExit(
            "pack requires an O_LOADS-v2 Word-RAM decision log; re-run sim")
    try:
        wordram_layout = pattern_supply.word_ram_layout(
            len(per),
            C_CELLS,
            int(sim_cold),
            wr0_load_bytes=int(frozen_layout["wr0_load_bytes"]),
            wr1_load_bytes=int(frozen_layout["wr1_load_bytes"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise SystemExit(
            "pack: frozen Word-RAM layout lacks valid O_LOADS peaks; "
            "re-run sim") from exc
    expected_layout = dataclasses.asdict(wordram_layout)
    if frozen_layout != expected_layout:
        raise SystemExit(
            "pack: frozen Word-RAM layout differs from the current layout "
            "calculation; re-run sim")
    supply_plan = pattern_supply.plan_supply(
        log, per, Plist, prefetch_per=prefetch_per,
        transfer_orders=transfer_orders,
        enabled=supply_enabled,
        wr0_patterns=wordram_layout.wr0_patterns,
        wr1_patterns=wordram_layout.wr1_patterns)
    word_ring_meta = supply_meta.get("word_ring") or {}
    word_ring_enabled = (
        bool(word_ring_meta.get("enabled", False))
    )
    print(f"  pattern supply: enabled={int(supply_plan.enabled)} "
          f"Prg={len(supply_plan.prg_patterns)} "
          f"Wr0={len(supply_plan.wr0_patterns)}/{wordram_layout.wr0_patterns} "
          f"Wr1={len(supply_plan.wr1_patterns)}/{wordram_layout.wr1_patterns} "
          f"Dic={len(supply_plan.dic_patterns)}/{pattern_supply.DIC_BUF_PATTERNS} "
          f"ring={int(word_ring_enabled)} "
          f"refill={len(supply_plan.wr0_refill_patterns)}/"
          f"{len(supply_plan.wr1_refill_patterns)}")
    # 不変条件: 実配信(pack)の1コマ cold がprofile上限を超えたら失敗。
    # sim のモデル cap が pack の連続スロット割当に対して高すぎる兆候(=解析は合うが実機で滑る)。
    # frame0(完全ロードのヘッダ)は除外。
    # realized == cap(共有 TileAllocator で構成上保証)。上限はprofile/logから取得する。
    if profile is not None:
        requested_cold_cap = int(profile.section("encoder")["cold_cap"])
    else:
        # A direct decision-log pack has no TOML to authenticate. Preserve the
        # cap frozen by that sim.
        requested_cold_cap = int(log.get("max_cold", 0))
    cold_ceiling = av_config.cold_cap(requested_cold_cap)
    if int(sim_cold) != cold_ceiling:
        raise SystemExit(
            f"pack: sim cold cap={sim_cold} differs from effective profile "
            f"cap={cold_ceiling}; re-run sim with the current TOML")
    realized_max = max([int(x) for x in n_load[1:]], default=0)
    if realized_max > cold_ceiling:
        raise SystemExit(
            f"pack: realized per-frame cold max={realized_max} > cap={cold_ceiling}. "
            f"共有 TileAllocator では realized=cap のはず=想定外。sim/pack の割り当て食い違いを疑う。")
    print(f"  realized cold: max={realized_max} <= profile cap {cold_ceiling} "
          "(共有割り当て)")
    if len(n_load) and int(n_load[0]) > POOL:
        raise SystemExit(
            f"pack: frame0 exact+prefetch cold={int(n_load[0])} exceeds "
            f"the player's {POOL}-slot resident pool")
    inline_f0 = (
        sum(bool(cold) for cold in per[0][2])
        + sum(bool(item[1]) for item in inline_prefetch_per[0]))
    if inline_f0 > C_CELLS:
        raise SystemExit(
            f"pack: frame0 inline cold={inline_f0} exceeds the "
            f"{C_CELLS}-pattern O_LOADS path")
    packed_tiles, packed_runs = run_stats(
        per, supply_plan.sources, inline_prefetch_per,
        supply_plan.dic_indices, transfer_orders, boot_sidecar,
        loads_caps=(
            wordram_layout.wr0_load_bytes,
            wordram_layout.wr1_load_bytes,
        ),
        word_capacities=(
            wordram_layout.wr0_patterns,
            wordram_layout.wr1_patterns,
        ))
    if not np.array_equal(packed_tiles, n_load):
        frame = int(np.flatnonzero(packed_tiles != n_load)[0])
        raise SystemExit(
            f"pack: internal cold tile mismatch at frame {frame}: "
            f"runs={int(packed_tiles[frame])} resolve={int(n_load[frame])}")
    verify_sim_pattern_transfers(log, packed_tiles, packed_runs, supply_plan)
    inline_prg = np.asarray(supply_plan.prg_loads, np.int64).copy()
    inline_prg[0] -= len(boot_sidecar)
    if inline_prg[0] < 0:
        raise SystemExit("pack: boot sidecar exceeds frame-0 Prg source count")
    wr0_peak, wr1_peak = pattern_supply.output_load_peaks(
        inline_prg, packed_runs)
    packed_peaks = (wr0_peak.bytes, wr1_peak.bytes)
    frozen_peaks = (
        wordram_layout.wr0_load_bytes,
        wordram_layout.wr1_load_bytes,
    )
    if packed_peaks != frozen_peaks:
        raise SystemExit(
            "pack: independently recomputed O_LOADS peaks differ from sim: "
            f"pack={packed_peaks} sim={frozen_peaks}; re-run sim")
    shadow_meta = log.get("shadow_updates") or {}
    update_lists = np.asarray(
        shadow_meta.get("selected", np.zeros(len(per), np.bool_)), np.bool_)
    if update_lists.shape != (len(per),):
        raise SystemExit("pack: frozen shadow update-list flags have wrong frame count")
    if len(update_lists) and bool(update_lists[0]):
        raise SystemExit("pack: frame 0 must retain the legacy bitmap format")
    raw_prefetch_enabled = bool(
        (log.get("raw_prefetch") or {}).get("enabled", False))
    if update_lists.any() and not (
            supply_plan.enabled or raw_prefetch_enabled):
        raise SystemExit(
            "pack: shadow update lists require the cold-run/pattern-supply path")
    frozen_legacy = np.asarray(shadow_meta.get("legacy_cycles", ()), np.int64)
    frozen_list = np.asarray(shadow_meta.get("list_cycles", ()), np.int64)
    recomputed_costs = tuple(
        shadow_updates.frame_cost(cells, C_CELLS) for cells, _entries, _colds in per)
    recomputed_legacy = np.asarray(
        [cost.legacy_cycles for cost in recomputed_costs], np.int64)
    recomputed_list = np.asarray(
        [cost.list_cycles for cost in recomputed_costs], np.int64)
    if (frozen_legacy.shape != recomputed_legacy.shape
            or not np.array_equal(frozen_legacy, recomputed_legacy)
            or frozen_list.shape != recomputed_list.shape
            or not np.array_equal(frozen_list, recomputed_list)):
        raise SystemExit("pack: shadow update cycle model differs from frozen sim decision")
    if np.any(update_lists & (recomputed_list >= recomputed_legacy)):
        frame = int(np.flatnonzero(update_lists & (recomputed_list >= recomputed_legacy))[0])
        raise SystemExit(f"pack: selected shadow list is not faster at frame {frame}")
    blocks, source_pcm_chunks = build_control(
        log, per, n_upd, audio_path, supply_plan.sources, update_lists,
        inline_prefetch_per, supply_plan.dic_indices, transfer_orders,
        word_capacities=(
            wordram_layout.wr0_patterns,
            wordram_layout.wr1_patterns,
        ))
    print(
        f"  shadow updates: list={int(update_lists.sum())}/{len(update_lists)} "
        f"Main saved={int(((recomputed_legacy - recomputed_list) * update_lists).sum())} cycles "
        f"control delta={sum(len(block) for block in blocks) - int(stream_schedule.control_block_lengths(n_upd, packed_runs, cells=C_CELLS, audio_frame_bytes=AUDIO_CONTROL).sum())}B")
    frozen_physical_budget = log.get("physical_budget") or {}
    frozen_control_envelope = None
    if frozen_physical_budget:
        physical_budget_schema = int(
            frozen_physical_budget.get("schema_version", 0))
        if physical_budget_schema not in (1, 2, 3, 4, 5):
            raise SystemExit(
                "pack: unsupported physical-budget schema "
                f"{frozen_physical_budget.get('schema_version')!r}")
        if physical_budget_schema < 3:
            frozen_control_envelope = np.asarray(
                frozen_physical_budget.get("control_sectors", ()), np.int64)
            if frozen_control_envelope.shape != (len(per),):
                raise SystemExit(
                    "pack: physical control-sector envelope length differs")
        frozen_prg_limits = np.asarray(
            frozen_physical_budget.get("prg_pattern_limits", ()), np.int64)
        if frozen_prg_limits.shape != (len(per),):
            raise SystemExit(
                "pack: physical Prg limit length differs")
        packed_prg = np.asarray(supply_plan.prg_loads, np.int64)
        if not word_ring_enabled:
            prg_over = np.flatnonzero(
                (np.arange(len(packed_prg)) > 0)
                & (packed_prg > frozen_prg_limits))
            if prg_over.size:
                frame = int(prg_over[0])
                raise AssertionError(
                    f"pack: frame {frame} Prg loads exceed the construction "
                    "limit frozen by sim")
        if physical_budget_schema >= 2:
            frozen_cold_limits = np.asarray(
                frozen_physical_budget.get("cold_pattern_limits", ()),
                np.int64,
            )
            if frozen_cold_limits.shape != packed_tiles.shape:
                raise SystemExit(
                    "pack: physical cold-limit length differs")
            cold_over = np.flatnonzero(
                (np.arange(len(packed_tiles)) > 0)
                & (packed_tiles > frozen_cold_limits))
            if cold_over.size:
                frame = int(cold_over[0])
                raise AssertionError(
                    f"pack: frame {frame} cold tiles exceed the "
                    "construction limit frozen by sim")
        frozen_block_limits = np.asarray(
            frozen_physical_budget.get("control_block_limits", ()), np.int64)
        actual_block_lengths = np.asarray(
            [len(block) for block in blocks], np.int64)
        if frozen_block_limits.shape != actual_block_lengths.shape:
            raise SystemExit(
                "pack: physical control-block limit length differs")
        control_over = np.flatnonzero(
            (np.arange(len(actual_block_lengths)) > 0)
            & (actual_block_lengths > frozen_block_limits))
        if control_over.size:
            frame = int(control_over[0])
            raise AssertionError(
                f"pack: frame {frame} control block exceeds the construction "
                "limit frozen by sim")
        if physical_budget_schema >= 3 and not word_ring_enabled:
            physical_budget.verify_shared_sector_prefix(
                packed_prg,
                actual_block_lengths,
                prebuffer_capacity_patterns=RING_CAP_PAT,
                frame_sectors=FRAME_SECTORS,
                fps=FPS if physical_budget_schema >= 4 else None,
            )
            frozen_prg = np.asarray(
                frozen_physical_budget.get("realized_prg_patterns", ()),
                np.int64,
            )
            frozen_cold = np.asarray(
                frozen_physical_budget.get("realized_cold_patterns", ()),
                np.int64,
            )
            timed_packed_prg = physical_budget.timed_body_trace(
                packed_prg, name="packed Prg trace")
            timed_packed_cold = physical_budget.timed_body_trace(
                packed_tiles, name="packed cold trace")
            if (
                frozen_prg.shape != timed_packed_prg.shape
                or not np.array_equal(
                    physical_budget.timed_body_trace(
                        frozen_prg, name="frozen Prg trace"),
                    timed_packed_prg,
                )
            ):
                raise SystemExit(
                    "pack: shared-sector realized Prg trace differs from sim")
            if (
                frozen_cold.shape != timed_packed_cold.shape
                or not np.array_equal(
                    physical_budget.timed_body_trace(
                        frozen_cold, name="frozen cold trace"),
                    timed_packed_cold,
                )
            ):
                raise SystemExit(
                    "pack: shared-sector realized cold trace differs from sim")
            print(
                "  cadence-sector prefix照合: control/payload deadlines exact")
    if word_ring_enabled:
        frozen_schedule = log.get("stream_schedule") or {}
        try:
            sc = wordbuf_ring.replay_frozen_schedule(
                prg_loads=supply_plan.prg_loads,
                wr0_loads=supply_plan.wr0_loads,
                wr1_loads=supply_plan.wr1_loads,
                block_lengths=np.asarray(
                    [len(block) for block in blocks], np.int64),
                payload_sectors=np.asarray(
                    frozen_schedule.get("payload_sectors", ()), np.int64),
                control_sectors=np.asarray(
                    frozen_schedule.get("control_sectors", ()), np.int64),
                word_stage_sectors=np.asarray(
                    word_ring_meta.get("stage_sectors", ()), np.int64),
                fps=FPS,
                prebuffer_patterns=int(np.asarray(
                    frozen_schedule.get("ring_occupancy", ()),
                    np.int64,
                )[0]),
                prg_capacity_patterns=RING_CAP_PAT,
                word_capacities=(
                    wordram_layout.wr0_patterns,
                    wordram_layout.wr1_patterns,
                ),
                boot_patterns=tuple(
                    int(value)
                    for value in word_ring_meta.get("boot_patterns", ())
                ),
                f0_cold=int(n_load[0]),
            )
        except (IndexError, TypeError, ValueError) as exc:
            raise SystemExit(
                f"pack: frozen WordBuf ring proof failed: {exc}") from exc
        print(
            "  WordBuf ring再証明: Prg/Wr0/Wr1 deadlines and capacities exact")
    else:
        sc = schedule(
            per,
            supply_plan.prg_loads,
            blocks,
            control_sector_envelope=frozen_control_envelope,
        )
    if supply_plan.enabled and log.get("pattern_supply") is None:
        frozen_lengths = np.asarray(
            (log.get("stream_schedule") or {}).get("block_lengths", ()), np.int64)
        actual_lengths = np.asarray(sc["blk_len"], np.int64)
        if frozen_lengths.shape != actual_lengths.shape or not np.array_equal(
                frozen_lengths, actual_lengths):
            raise SystemExit(
                "pack: pattern supply changed control block lengths; source assignment "
                "must preserve complete cold runs")
        print("  BODY配送/RING照合: preloadでPrg需要を変更したためbaseline traceとの一致対象外; "
              "control lengths exact")
    else:
        verify_sim_stream_schedule(log, sc)
    st = ("OK" if sc["feasible"] else
          f"INFEASIBLE(over {sc['over']} under {sc.get('under',0)} "
          f"rate_lead_peak/end {sc.get('rate_lead_peak', 0)}/"
          f"{sc.get('rate_lead_end', 0)})")
    Pb = sum(len(b) for b in blocks)
    under = sc.get("under", 0)
    evaluation_end = int(sc.get("evaluation_end_frame", len(per)))
    print(f"schedule[{st}] prebuf {sc['prebuf_pat']*PAT/1024:.0f}KB ring_peak {sc['ring_peak']*PAT/1024:.0f}KB "
          f"ring_min eval {sc.get('ring_min_evaluation', sc.get('ring_min', 0))*PAT/1024:.1f}KB "
          f"(f1..{max(1, evaluation_end - 1)}, full {sc.get('ring_min',0)*PAT/1024:.1f}KB, "
          f"tail starts f{evaluation_end}, normal {RING_CAP_KB}KB, "
          f"delivery {RING_DELIVERY_CAP_KB}KB)  under(枯渇) {under} "
          f"({100.0*under/max(1,len(per)):.1f}%)  n_pay_sec avg {sc['n_pay_sec'].mean():.2f}  "
          f"control-first ready_min {sc['ready_min']}pat ctrl_min {sc['ctrl_min']}B  "
          f"rate_lead peak/end {sc['rate_lead_peak']}/{sc['rate_lead_end']}sec")
    startup_end = min(len(per), 31)
    if startup_end > 1:
        startup_fsec = int(sc["fsec"][1:startup_end].sum())
        startup_rate = int(sc["ratedelta"][1:startup_end].sum())
        print(f"  startup BODY frames 1..{startup_end - 1}: {startup_fsec} sectors "
              f"(CD-1x allowance {startup_rate}, avoidable excess {startup_fsec - startup_rate})")
    if (sc["prebuf_pat"] > RING_CAP_PAT
            or sc["ring_peak"] > RING_DELIVERY_CAP_PAT):
        raise SystemExit(
            "pack: PrgBuf exceeds its fps-derived prebuffer or physical "
            f"delivery limit (normal={RING_CAP_KB}KB, "
            f"delivery={RING_DELIVERY_CAP_KB}KB) "
            f"(prebuf={sc['prebuf_pat']*PAT/1024:.0f}KB, "
            f"peak={sc['ring_peak']*PAT/1024:.0f}KB)")
    if not sc["feasible"]:
        raise SystemExit(
            "pack: refusing to write an infeasible BODY schedule "
            f"(over={sc['over']} under={sc.get('under', 0)} "
            f"ready_min={sc['ready_min']} ctrl_min={sc['ctrl_min']} "
            f"rate_lead_peak/end={sc.get('rate_lead_peak', 0)}/"
            f"{sc.get('rate_lead_end', 0)})")
    if args.verify:
        decode_verify(log, per, blocks, supply_plan, sc, compare_dir=compare or None,
                      sample_dir=Path(output).parent / "decoded",
                      boot_sidecar=boot_sidecar)
    if not args.no_write:
        write_stream(
            output, log, per, blocks, source_pcm_chunks, supply_plan,
            wordram_layout, sc, POOL,
            boot_sidecar=boot_sidecar,
            sp_extension_bytes=sp_extension_bytes)


def _profile_from_command_line():
    for index, value in enumerate(sys.argv[1:]):
        if value == "--config":
            try:
                return load_profile(sys.argv[index + 2])
            except IndexError as exc:
                raise SystemExit("--config requires a path") from exc
        if value.startswith("--config="):
            return load_profile(value.split("=", 1)[1])
    return None


if __name__ == "__main__":
    _command_profile = _profile_from_command_line()
    _stem_lease = None
    _sim_lease = None
    if _command_profile is not None:
        try:
            _stem_lease = resource_tokens.acquire_stem(
                _command_profile.sim_stem)
        except resource_tokens.ResourceBusyError as exc:
            print(str(exc), file=sys.stderr)
            raise SystemExit(75) from exc
    try:
        if _command_profile is not None:
            _sim_lease = tmpfs_workspace.lease_managed_path(
                _command_profile.output_dir)
        main()
    finally:
        if _sim_lease is not None:
            _sim_lease.release()
        if _stem_lease is not None:
            _stem_lease.release()
