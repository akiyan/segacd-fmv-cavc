#!/usr/bin/env python3
"""Render the real sim data with the canonical 1920x1080 analysis layout.

``layout_preview.py`` owns layout, headings, scales, and reading rules;
``analysis_style.py`` owns category meanings and semantic colours.  This
module owns the real-data mapping, TSV fields, and final mux.

The content panels and TSV remain indexed by the sim/content frame.  The MP4
is exact 60 fps: ffmpeg holds each content PNG to the next content timestamp,
then overlays independently rendered waveform+spectrum interiors at every
1/60-second output timestamp.  Thus audio motion follows analysis-video
frames, not Sega CD content-frame switches.  The muxed WAV and both panels use
the sim's checkpointed playback model, never the clean source WAV.

入力(env):
  CBRSIM_OUT       sim出力ディレクトリ(raw/decisions.pkl/stats.npz/
                   miss_masks.npy/buffer_remaining.npz/palettes.bin/
                   audio WAV/report.txt)。preview/catmap は本工程で生成する。
  CBRSIM_SRCLABEL  右Sourceパネル見出し(既定 "Source")
  CBRSIM_MODE      画面モード H32/H40 (既定 H32。DMA理論値に使う)
  ANALYSIS_OUT     tmpfs artifactに使う要求mp4名
  ANALYSIS_TSV     明示した場合の永続TSV実体path (既定はlogs/のunique path)
  ANALYSIS_CQ      h264_nvenc cq (既定 23)
W/H/タイル数/表示アスペクト/諸元は sim 出力から自動導出。

usage: python3 tools/render_analysis.py PROFILE.toml       # 全編→mp4
       python3 tools/render_analysis.py PROFILE.toml --tsv-only
       python3 tools/render_analysis.py PROFILE.toml A B   # frame [A,B) だけPNG(検証用, mp4化しない)
"""
import sys
import os
import csv
import glob
import pickle
import subprocess
from pathlib import Path
from fractions import Fraction
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).parent))
from encode_config import consume_config_arg

# Match the sim invocation exactly without requiring callers to repeat its
# resolved CBRSIM_* environment by hand.
CONFIG_PROFILE = consume_config_arg(
    sys.argv, required=__name__ == "__main__")

import layout_preview as L
import analysis_audio
import analysis_style as style
import stream_schedule
import analysis_logs
import resource_tokens
import r2v_model
import scroll_frames
import scroll_plan
import shadow_updates
import tmpfs_workspace
from cbr_paths import artifact_path, sim_work_dir

SIM = str(sim_work_dir())
SRCLABEL = os.environ.get("CBRSIM_SRCLABEL", "Source")


def _source_spec():
    """Source見出し併記用: 元動画の 解像度 / fps / 音声仕様 を ffprobe で組み立てる(ビットレートは省略)。"""
    src = os.environ.get("CBRSIM_SRC", "")
    if not src or not Path(src).exists():
        return ""
    import subprocess
    import json as _json
    try:
        vj = _json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate", "-of", "json", src],
            capture_output=True, text=True).stdout)["streams"][0]
        num, den = vj["r_frame_rate"].split("/")
        fps = round(float(num) / float(den))
        parts = ["%dx%d" % (vj["width"], vj["height"]), "%dfps" % fps]
        aj = _json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=codec_name,sample_rate,channels", "-of", "json", src],
            capture_output=True, text=True).stdout).get("streams", [])
        if aj:
            a = aj[0]; ch = int(a.get("channels", 0)); sr = int(a.get("sample_rate", 0))
            chs = {1: "mono", 2: "stereo"}.get(ch, "%dch" % ch)
            parts.append("%s %gkHz %s" % (a["codec_name"].upper(), sr / 1000.0, chs))
        return " / ".join(parts)
    except Exception:
        return ""


SRC_SPEC = _source_spec()
MODE = os.environ.get("CBRSIM_MODE", "H32")
OUT_MP4 = Path(os.environ.get(
    "ANALYSIS_OUT", str(artifact_path("analysis", sim_dir=SIM))))
OUT_TSV = (
    Path(os.environ["ANALYSIS_TSV"])
    if os.environ.get("ANALYSIS_TSV") else None
)
CQ = os.environ.get("ANALYSIS_CQ", "23")
FRAMES_DIR = f"{SIM}/analysis_frames"
AUDIO_FRAMES_DIR = f"{SIM}/analysis_audio_frames"
AUDIO_STR = "22.05kHz mono IMA ADPCM"       # 既定。sim出力(stats)にラベルがあればそれを使う

# ---- フォント(layout_preview のグローバルへ) ----
L.f_head = ImageFont.truetype(L.FONT, 33)
L.f_leg = ImageFont.truetype(L.FONT, 15)
L.f_lbl = ImageFont.truetype(L.FONT, 20)
L.f_sm = ImageFont.truetype(L.FONT, 12)
L.f_meta = ImageFont.truetype(L.FONT, 18)
L.f_pal = ImageFont.truetype(L.FONT, 14)

# ---- sim出力から諸元を自動導出 ----
z = np.load(f"{SIM}/stats.npz", allow_pickle=True)
S = z["stats"]
STAT_COLUMNS = tuple(str(z["cols"]).split())
idx = {k: i for i, k in enumerate(STAT_COLUMNS)}
FPS = float(z["fps"]); C = int(z["cells"]); BUDGET = int(z["budget_tiles"])
ACTIVE_TILES = int(z["active_tiles"]) if "active_tiles" in z else C
if "max_cold" not in z:
    raise ValueError("stats.npz has no profile cold cap; re-run sim")
COLD_CAP = int(z["max_cold"])
NF = len(S)
DECISION_PATH = Path(SIM) / "decisions.pkl"
if not DECISION_PATH.is_file():
    raise FileNotFoundError(
        f"analysis decisions are missing: {DECISION_PATH}; re-run sim")
with DECISION_PATH.open("rb") as _decision_source:
    DECISIONS = pickle.load(_decision_source)
DECISION_FRAMES = DECISIONS.get("frames")
if not isinstance(DECISION_FRAMES, list) or len(DECISION_FRAMES) != NF:
    raise SystemExit("analysis decision-frame count differs from stats")
_geom = tuple(int(value) for value in DECISIONS.get("geom", ()))
if len(_geom) != 4:
    raise SystemExit("analysis decision geometry is missing")
TCOLS, TROWS, _decision_cells, _decision_tile = _geom
if _decision_cells != C or _decision_tile != 8:
    raise SystemExit("analysis decision geometry differs from stats")
W, H = TCOLS * _decision_tile, TROWS * _decision_tile
_display_category_masks = DECISIONS.get("display_category_masks") or {}
if int(_display_category_masks.get("schema_version", 0)) != 1:
    raise SystemExit(
        "analysis per-cell category masks are missing; re-run sim")
CATEGORY_MASK_ORDER = tuple(
    str(name) for name in _display_category_masks.get("bit_order", ()))
CATEGORY_MASK_ROWS = tuple(_display_category_masks.get("rows", ()))
if (len(CATEGORY_MASK_ROWS) != NF
        or any(len(row) != C * np.dtype(np.uint16).itemsize
               for row in CATEGORY_MASK_ROWS)):
    raise SystemExit("analysis per-cell category masks have the wrong shape")
if "audio_label" in z:
    AUDIO_STR = str(z["audio_label"])        # sim側のADPCM音声ラベル
if "audio_playback_file" not in z:
    raise SystemExit(
        "stats.npz has no audio_playback_file; re-sim this source. Selecting a "
        "WAV by filename would silently use the clean source audio instead of "
        "the ADPCM playback model.")
AUDIO_PATH = Path(SIM) / str(z["audio_playback_file"])
if not AUDIO_PATH.is_file():
    raise FileNotFoundError(
        f"stats.npz playback audio is missing: {AUDIO_PATH}")
_raw = sorted(glob.glob(f"{SIM}/raw/*.png"))
RW, RH = Image.open(_raw[0]).size             # Sourceパネル素材の画素
_SOURCE_SAR = Fraction(os.environ.get("CBRSIM_SOURCE_SAR", "1:1").replace(":", "/"))
SOURCE_SAR_NUM = _SOURCE_SAR.numerator
SOURCE_SAR_DEN = _SOURCE_SAR.denominator
_analysis_profile = CONFIG_PROFILE.section("analysis") if CONFIG_PROFILE else {}
SOURCE_CANVAS = tuple(_analysis_profile.get("source_canvas", (RW, RH)))
SOURCE_CANVAS_W, SOURCE_CANVAS_H = map(int, SOURCE_CANVAS)
# 画面モード(H32/H40/mode4)から PAR・実機画面サイズ・表示アスペクトを取得
_M = L.MODES[MODE]
PAR = _M["par"]                                # 1ドット横長比
A_CONTENT = (W / H) * PAR                      # カテゴリ(タイル解析)の表示比
RES = f"{W}x{H} ({TCOLS}x{TROWS})"
# 実機画面(この解像度を画面いっぱいに拡大せず中央配置する)。
SCREEN_W = max(_M["sw"], W)
SCREEN_H = max(_M["sh"], H)
SCREEN_A = L.screen_aspect(MODE)               # 画面の表示アスペクト(H32/H40=64:49, mode4≈14:9)
BUF = np.load(f"{SIM}/buffer_remaining.npz")
BUF_SCHEMA = int(BUF["schema_version"]) if "schema_version" in BUF else 1
BUF_KIND = str(BUF["remaining_kind"]) if "remaining_kind" in BUF else "legacy"
if BUF_SCHEMA < 6 or BUF_KIND != "three_consumptive_plus_dicbuf":
    raise SystemExit(
        f"analysis requires fps-jitter pattern supply schema 6, got "
        f"schema={BUF_SCHEMA} kind={BUF_KIND!r}; re-run sim")
SUPPLY_CAPACITIES = {
    "Prg": int(BUF["prg_capacity"]),
    "Wr0": int(BUF["wr0_capacity"]),
    "Wr1": int(BUF["wr1_capacity"]),
}
SUPPLY_REMAINING = {
    "Prg": BUF["prg_remaining"].astype(np.int64),
    "Wr0": BUF["wr0_remaining"].astype(np.int64),
    "Wr1": BUF["wr1_remaining"].astype(np.int64),
}
if "quality_budget_remaining" not in BUF:
    raise SystemExit("analysis quality-budget trace is missing; re-run sim")
QUALITY_REM = BUF["quality_budget_remaining"].astype(np.int64)
for _name, _remaining in SUPPLY_REMAINING.items():
    _capacity = SUPPLY_CAPACITIES[_name]
    if len(_remaining) != NF:
        raise SystemExit(
            f"{_name} trace has {len(_remaining)} frames, expected {NF}; re-run sim")
    if (_remaining < 0).any() or (_remaining > _capacity).any():
        raise SystemExit(
            f"{_name} trace is outside capacity {_capacity}; re-run sim")
if len(QUALITY_REM) != NF:
    raise SystemExit(
        f"quality-budget trace has {len(QUALITY_REM)} frames, expected {NF}; re-run sim")
_body_fields = (
    "body_useful_payload_bytes",
    "body_useful_control_bytes",
    "body_pad_bytes",
    "body_physical_bytes",
)
if any(name not in BUF for name in _body_fields):
    raise SystemExit(
        "BODY useful-delivery trace is incomplete; re-run sim")
BODY_PAYLOAD_BYTES = BUF["body_useful_payload_bytes"].astype(np.int64)
BODY_CONTROL_BYTES = BUF["body_useful_control_bytes"].astype(np.int64)
BODY_PAD_BYTES = BUF["body_pad_bytes"].astype(np.int64)
BODY_PHYSICAL_BYTES = BUF["body_physical_bytes"].astype(np.int64)
for _name, _values in (
        ("payload", BODY_PAYLOAD_BYTES),
        ("control", BODY_CONTROL_BYTES),
        ("pad", BODY_PAD_BYTES),
        ("physical", BODY_PHYSICAL_BYTES)):
    if len(_values) != NF:
        raise SystemExit(
            f"BODY {_name} trace has {len(_values)} slots, expected {NF}; re-run sim")
if not np.array_equal(
        BODY_PAYLOAD_BYTES + BODY_CONTROL_BYTES + BODY_PAD_BYTES,
        BODY_PHYSICAL_BYTES):
    raise SystemExit(
        "BODY useful/pad trace does not sum to physical slots; re-run sim")
if any(int(values[0]) != 0 for values in (
        BODY_PAYLOAD_BYTES, BODY_CONTROL_BYTES, BODY_PAD_BYTES,
        BODY_PHYSICAL_BYTES)):
    raise SystemExit(
        "timed BODY delivery slot 0 must exclude the BODY arm/frame 0; re-run sim")
MISS_MASKS = np.load(f"{SIM}/miss_masks.npy")

# ---- hardware-scroll state (sim decisions) ----
# ``positions`` are absolute VDP scroll values per frame; the crop formula
# display = plane[(xy - position) % plane_size] makes a decreasing position a
# rightward/downward camera pan.  The legend indicator and category-map edge
# overlay appear only when the movie adopted at least one scroll window.
_SCROLL_META = DECISIONS.get("scroll") or {}
SCROLL_ACTIVE = np.asarray(
    _SCROLL_META.get("active", np.zeros(NF, np.bool_)), np.bool_)
SCROLL_POSITIONS = np.asarray(
    _SCROLL_META.get("positions", np.zeros((NF, 2), np.int64)), np.int64)
if SCROLL_ACTIVE.shape != (NF,) or SCROLL_POSITIONS.shape != (NF, 2):
    raise SystemExit("analysis scroll trace has an invalid shape; re-run sim")
SCROLL_ON = bool(SCROLL_ACTIVE.any())
if SCROLL_ON and "scrl" not in idx:
    raise SystemExit(
        "analysis Scrl category is missing for a scroll movie; re-run sim")


def frame_scroll(i):
    """Legend/category-map hardware-scroll state for one frame.

    Returns None for a movie without any adopted scroll window (the legend
    indicator is omitted entirely), an inactive dict between windows, and an
    active dict with the axis, absolute VDP position, camera-pan direction,
    and pan speed (px per content frame) inside a window.
    """
    if not SCROLL_ON:
        return None
    if not SCROLL_ACTIVE[i]:
        return dict(active=False)
    hscroll = int(SCROLL_POSITIONS[i, 0])
    vscroll = int(SCROLL_POSITIONS[i, 1])
    axis = "H" if hscroll else "V"
    position = hscroll or vscroll
    previous = 0
    if i > 0 and SCROLL_ACTIVE[i - 1]:
        previous = int(
            SCROLL_POSITIONS[i - 1, 0] or SCROLL_POSITIONS[i - 1, 1])
    delta = position - previous
    # A zero-movement frame (fractional cadence) keeps the window's overall
    # direction, recovered from the accumulated position's sign.
    toward = delta if delta else position
    if axis == "H":
        direction = "right" if toward < 0 else "left"
    else:
        direction = "down" if toward < 0 else "up"
    return dict(active=True, axis=axis, position=position,
                speed=abs(delta), direction=direction)

# ---- stats -> mutually-exclusive display categories ----
col = lambda k: S[:, idx[k]].astype(np.int64) if k in idx else np.zeros(NF, np.int64)
Raw = col("tx"); Dedup = col("dedup"); Near = col("near")
# Flbk = 旧Mid+Farを統合(Missのフォールバック)。新statsは flbk 列, 旧statsは mid+far を合算(後方互換)
Flbk = col("flbk") + col("mid") + col("far")
Want = col("want"); Miss = col("miss")
if "buf" not in idx:
    raise SystemExit("analysis exact-source total is missing; re-run sim")
Buf = col("buf")
_source_fields = ("prg", "wr0", "wr1", "dic")
if any(name not in idx for name in _source_fields):
    raise SystemExit(
        "analysis physical-source categories are missing; re-run sim")
Prg, Wr0, Wr1, Dic = (col(name) for name in _source_fields)
if not np.array_equal(Prg + Wr0 + Wr1 + Dic, Buf):
    raise SystemExit(
        "analysis physical-source categories do not sum to legacy Buf; re-run sim")
if "same" not in idx:
    raise SystemExit("analysis exact Same category is missing; re-run sim")
Same = col("same")
# Scrl = scroll-carried cells (unfunded want during an active scroll window).
# A pre-Scrl stats file is acceptable only for a movie without scroll windows,
# where the category is identically zero.
Scrl = col("scrl")
DMA_TILES = col("dma_tiles") if "dma_tiles" in idx else Raw + Buf
PREFETCH = col("prefetch")
_r2v_fields = (
    "r2v_words", "r2v_pattern_words", "r2v_repair_words",
    "r2v_name_table_words", "r2v_cram_words", "r2v_short_runs",
)
if any(name not in z for name in _r2v_fields):
    raise SystemExit("analysis R2V workload is missing; re-run sim")
R2V_WORDS = z["r2v_words"].astype(np.int64)
R2V_PATTERN_WORDS = z["r2v_pattern_words"].astype(np.int64)
R2V_REPAIR_WORDS = z["r2v_repair_words"].astype(np.int64)
R2V_NAME_TABLE_WORDS = z["r2v_name_table_words"].astype(np.int64)
R2V_CRAM_WORDS = z["r2v_cram_words"].astype(np.int64)
R2V_SHORT_RUNS = z["r2v_short_runs"].astype(np.int64)
if any(len(values) != NF for values in (
    R2V_WORDS, R2V_PATTERN_WORDS, R2V_REPAIR_WORDS,
    R2V_NAME_TABLE_WORDS, R2V_CRAM_WORDS, R2V_SHORT_RUNS,
)):
    raise SystemExit("analysis R2V workload has the wrong frame count")
# R2V is a player-side interpretation of stable encoder decisions. Recalculate
# it while rendering so a player-only transfer-policy change does not force a
# full video re-encode or an encoder-version bump.
_current_r2v = r2v_model.calculate_words(
    R2V_PATTERN_WORDS // r2v_model.PATTERN_WORDS,
    col("dma_runs"),
    R2V_CRAM_WORDS != 0,
    R2V_NAME_TABLE_WORDS,
)
for _component in _current_r2v.values():
    _component[0] = 0
R2V_WORDS = _current_r2v["words"]
R2V_REPAIR_WORDS = _current_r2v["repair_words"]
R2V_MAX = r2v_model.timed_scale_max(R2V_WORDS)
PREFETCH_CAP = int(z["raw_prefetch_cap"]) if "raw_prefetch_cap" in z else max(
    1, int(PREFETCH.max(initial=0)))


def _balanced_raw_flags(raw_count, total_count):
    """Spread one frame's Raw attribution evenly through its PrgBuf loads."""
    raw_count = int(raw_count)
    total_count = int(total_count)
    if not 0 <= raw_count <= total_count:
        raise SystemExit(
            f"Raw payload attribution {raw_count} exceeds "
            f"{total_count} PrgBuf loads")
    if total_count == 0:
        return np.zeros(0, np.bool_)
    positions = np.arange(total_count, dtype=np.int64)
    return (
        ((positions + 1) * raw_count // total_count)
        != (positions * raw_count // total_count)
    )


if "body_raw_payload_bytes" in BUF:
    BODY_RAW_PAYLOAD_BYTES = BUF[
        "body_raw_payload_bytes"].astype(np.int64)
    if BODY_RAW_PAYLOAD_BYTES.shape != BODY_PAYLOAD_BYTES.shape:
        raise SystemExit(
            "analysis Raw payload trace has the wrong frame count; re-run sim")
    BODY_PRG_PAYLOAD_BYTES = (
        BODY_PAYLOAD_BYTES - BODY_RAW_PAYLOAD_BYTES)
    if np.any(BODY_PRG_PAYLOAD_BYTES < 0):
        raise SystemExit(
            "analysis Raw payload exceeds useful payload; re-run sim")
else:
    if "prg_loads" not in BUF:
        raise SystemExit("analysis PrgBuf load trace is missing; re-run sim")
    _prg_loads = BUF["prg_loads"].astype(np.int64)
    if len(_prg_loads) != NF:
        raise SystemExit("analysis PrgBuf load trace has the wrong frame count")
    _payload_raw_flags = np.concatenate([
        _balanced_raw_flags(Raw[i], _prg_loads[i])
        for i in range(1, NF)
    ])
    _delivered_payload_patterns = (
        int(BODY_PAYLOAD_BYTES.sum()) // stream_schedule.PATTERN_BYTES)
    _prebuffer_patterns = (
        len(_payload_raw_flags) - _delivered_payload_patterns)
    BODY_RAW_PAYLOAD_BYTES, BODY_PRG_PAYLOAD_BYTES = (
        stream_schedule.split_body_payload_classes(
            _payload_raw_flags,
            BODY_PAYLOAD_BYTES,
            prebuffer_patterns=_prebuffer_patterns,
        )
    )
if not np.array_equal(
        BODY_RAW_PAYLOAD_BYTES + BODY_PRG_PAYLOAD_BYTES,
        BODY_PAYLOAD_BYTES,
):
    raise AssertionError("Band Raw/Prg split does not cover BODY payload")


def _legacy_dma_runs():
    """Replay the shared allocator when rendering an older stats.npz.

    Fresh sims save dma_runs directly. Existing verified sims can still render
    the exact packed-run count from decisions.pkl without a full re-encode.
    """
    path = Path(SIM) / "decisions.pkl"
    if not path.exists():
        raise SystemExit(
            "DMA runs: stats.npz has no dma_runs and decisions.pkl is missing; "
            "re-run sim instead of displaying an estimated value")
    try:
        from tile_alloc import TileAllocator, count_slot_runs
        with path.open("rb") as fh:
            log = pickle.load(fh)
        frames = log["frames"]
        if len(frames) != NF:
            raise ValueError(f"decision frames {len(frames)} != stats frames {NF}")
        pool = int(log.get(
            "vram_tiles",
            log.get("config", {}).get("hardware", {}).get("vram_tiles", 1400)))
        alloc = TileAllocator(C, pool, 1)
        result = np.zeros(NF, np.int64)
        replay_tiles = np.zeros(NF, np.int64)
        for i, frame in enumerate(frames):
            ordered = sorted(frame, key=lambda item: item[0])
            placed = alloc.place_frame([(int(cell), key) for cell, _pal, key in ordered], i)
            cold_slots = [slot for slot, cold in placed if cold]
            replay_tiles[i] = len(cold_slots)
            result[i] = count_slot_runs(cold_slots)
        mismatch = np.flatnonzero(replay_tiles != DMA_TILES)
        if mismatch.size:
            i = int(mismatch[0])
            raise ValueError(
                f"frame {i} cold tiles decisions={int(replay_tiles[i])} "
                f"stats={int(DMA_TILES[i])}")
        print("Pattern runs: replayed exact values from legacy decisions.pkl")
        return result
    except Exception as exc:
        raise SystemExit(
            f"Pattern runs: exact legacy replay failed ({exc}); re-run sim") from exc


DMA_RUNS = col("dma_runs") if "dma_runs" in idx else _legacy_dma_runs()
FULL = {
    "Raw": Raw, "Same": Same, "Near": Near, "Flbk": Flbk, "Miss": Miss,
    "Scrl": Scrl, "Prg": Prg, "Wr0": Wr0, "Wr1": Wr1, "Dic": Dic,
}
_category_sum = sum(FULL.values())
if not np.array_equal(_category_sum, np.full(NF, C, np.int64)):
    bad = int(np.flatnonzero(_category_sum != C)[0])
    raise SystemExit(
        f"analysis categories do not cover frame {bad}: "
        f"{int(_category_sum[bad])} != {C}; re-run sim")
WIN = 4; HALF = int(round(FPS * WIN))                       # 線グラフ ±4秒

# ---- palettes.bin(MDワード 0000BBB0GGG0RRR0) -> RGB(使用色枠なし) ----
pb = np.frombuffer(Path(f"{SIM}/palettes.bin").read_bytes(), ">u2").reshape(4, 16)


def md_rgb(w):
    r = (int(w) >> 1) & 7; g = (int(w) >> 5) & 7; b = (int(w) >> 9) & 7
    return (r * 36, g * 36, b * 36)


PAL = [[md_rgb(pb[p, c]) for c in range(16)] for p in range(4)]

# ---- 実CRAM状態(Prev/Current/Next とsim preview再生用) ----
_SP = np.load(f"{SIM}/seg_palettes.npz")
SEG_PALS = _SP["seg_pals"]                     # (nseg,4,15,3) rgb333(0-7)
FRAME_SEG = _SP["frame_seg"]                   # (NF,)
SEGMENT_ENTRY_CRAM = (
    _SP["segment_entry_cram"]
    if "segment_entry_cram" in _SP.files else SEG_PALS
)
FRAME_TYPES = (
    _SP["frame_types"].astype(np.uint8)
    if "frame_types" in _SP.files else np.zeros(NF, np.uint8)
)
ACTIVE_FRAME_CRAM = (
    _SP["active_frame_cram"]
    if "active_frame_cram" in _SP.files
    else SEGMENT_ENTRY_CRAM[FRAME_SEG]
)
if (FRAME_TYPES.shape != (NF,)
        or ACTIVE_FRAME_CRAM.shape != (NF, 4, 15, 3)
        or SEGMENT_ENTRY_CRAM.shape != SEG_PALS.shape):
    raise SystemExit("analysis CRAM state has an invalid shape; re-run sim")

# ---- 音声波形 / spectrum panel用データ(sim OUT のplayback-model WAV) ----
import wave as _wave  # noqa: E402
ANALYSIS_VIDEO_FPS = L.ANALYSIS_VIDEO_FPS
WAVE_WIN_S = 1.0 / ANALYSIS_VIDEO_FPS
WAVE_BW = L.WAVE_FRAME[2] - L.WAVE_FRAME[0] - 2
SPEC_BW = L.SPEC_FRAME[2] - L.SPEC_FRAME[0] - 2
AUDIO_OVERLAY_X = L.WAVE_FRAME[0] + 1
AUDIO_OVERLAY_Y = L.WAVE_FRAME[1] + 1
AUDIO_OVERLAY_W = L.SPEC_FRAME[2] - AUDIO_OVERLAY_X
AUDIO_OVERLAY_H = L.WAVE_FRAME[3] - L.WAVE_FRAME[1] - 2
AUDIO_OUTPUT_FRAMES = analysis_audio.output_frame_count(
    NF, content_fps=FPS, output_fps=ANALYSIS_VIDEO_FPS)
try:
    _wf = _wave.open(str(AUDIO_PATH), "rb")
    AUDIO_RATE = _wf.getframerate()
    _audio_width = _wf.getsampwidth()
    _audio_channels = _wf.getnchannels()
    _audio_raw = _wf.readframes(_wf.getnframes())
    _wf.close()
    AUDIO_SAMPLES, AUDIO_FULL_SCALE = analysis_audio.decode_pcm_mono(
        _audio_raw,
        sample_width=_audio_width,
        channels=_audio_channels,
    )
except Exception as _e:
    AUDIO_RATE = 22_050
    AUDIO_SAMPLES = np.zeros(1, np.int32)
    AUDIO_FULL_SCALE = 32768
    print("analysis audio: playback-model WAV unavailable ->", _e)


def pal_rgb(palette):
    p = np.asarray(palette).astype(int)        # (4,15,3) 0-7 -> *36 で表示
    return [[(int(p[pl][c][0]) * 36, int(p[pl][c][1]) * 36, int(p[pl][c][2]) * 36) for c in range(15)]
            for pl in range(4)]


def seg_pal_rgb(seg):
    seg = int(np.clip(seg, 0, len(SEGMENT_ENTRY_CRAM) - 1))
    return pal_rgb(SEGMENT_ENTRY_CRAM[seg])


def frame_palettes(i):
    s = int(FRAME_SEG[i]) if i < len(FRAME_SEG) else 0
    last = len(SEG_PALS) - 1
    return {"Prev": seg_pal_rgb(s - 1) if s > 0 else None,      # 前後にパレット無し=ブランク
            "Current": pal_rgb(ACTIVE_FRAME_CRAM[i]),
            "Next": seg_pal_rgb(s + 1) if s < last else None}


def _cells_to_image(cell_rgb):
    return (
        cell_rgb.reshape(TROWS, TCOLS, 8, 8, 3)
        .transpose(0, 2, 1, 3, 4)
        .reshape(H, W, 3)
    )


def materialize_analysis_panels(frames):
    """Replay decisions and create preview/category PNGs for analysis only."""
    requested = {int(frame) for frame in frames}
    preview_dir = Path(SIM) / "preview"
    catmap_dir = Path(SIM) / "catmap"
    preview_dir.mkdir(parents=True, exist_ok=True)
    catmap_dir.mkdir(parents=True, exist_ok=True)
    targets = range(NF) if len(requested) == NF else requested
    for frame in targets:
        (preview_dir / f"{frame:05d}.png").unlink(missing_ok=True)
        (catmap_dir / f"{frame:05d}.png").unlink(missing_ok=True)

    required_order = (
        "Raw", "Near", "Flbk", "Prg", "Wr0", "Wr1", "Dic", "Miss", "Scrl",
    )
    # A pre-Scrl mask order is acceptable only without scroll windows (the
    # Scrl bit would be identically zero there).
    if CATEGORY_MASK_ORDER == required_order[:-1] and not SCROLL_ON:
        pass
    elif CATEGORY_MASK_ORDER != required_order:
        raise SystemExit(
            f"analysis category-mask order differs: {CATEGORY_MASK_ORDER!r}")
    category_bits = {
        name: np.uint16(1 << index)
        for index, name in enumerate(CATEGORY_MASK_ORDER)
    }
    # A scroll-adopted movie's decision cells address the physical 64x32
    # rolling plane; replay it exactly like the pack's decode verifier and
    # crop the fine-scrolled viewport for the preview panel. Without scroll
    # controls the plane degenerates to the logical grid.
    scroll_active_flags = SCROLL_ACTIVE
    scroll_position_pairs = SCROLL_POSITIONS
    plane_on = SCROLL_ON
    plane_cells = (
        shadow_updates.SCROLL_PLANE_CELLS if plane_on else C)
    normal_cells = (
        scroll_plan.normal_plane_cells(TCOLS, TROWS)
        if plane_on else tuple(range(C)))
    display_idx = np.zeros((plane_cells, 64), np.uint8)
    display_pal = np.zeros(plane_cells, np.uint8)
    scrolling = False
    scroll_position = 0
    scroll_state = None
    for frame, updates in enumerate(DECISION_FRAMES):
        if scroll_active_flags[frame]:
            hscroll = int(scroll_position_pairs[frame, 0])
            vscroll = int(scroll_position_pairs[frame, 1])
            axis = (
                scroll_frames.AXIS_HORIZONTAL if hscroll
                else scroll_frames.AXIS_VERTICAL)
            position = hscroll or vscroll
            # Entry needs no seeding: ordinary frames already write through
            # the normal_cells mapping, so the viewport's plane cells hold
            # the logical content when the first control arrives.
            delta = position - scroll_position
            scroll_state = scroll_plan.position_state(
                frame, axis, position, delta=delta,
                columns=TCOLS, rows=TROWS)
            scrolling = True
            scroll_position = position
            frame_cells = tuple(scroll_state.primary_cells)
        else:
            if scrolling:
                sources = np.asarray(
                    scroll_state.primary_cells, np.int64)
                destinations = np.asarray(normal_cells, np.int64)
                display_idx[destinations] = display_idx[sources]
                display_pal[destinations] = display_pal[sources]
                scrolling = False
                scroll_position = 0
                scroll_state = None
            frame_cells = normal_cells
        for cell, palette, key in updates:
            cell = int(cell)
            if not scroll_active_flags[frame]:
                cell = normal_cells[cell]
            indices = np.frombuffer(key, np.uint8)
            if indices.shape != (64,):
                raise SystemExit(
                    f"analysis frame {frame} cell {cell} has an invalid pattern")
            display_idx[cell] = indices
            display_pal[cell] = int(palette)

        category_masks = np.frombuffer(
            CATEGORY_MASK_ROWS[frame], dtype="<u2")
        for name in CATEGORY_MASK_ORDER:
            count = int(np.count_nonzero(
                category_masks & category_bits[name]))
            if count != int(FULL[name][frame]):
                raise SystemExit(
                    f"analysis frame {frame} {name} mask differs from stats")
        if frame not in requested:
            continue

        full_palette = np.zeros((4, 16, 3), np.uint8)
        full_palette[:, 1:] = ACTIVE_FRAME_CRAM[frame]
        selection = np.asarray(frame_cells, np.int64)
        cell_rgb = (
            full_palette[display_pal[selection, None], display_idx[selection]]
            * 36
        ).reshape(C, 8, 8, 3).astype(np.uint8)
        if scrolling:
            # Fine crop of the rolling plane, exactly like the pack decoder.
            plane_rgb = (
                full_palette[display_pal[:, None], display_idx] * 36
            ).reshape(
                scroll_plan.PLANE_ROWS, scroll_plan.PLANE_COLUMNS, 8, 8, 3,
            ).transpose(0, 2, 1, 3, 4).reshape(
                scroll_plan.PLANE_ROWS * 8,
                scroll_plan.PLANE_COLUMNS * 8,
                3,
            ).astype(np.uint8)
            yy = (
                np.arange(H, dtype=np.int64) - int(scroll_state.vscroll)
            ) % plane_rgb.shape[0]
            xx = (
                np.arange(W, dtype=np.int64) - int(scroll_state.hscroll)
            ) % plane_rgb.shape[1]
            preview_image = plane_rgb[yy[:, None], xx[None, :]]
        else:
            preview_image = _cells_to_image(cell_rgb)
        Image.fromarray(preview_image, "RGB").save(
            preview_dir / f"{frame:05d}.png")

        border_names = ("Raw", "Near", "Flbk", "Prg", "Wr0", "Wr1", "Dic")
        if scrolling:
            # Category art in plane space, fine-cropped with the exact same
            # per-pixel offset as the preview, so the category map slides
            # with the real hardware scroll instead of jumping per tile.
            # Same and Scrl draw no border; Miss keeps its black hole.
            plane_masks = np.zeros(plane_cells, np.uint16)
            plane_masks[selection] = category_masks
            plane_rgb_cells = (
                full_palette[display_pal[:, None], display_idx] * 36
            ).reshape(plane_cells, 8, 8, 3).astype(np.float64)
            plane_rgb_cells[
                (plane_masks & category_bits["Miss"]) != 0
            ] = 0
            for name in border_names:
                style.apply_numpy_category_border(
                    plane_rgb_cells,
                    (plane_masks & category_bits[name]) != 0,
                    name,
                )
            plane_art = plane_rgb_cells.clip(0, 255).astype(np.uint8).reshape(
                scroll_plan.PLANE_ROWS, scroll_plan.PLANE_COLUMNS, 8, 8, 3,
            ).transpose(0, 2, 1, 3, 4).reshape(
                scroll_plan.PLANE_ROWS * 8,
                scroll_plan.PLANE_COLUMNS * 8,
                3,
            )
            catmap_image = plane_art[yy[:, None], xx[None, :]]
        else:
            category_rgb = cell_rgb.astype(np.float64)
            category_rgb[
                (category_masks & category_bits["Miss"]) != 0
            ] = 0
            for name in border_names:
                style.apply_numpy_category_border(
                    category_rgb,
                    (category_masks & category_bits[name]) != 0,
                    name,
                )
            catmap_image = _cells_to_image(
                category_rgb.clip(0, 255).astype(np.uint8))
        Image.fromarray(catmap_image, "RGB").save(
            catmap_dir / f"{frame:05d}.png")
    print(
        f"analysis panels: materialized {len(requested)} preview/category frames",
        flush=True,
    )


CAT_TOTALS = {k: int(FULL[k].sum()) for k, _ in style.CATS}

# ---- 有効転送量(新規パターンのCDバイト) + CD1x/コマ + パレット切替フレーム ----
Updated = col("updated")
_cram_write = FRAME_TYPES != 0
if NF > 1:
    _cram_write[1:] |= FRAME_SEG[1:] != FRAME_SEG[:-1]
_cram_write[0] = False
_cram = _cram_write.astype(np.int64) * 128
FB = Raw * 32 + Buf * 32 + Updated * 2 + _cram        # 1コマの映像書込量(パターン+全ネーム+CRAM, タンク供給込み)
# Band is useful BODY.DAT bytes in the physical delivery slot.  It excludes
# Untimed BODY-arm/frame-0 bytes, stream-tail alignment zeros, and rate-match pad.
BODY_USEFUL_BYTES = BODY_PAYLOAD_BYTES + BODY_CONTROL_BYTES
BAND_BPS = stream_schedule.body_delivery_rate_bps(
    BODY_USEFUL_BYTES, BODY_PHYSICAL_BYTES)
BAND = BAND_BPS // 1024
EFF = FB                                              # (互換)
AVG_KBPS = int(round(stream_schedule.average_body_delivery_rate_bps(
    BODY_USEFUL_BYTES, BODY_PHYSICAL_BYTES) / 1024))
SEG_STARTS = {}
for _i, _s in enumerate(FRAME_SEG):
    SEG_STARTS.setdefault(int(_s), _i)               # 各区間の開始フレーム=CRAM切替点


def frame_plinfo(i):
    s = int(FRAME_SEG[i]) if i < len(FRAME_SEG) else 0
    last = len(SEG_PALS) - 1
    def one(sg):
        sg = int(max(0, min(sg, last)))
        return dict(pl=sg, frame=SEG_STARTS.get(sg, 0))
    return {"Prev": one(s - 1) if s > 0 else None, "Current": one(s),
            "Next": one(s + 1) if s < last else None}


# ---- メーター幅(統一廃止=各バーは自分のラベル幅) ----
GAP = 16
REQ_W = L._w(L.f_leg, "Req:000  Miss:000") + 3
COLD_W = L._w(L.f_leg, "Cold:000") + 3
PRE_W = L._w(L.f_leg, "Pre:000") + 3
BAND_W, PRG_W, WRD_W, R2V_W, RUN_W = L.meter_widths(R2V_MAX)
X_TL_STATUS = (
    4 + REQ_W + GAP + COLD_W + GAP + BAND_W + GAP
    + R2V_W + GAP + RUN_W + GAP + PRG_W + GAP + WRD_W + GAP
    + PRE_W + GAP)


def fit(A, bw, bh):
    """表示アスペクトA を box(bw,bh) にレターボックスで収める -> (sw,sh,ox,oy)。"""
    if A >= bw / bh:
        sw, sh = bw, round(bw / A)
    else:
        sh, sw = bh, round(bh * A)
    return sw, sh, (bw - sw) // 2, (bh - sh) // 2


# ---- 静的ベース(枠/見出し/meta/palstate) ----
def build_base():
    cv = Image.new("RGB", (L.CW, L.CH), L.BG)
    d = ImageDraw.Draw(cv)
    L.panel(d, L.MAIN_FRAME)
    base_y = L.MAIN_FRAME[1] - 10
    hx = L.MAIN_FRAME[0] + 2
    d.text((hx, base_y), "SEGA-CD sim output", fill=L.COL_TXT, font=L.f_head, anchor="ls")
    meta = " / ".join([MODE, RES, AUDIO_STR, "%gfps" % round(FPS, 2), "avg %d KiB/sec" % AVG_KBPS])
    d.text((hx + L._w(L.f_head, "SEGA-CD sim output") + 12, base_y), meta,
           fill=L.COL_DIM, font=L.f_meta, anchor="ls")
    L.panel(d, L.SRC_FRAME)          # 見出しは "Source" + ソース諸元(res/fps/音声)を小フォント併記
    _sby = L.SRC_FRAME[1] - 10; _sx = L.SRC_FRAME[0] + 2
    d.text((_sx, _sby), "Source", fill=L.COL_TXT, font=L.f_head, anchor="ls")
    if SRC_SPEC:
        d.text((_sx + L._w(L.f_head, "Source") + 12, _sby), SRC_SPEC, fill=L.COL_DIM, font=L.f_meta, anchor="ls")
    L.panel(d, L.CAT_FRAME)
    L.panel(d, L.WAVE_FRAME)
    L.panel(d, L.SPEC_FRAME)
    _ax = L.WAVE_FRAME[0] + 2; _ay = L.WAVE_FRAME[1] - 4
    d.text((_ax, _ay), "Audio", fill=L.COL_TXT, font=L.f_leg, anchor="ls")
    _sx = _ax + L._w(L.f_leg, "Audio") + L._w(L.f_sm, " ")
    d.text(
        (_sx, _ay), AUDIO_STR,
        fill=L.COL_DIM, font=L.f_sm, anchor="ls")
    _sx = L.SPEC_FRAME[0] + 2
    d.text((_sx, _ay), "Spectrum", fill=L.COL_TXT, font=L.f_leg, anchor="ls")
    d.text(
        (_sx + L._w(L.f_leg, "Spectrum") + L._w(L.f_sm, " "), _ay),
        "40Hz–11kHz", fill=L.COL_DIM, font=L.f_sm, anchor="ls")
    # カテゴリ合計(全編合計=静的)を Category の下へ
    cv.paste(L.draw_cattotals(L.CATTOT_W, L.CATTOT_H, {"cat_totals": CAT_TOTALS}),
             L.CATTOT_XY)
    return cv


# ---- タイムライン背景(全編共通・再生ヘッド無し) ----
def build_tl_bg():
    by = 8; BAR_W = 180; GAP = 16          # 上マージン半減(タイムラインは下端据置=縦に伸びる)
    x_tl = X_TL_STATUS
    tlw = L.STATUS_W - 4 - x_tl
    tlh = (L.STATUS_H - 2) - by
    H_req = tlh // 2
    H_supply = tlh // 4
    H_bottom = tlh - H_req - H_supply
    H_run = H_bottom // 2
    H_band = H_bottom - H_run
    y_run = H_req + H_supply
    y_band = y_run + H_run
    im = Image.new("RGB", (tlw, tlh), (16, 16, 16))
    d = ImageDraw.Draw(im)
    d.rectangle([0, H_req, tlw, H_req + H_supply], fill=(21, 22, 28))
    d.rectangle([0, y_run, tlw, y_band], fill=(27, 24, 17))
    d.rectangle([0, y_band, tlw, tlh], fill=(18, 26, 20))
    order = [
        (name, style.CATEGORY_COLORS[name])
        for name in style.REQ_TIMELINE_CATS
    ]
    for cx in range(tlw):
        fi = min(int(cx / tlw * NF), NF - 1)
        yb = H_req
        for k, c in order:
            seg = int(H_req * FULL[k][fi] / C)
            if seg > 0:
                d.line([(cx, yb - seg), (cx, yb)], fill=c); yb -= seg
        ys = H_req + H_supply
        supply_remaining = {
            name: SUPPLY_REMAINING[name][fi]
            for name in style.METER_SUPPLY_SOURCE_ORDER
        }
        for name, hs in style.meter_supply_segments(
            supply_remaining,
            SUPPLY_CAPACITIES,
            H_supply,
        ):
            if hs > 0:
                d.line(
                    [(cx, ys - hs), (cx, ys)],
                    fill=style.SUPPLY_COLORS[name],
                )
                ys -= hs
        run_capacity = max(COLD_CAP, 1)
        hr = int(H_run * min(int(DMA_RUNS[fi]), run_capacity) / run_capacity)
        if hr > 0:
            d.line([(cx, y_band - hr), (cx, y_band)], fill=style.COL_RUN)
        physical = max(int(BODY_PHYSICAL_BYTES[fi]), 1)
        hrw = int(H_band * int(BODY_RAW_PAYLOAD_BYTES[fi]) / physical)
        hprg = int(H_band * int(BODY_PAYLOAD_BYTES[fi]) / physical)
        if hrw > 0:
            d.line([(cx, tlh - hrw), (cx, tlh)], fill=style.CAT_RAW)
        if hprg > hrw:
            d.line(
                [(cx, tlh - hprg), (cx, tlh - hrw)],
                fill=style.COL_PRG,
            )
        hc = int(H_band * int(BODY_USEFUL_BYTES[fi]) / physical)
        if hc > hprg:
            d.line(
                [(cx, tlh - hc), (cx, tlh - hprg)],
                fill=style.COL_OVH,
            )
    d.line([(0, y_run), (tlw - 1, y_run)], fill=(110, 105, 70))
    d.line([(0, y_band), (tlw - 1, y_band)], fill=(110, 105, 70))
    d.rectangle([0, 0, tlw - 1, tlh - 1], outline=L.COL_FRAME_IN)
    return im, x_tl, by, tlw, tlh


BASE = build_base()
TL_BG, X_TL, BY, TLW, TLH = build_tl_bg()


def draw_status_real(data):
    im = Image.new("RGB", (L.STATUS_W, L.STATUS_H), (16, 16, 16))
    d = ImageDraw.Draw(im)
    by, BH = 8, 16
    ly = by + BH + 3
    x = 4
    cn = data["counts"]
    r2v_max = max(1, int(data["r2v_max"]))
    r2v_val = int(data["r2v_words"])

    def stacked(segs, full, bw):
        px = x
        for val, c in segs:
            seg = int(bw * min(val, full) / full)
            seg = min(seg, x + bw - px)              # 積み上げ合計が枠幅を超えない(はみ出し防止)
            if seg > 0:
                d.rectangle([px, by, px + seg, by + BH], fill=c); px += seg
        d.rectangle([x, by, x + bw, by + BH], outline=L.COL_FRAME_IN)

    # 1) Req + Miss headline values.
    stacked([
        (cn[name], style.CATEGORY_COLORS[name])
        for name, _ in style.CATS
    ], C, REQ_W)
    bx = x + int(REQ_W * data["budget"] / C)
    d.line([bx, by - 2, bx, by + BH + 2], fill=style.COL_LIMIT)
    xq = L.draw_field(d, x, ly, "Req:", data["req"], 3, L.f_leg, L.COL_TXT)
    L.draw_field(d, xq + 8, ly, "Miss:", data["miss"], 3, L.f_leg, L.COL_TXT)
    x += REQ_W + GAP
    # 2) Cold = same-frame exact loads by source + future prefetch.
    cold_parts = [(cn["Raw"], style.CAT_RAW)]
    cold_parts += [
        (cn[name], style.SUPPLY_COLORS[name])
        for name in style.DISPLAY_SOURCE_ORDER
    ]
    cold_parts.append((data["cold_prefetch"], style.CAT_PREFETCH))
    stacked(cold_parts, data["cold_cap"], COLD_W)
    L.draw_field(d, x, ly, "Cold:", data["cold"], 3, L.f_leg, L.COL_TXT)
    x += COLD_W + GAP
    # 3) Band = Raw payload + Prg charge + control; no pad/Header.
    stacked([(data["body_raw_payload_bytes"], style.CAT_RAW),
             (data["body_prg_payload_bytes"], style.COL_PRG),
             (data["body_control_bytes"], style.COL_OVH)],
            max(data["body_physical_bytes"], 1), BAND_W)
    d.line(
        [x + BAND_W, by - 2, x + BAND_W, by + BH + 2],
        fill=style.COL_BAND_LIMIT,
    )
    L.draw_field(d, x, ly, "Band:", data["band_kbps"], 3, L.f_leg, L.COL_TXT)
    x += BAND_W + GAP
    # 4) R2V = pattern + DMA repair + name-table/HUD + palette words.
    fillw = int(R2V_W * min(r2v_val, r2v_max) / r2v_max)
    over = r2v_val > r2v_max
    d.rectangle(
        [x, by, x + fillw, by + BH],
        fill=style.COL_OVER if over else style.COL_DMA,
    )
    if over:
        d.rectangle(
            [x + fillw, by, x + R2V_W, by + BH],
            fill=style.COL_OVER_REMAINDER,
        )
    d.rectangle([x, by, x + R2V_W, by + BH], outline=L.COL_FRAME_IN)
    L.draw_field(
        d, x, ly, "R2V:", r2v_val, L.r2v_value_digits(r2v_max),
        L.f_leg, L.COL_TXT,
    )
    x += R2V_W + GAP

    # 5) Run = playerのcold-run record数。フル=1tile/runの理論最悪ケース。
    run_val = int(data["dma_runs"])
    run_max = L.dma_run_worst_case(data["dma_tiles"])
    run_fill = (max(1, int(RUN_W * min(run_val, run_max) / run_max))
                if run_val > 0 and run_max > 0 else 0)
    d.rectangle([x, by, x + run_fill, by + BH],
                fill=style.CAT_MISS if run_val > run_max else style.COL_RUN)
    d.rectangle([x, by, x + RUN_W, by + BH], outline=L.COL_FRAME_IN)
    L.draw_field(d, x, ly, "Run:", run_val, L.DMA_RUN_DIGITS, L.f_leg, L.COL_TXT)
    x += RUN_W + GAP

    # 6) Prg remains physical; WordBuf banks are combined only for display.
    prg_remaining = data["supply_remaining"]["Prg"]
    prg_capacity = data["supply_capacities"]["Prg"]
    stacked([(prg_remaining, style.COL_PRG)], prg_capacity, PRG_W)
    L.draw_field(d, x, ly, "Prg:", prg_remaining, 5, L.f_leg, L.COL_TXT)
    x += PRG_W + GAP

    wrd_remaining = (
        data["supply_remaining"]["Wr0"] + data["supply_remaining"]["Wr1"])
    wrd_capacity = (
        data["supply_capacities"]["Wr0"] + data["supply_capacities"]["Wr1"])
    stacked([(wrd_remaining, style.COL_WRD)], wrd_capacity, WRD_W)
    L.draw_field(d, x, ly, "Wrd:", wrd_remaining, 4, L.f_leg, L.COL_TXT)
    x += WRD_W + GAP

    # 7) Prefetch activity is shown last.
    stacked([(data["cold_prefetch"], style.CAT_PREFETCH)],
            data["prefetch_cap"], PRE_W)
    L.draw_field(d, x, ly, "Pre:", data["cold_prefetch"], 3, L.f_leg, L.COL_TXT)
    x += PRE_W + GAP
    # メーター下: パレット Prev/Current/Next(PL/Frame見出し, 正方形タイル)
    meters_right = x - GAP
    py0 = ly + 16
    L.draw_palettes_strip(d, 4, py0, meters_right - 4, (L.STATUS_H - 2) - py0,
                          data["palettes"], data.get("pl_info"))
    im.paste(TL_BG, (X_TL, BY))
    head = X_TL + int(TLW * data["frame"] / NF)
    ImageDraw.Draw(im).line([head, BY, head, BY + TLH], fill=(255, 255, 255))
    return im


def catmap_panel(i, sw, sh):
    """catmap を(sw,sh)へ拡大 → Missセル(miss_masks)を『赤で塗りつぶし』で上書き。
    scroll活性フレームは進入エッジのstrip枠+行進chevronを重ねる。"""
    cm = Image.open(f"{SIM}/catmap/{i:05d}.png").convert("RGB").resize((sw, sh), Image.NEAREST)
    d = ImageDraw.Draw(cm)
    bits = np.unpackbits(MISS_MASKS[i])[:C]
    if bits.any():
        for cell in np.where(bits)[0]:
            r, c = int(cell) // TCOLS, int(cell) % TCOLS
            x0 = round(c * sw / TCOLS); y0 = round(r * sh / TROWS)
            x1 = round((c + 1) * sw / TCOLS) - 1; y1 = round((r + 1) * sh / TROWS) - 1
            d.rectangle(
                [x0, y0, x1, y1],
                fill=style.CAT_MISS,
            )
    L.draw_scroll_edge(d, sw, sh, frame_scroll(i), TCOLS, TROWS)
    return cm


def frame_data(i):
    cn = {k: int(FULL[k][i]) for k in FULL}
    # Frame 0 is an untimed boot construction. Keep its Raw/Same display
    # classification, but do not present boot work as timed codec load.
    displayed_cold = (
        cn["Raw"]
        + sum(cn[name] for name in style.DISPLAY_SOURCE_ORDER)
        + int(PREFETCH[i])
    )
    return dict(C=C, counts=cn, fps=FPS, win=WIN,
                mode=MODE, res=RES, audio=AUDIO_STR, avg_kbps=AVG_KBPS,
                req=int(Want[i]), miss=cn["Miss"], budget=BUDGET,
                comp=cn["Same"] + cn["Near"] + cn["Flbk"],
                supply_capacities=SUPPLY_CAPACITIES,
                supply_remaining={
                    name: int(values[i])
                    for name, values in SUPPLY_REMAINING.items()
                },
                dma_tiles=L.timed_metric_value(i, DMA_TILES[i]),
                dma_runs=L.timed_metric_value(i, DMA_RUNS[i]),
                r2v_words=L.timed_metric_value(i, R2V_WORDS[i]),
                r2v_max=R2V_MAX,
                body_raw_payload_bytes=L.timed_metric_value(
                    i, BODY_RAW_PAYLOAD_BYTES[i]),
                body_prg_payload_bytes=L.timed_metric_value(
                    i, BODY_PRG_PAYLOAD_BYTES[i]),
                body_payload_bytes=L.timed_metric_value(
                    i, BODY_PAYLOAD_BYTES[i]),
                body_control_bytes=L.timed_metric_value(
                    i, BODY_CONTROL_BYTES[i]),
                body_physical_bytes=L.timed_metric_value(
                    i, BODY_PHYSICAL_BYTES[i]),
                band_kbps=L.timed_metric_value(i, BAND[i]),
                cold=L.timed_metric_value(i, displayed_cold),
                cold_prefetch=L.timed_metric_value(i, PREFETCH[i]),
                prefetch_cap=PREFETCH_CAP,
                cold_cap=COLD_CAP,
                scroll=frame_scroll(i),
                pl_info=frame_plinfo(i),
                frame=i, total_frames=NF, time_s=i / FPS, palettes=frame_palettes(i),
                series={k: [int(FULL[k][min(max(j, 0), NF - 1)]) for j in range(i - HALF, i + HALF + 1)]
                        for k in FULL})


ANALYSIS_TSV_COLUMNS = (
    "schema_version", "frame", "frame_hex", "time_seconds",
    "palette_segment", "cells", "active_tiles", "budget_tiles",
    "cold_cap_tiles", "prefetch_cap_tiles",
    "legend_raw", "legend_same", "legend_dic", "legend_prg",
    "legend_wr", "legend_wr0", "legend_wr1", "legend_near",
    "legend_flbk", "legend_miss", "legend_scrl",
    "status_req", "status_miss", "status_cold", "status_pre",
    "status_band_kib_s", "status_prg", "status_wr0", "status_wr1",
    "status_r2v", "status_dma", "status_run",
    "r2v_pattern_words", "r2v_repair_words",
    "r2v_name_table_words", "r2v_cram_words", "r2v_short_runs",
    "body_raw_payload_bytes", "body_prg_payload_bytes",
    "body_payload_bytes", "body_control_bytes", "body_pad_bytes",
    "body_physical_bytes", "body_useful_bytes", "body_band_bps",
    "quality_budget_remaining_bytes",
    "scroll_active", "scroll_hscroll", "scroll_vscroll",
) + tuple(f"stat_{name}" for name in STAT_COLUMNS)


def _tsv_number(value):
    """Return a stable built-in scalar for csv without losing float values."""
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float):
        if np.isfinite(value) and value.is_integer():
            return int(value)
        return format(value, ".17g")
    return value


def analysis_tsv_row(i):
    """Build one row from the exact data used by the overlay for frame i."""
    data = frame_data(i)
    cn = data["counts"]
    row = {
        "schema_version": 9,
        "frame": i,
        "frame_hex": f"0x{i:04X}",
        "time_seconds": format(i / FPS, ".9f"),
        "palette_segment": int(FRAME_SEG[i]),
        "cells": C,
        "active_tiles": ACTIVE_TILES,
        "budget_tiles": BUDGET,
        "cold_cap_tiles": COLD_CAP,
        "prefetch_cap_tiles": PREFETCH_CAP,
        "legend_raw": cn["Raw"],
        "legend_same": cn["Same"],
        "legend_dic": cn["Dic"],
        "legend_prg": cn["Prg"],
        "legend_wr": cn["Wr0"] + cn["Wr1"],
        "legend_wr0": cn["Wr0"],
        "legend_wr1": cn["Wr1"],
        "legend_near": cn["Near"],
        "legend_flbk": cn["Flbk"],
        "legend_miss": cn["Miss"],
        "legend_scrl": cn["Scrl"],
        "status_req": data["req"],
        "status_miss": data["miss"],
        "status_cold": data["cold"],
        "status_pre": data["cold_prefetch"],
        "status_band_kib_s": data["band_kbps"],
        "status_prg": data["supply_remaining"]["Prg"],
        "status_wr0": data["supply_remaining"]["Wr0"],
        "status_wr1": data["supply_remaining"]["Wr1"],
        "status_r2v": data["r2v_words"],
        "status_dma": data["dma_tiles"],
        "status_run": data["dma_runs"],
        "r2v_pattern_words": int(R2V_PATTERN_WORDS[i]),
        "r2v_repair_words": int(R2V_REPAIR_WORDS[i]),
        "r2v_name_table_words": int(R2V_NAME_TABLE_WORDS[i]),
        "r2v_cram_words": int(R2V_CRAM_WORDS[i]),
        "r2v_short_runs": int(R2V_SHORT_RUNS[i]),
        "body_raw_payload_bytes": int(BODY_RAW_PAYLOAD_BYTES[i]),
        "body_prg_payload_bytes": int(BODY_PRG_PAYLOAD_BYTES[i]),
        "body_payload_bytes": int(BODY_PAYLOAD_BYTES[i]),
        "body_control_bytes": int(BODY_CONTROL_BYTES[i]),
        "body_pad_bytes": int(BODY_PAD_BYTES[i]),
        "body_physical_bytes": int(BODY_PHYSICAL_BYTES[i]),
        "body_useful_bytes": int(BODY_USEFUL_BYTES[i]),
        "body_band_bps": int(BAND_BPS[i]),
        "quality_budget_remaining_bytes": int(QUALITY_REM[i]),
        "scroll_active": int(bool(SCROLL_ACTIVE[i])),
        "scroll_hscroll": int(SCROLL_POSITIONS[i, 0]),
        "scroll_vscroll": int(SCROLL_POSITIONS[i, 1]),
    }
    row.update({
        f"stat_{name}": _tsv_number(S[i, idx[name]])
        for name in STAT_COLUMNS
    })
    return row


def write_analysis_tsv():
    """Write one permanent TSV directly under logs/ or an explicit path."""
    path = (
        OUT_TSV
        if OUT_TSV is not None
        else analysis_logs.unique_tsv_path(CONFIG_PROFILE, kind="timeline")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=ANALYSIS_TSV_COLUMNS, delimiter="\t",
            lineterminator="\n", extrasaction="raise")
        writer.writeheader()
        for i in range(NF):
            writer.writerow(analysis_tsv_row(i))
    tmp.replace(path)
    return path


def draw_waveform_real(output_frame):
    """Draw samples owned by one exact 60 fps analysis-video frame."""
    bw, bh = WAVE_BW, L.WAVE_FRAME[3] - L.WAVE_FRAME[1] - 2
    im = Image.new("RGB", (bw, bh), (16, 16, 16))
    d = ImageDraw.Draw(im)
    mid = bh // 2
    d.line([(0, mid), (bw - 1, mid)], fill=(60, 60, 66))
    start, stop = analysis_audio.frame_sample_bounds(
        output_frame,
        fps=ANALYSIS_VIDEO_FPS,
        sample_rate=AUDIO_RATE,
        total_samples=len(AUDIO_SAMPLES),
    )
    minima, maxima = analysis_audio.waveform_extrema(
        AUDIO_SAMPLES, start=start, stop=stop, columns=bw)
    scale = bh * 0.46 / AUDIO_FULL_SCALE
    prev_top = prev_bottom = None
    for x in range(bw):
        top = mid - round(int(maxima[x]) * scale)
        bottom = mid - round(int(minima[x]) * scale)
        # Bridge a vertical gap to the previous column so the trace stays
        # continuous; the column's own extrema still bound the next bridge.
        draw_top, draw_bottom = top, bottom
        if prev_bottom is not None:
            if draw_top > prev_bottom:
                draw_top = prev_bottom + 1
            elif draw_bottom < prev_top:
                draw_bottom = prev_top - 1
        d.line(
            [(x, draw_top), (x, draw_bottom)],
            fill=L.AUDIO_TRACE_COLOR,
        )
        prev_top, prev_bottom = top, bottom
    return im


def draw_spectrum_real(output_frame):
    """Draw a 24-band FFT around one 60 fps analysis-video frame."""
    bw, bh = SPEC_BW, L.SPEC_FRAME[3] - L.SPEC_FRAME[1] - 2
    im = Image.new("RGB", (bw, bh), (16, 16, 16))
    d = ImageDraw.Draw(im)
    baseline = bh - 2
    d.line([(0, baseline), (bw - 1, baseline)], fill=(60, 60, 66))
    center_sample = round(
        (output_frame / ANALYSIS_VIDEO_FPS + WAVE_WIN_S / 2.0)
        * AUDIO_RATE)
    levels = analysis_audio.spectrum_levels(
        AUDIO_SAMPLES,
        sample_rate=AUDIO_RATE,
        center_sample=center_sample,
        full_scale=AUDIO_FULL_SCALE,
        fft_size=L.SPECTRUM_FFT_SIZE,
        min_hz=L.SPECTRUM_MIN_HZ,
        max_hz=L.SPECTRUM_MAX_HZ,
        bands=L.SPECTRUM_BANDS,
    )
    slot = bw / L.SPECTRUM_BANDS
    for band, level in enumerate(levels):
        left = round(band * slot) + 1
        right = max(left, round((band + 1) * slot) - 2)
        top = baseline - round(float(level) * (bh - 5))
        if top < baseline:
            d.rectangle(
                [(left, top), (right, baseline - 1)],
                fill=L.AUDIO_TRACE_COLOR,
            )
    return im


def draw_audio_overlay(output_frame):
    """Write the waveform+spectrum interiors for one analysis-video frame."""
    overlay = Image.new(
        "RGBA", (AUDIO_OVERLAY_W, AUDIO_OVERLAY_H), (0, 0, 0, 0))
    overlay.paste(draw_waveform_real(output_frame), (0, 0))
    spectrum_x = L.SPEC_FRAME[0] + 1 - AUDIO_OVERLAY_X
    overlay.paste(draw_spectrum_real(output_frame), (spectrum_x, 0))
    overlay.save(f"{AUDIO_FRAMES_DIR}/{output_frame:06d}.png")
    return output_frame


def render(i):
    data = frame_data(i)
    cv = BASE.copy()
    # メイン(SEGA-CD出力): 実機同様、画面いっぱいに拡大せず 実機画面(4:3)へ中央配置。
    mv = Image.open(f"{SIM}/preview/{i:05d}.png").convert("RGB")
    bw = L.MAIN_FRAME[2] - L.MAIN_FRAME[0] - 2 * L.PAD; bh = L.MAIN_FRAME[3] - L.MAIN_FRAME[1] - 2 * L.PAD
    Fw, Fh, ox, oy = fit(SCREEN_A, bw, bh)         # 4:3の実機画面をパネルへ
    scr = Image.new("RGB", (Fw, Fh), (0, 0, 0))
    cw = round(Fw * W / SCREEN_W); ch = round(Fh * H / SCREEN_H)   # 画面内のコンテンツ画素
    cx = round(Fw * ((SCREEN_W - W) // 2) / SCREEN_W); cy = round(Fh * ((SCREEN_H - H) // 2) / SCREEN_H)
    scr.paste(mv.resize((cw, ch), Image.LANCZOS), (cx, cy))         # 中央配置(周囲は黒縁)
    cv.paste(scr, (L.MAIN_FRAME[0] + L.PAD + ox, L.MAIN_FRAME[1] + L.PAD + oy))
    # Source(raw は 1始点)
    sv = Image.open(f"{SIM}/raw/{i + 1:05d}.png").convert("RGB")
    bw = L.SRC_FRAME[2] - L.SRC_FRAME[0] - 2 * L.PAD; bh = L.SRC_FRAME[3] - L.SRC_FRAME[1] - 2 * L.PAD
    source_geometry = L.source_panel_geometry(
        RW, RH, SOURCE_CANVAS_W, SOURCE_CANVAS_H,
        SOURCE_SAR_NUM, SOURCE_SAR_DEN, bw, bh)
    sw, sh = source_geometry["panel_size"]
    ox, oy = source_geometry["panel_offset"]
    cw, ch = source_geometry["content_size"]
    cx, cy = source_geometry["content_offset"]
    source_canvas = Image.new("RGB", (sw, sh), (0, 0, 0))
    source_canvas.paste(sv.resize((cw, ch), Image.LANCZOS), (cx, cy))
    cv.paste(
        source_canvas,
        (L.SRC_FRAME[0] + L.PAD + ox, L.SRC_FRAME[1] + L.PAD + oy))
    # Category(Miss=中身なし赤枠)
    bw = L.CAT_FRAME[2] - L.CAT_FRAME[0] - 2 * L.PAD; bh = L.CAT_FRAME[3] - L.CAT_FRAME[1] - 2 * L.PAD
    sw, sh, ox, oy = fit(A_CONTENT, bw, bh)
    cv.paste(catmap_panel(i, sw, sh), (L.CAT_FRAME[0] + L.PAD + ox, L.CAT_FRAME[1] + L.PAD + oy))
    d = ImageDraw.Draw(cv)
    # Time/Frame(右上・小15px・ベースライン揃え)
    base_y = L.MAIN_FRAME[1] - 10
    _plt = len(SEG_PALS) - 1                        # 総数(最大パレット番号)
    _plw = max(2, len(str(_plt)))
    lab_t = "PL:%0*d/%0*d Time:%02d:%05.2f Frame:" % (_plw, int(FRAME_SEG[i]), _plw, _plt,
                                                      int(data["time_s"] // 60), data["time_s"] % 60)
    fhex = "%04X" % i                              # F番号=実機HUDと同じ16進4桁
    tw = L._w(L.f_leg, lab_t) + L._w(L.f_leg, fhex)
    tx = L.MAIN_FRAME[2] - tw; ty = base_y - L.f_leg.getmetrics()[0]
    d.text((tx, ty), lab_t, fill=L.COL_TXT, font=L.f_leg)
    d.text((tx + L._w(L.f_leg, lab_t), ty), fhex, fill=L.COL_TXT, font=L.f_leg)
    # 凡例リスト(Categoryの上) / audio panels(右下) / status
    cv.paste(L.draw_legend(L.CATLEG_W, L.CATLEG_H, data), L.CATLEG_XY)
    output_frame = analysis_audio.output_frame_at_content_frame(
        i, content_fps=FPS, output_fps=ANALYSIS_VIDEO_FPS)
    cv.paste(
        draw_waveform_real(output_frame),
        (L.WAVE_FRAME[0] + 1, L.WAVE_FRAME[1] + 1))
    cv.paste(
        draw_spectrum_real(output_frame),
        (L.SPEC_FRAME[0] + 1, L.SPEC_FRAME[1] + 1))
    cv.paste(draw_status_real(data), L.STATUS_XY)
    cv.save(f"{FRAMES_DIR}/{i:05d}.png")
    return i


def mux(output: Path):
    audio = str(AUDIO_PATH)
    vcodec = ["-c:v", "h264_nvenc", "-preset", "p6", "-tune", "hq", "-rc", "vbr",
              "-cq", CQ, "-b:v", "0"]
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(FPS), "-start_number", "0",
           "-i", f"{FRAMES_DIR}/%05d.png",
           "-framerate", str(ANALYSIS_VIDEO_FPS), "-start_number", "0",
           "-i", f"{AUDIO_FRAMES_DIR}/%06d.png"]
    if Path(audio).exists():
        cmd += ["-i", audio]
    filter_graph = (
        f"[0:v]fps={ANALYSIS_VIDEO_FPS}[base];"
        f"[base][1:v]overlay={AUDIO_OVERLAY_X}:{AUDIO_OVERLAY_Y}:"
        "shortest=1[v]")
    cmd += ["-filter_complex", filter_graph, "-map", "[v]"]
    if Path(audio).exists():
        cmd += ["-map", "2:a:0"]
    cmd += vcodec + ["-pix_fmt", "yuv420p"]
    if Path(audio).exists():
        cmd += ["-c:a", "aac", "-ar", "22050", "-b:a", "96k", "-shortest"]  # 音声の標本化を保つ(ADPCM 22kHz対応)
    cmd += ["-fps_mode", "cfr", str(output)]
    subprocess.run(cmd, check=True)


def main():
    from multiprocessing import get_context
    arguments = sys.argv[1:]
    tsv_only = arguments == ["--tsv-only"]
    rng = None
    if not tsv_only and len(arguments) == 2:
        try:
            rng = list(range(int(arguments[0]), int(arguments[1])))
        except ValueError as exc:
            raise SystemExit(
                "analysis arguments must be --tsv-only or integer frame A B"
            ) from exc
    elif not tsv_only and arguments:
        raise SystemExit(
            "analysis arguments must be --tsv-only or integer frame A B")
    frames = rng if rng is not None else list(range(NF))
    if tsv_only:
        sim_lease = tmpfs_workspace.lease_managed_path(Path(SIM))
        try:
            print(f"analysis data -> {write_analysis_tsv()}", flush=True)
        finally:
            if sim_lease is not None:
                sim_lease.release()
        return
    # A rendered 1080p PNG is commonly around 2 MiB. Leave room for PNGs,
    # the muxed video, and normal compression variance before workers start.
    required = (
        len(frames) * (5 * 1024 ** 2 // 2)
        + (AUDIO_OUTPUT_FRAMES * 64 * 1024 if rng is None else 0)
        + 1024 ** 3
    )
    sim_lease = tmpfs_workspace.lease_managed_path(
        Path(SIM), required_bytes=required)
    mp4_lease = None
    mp4_actual = None
    try:
        if rng is None:
            mp4_actual, mp4_lease = tmpfs_workspace.allocate_file(
                OUT_MP4,
                kind="analysis-mp4",
                key=(f"{CONFIG_PROFILE.path.stem}-"
                     f"{CONFIG_PROFILE.sha256[:10]}"),
                required_bytes=512 * 1024 ** 2,
            )
        os.makedirs(FRAMES_DIR, exist_ok=True)
        if rng is None:
            os.makedirs(AUDIO_FRAMES_DIR, exist_ok=True)
        nw = resource_tokens.requested_cpu_workers(limit=len(frames))
        print(f"Analysis: waiting for {nw} CPU token(s) ...", flush=True)
        with resource_tokens.acquire_tokens("cpu", count=nw):
            materialize_analysis_panels(frames)
            print(f"analysis data -> {write_analysis_tsv()}", flush=True)
            print(
                f"render {len(frames)} frames @ {W}x{H} "
                f"({TCOLS}x{TROWS}) fps={FPS} -> {FRAMES_DIR}",
                flush=True,
            )
            # Python 3.14 changed POSIX's default from fork to forkserver. This
            # renderer loads large read-only tables first so Linux fork can
            # share those pages.
            mp = (
                get_context("fork")
                if sys.platform.startswith("linux") else get_context()
            )
            with mp.Pool(nw) as pool:
                for k, _ in enumerate(
                        pool.imap_unordered(render, frames, chunksize=8)):
                    if k % 300 == 0:
                        print(f"  {k}/{len(frames)}", flush=True)
                if rng is None:
                    print(
                        f"render {AUDIO_OUTPUT_FRAMES} audio panels "
                        f"@ {ANALYSIS_VIDEO_FPS}fps -> {AUDIO_FRAMES_DIR}",
                        flush=True,
                    )
                    for k, _ in enumerate(pool.imap_unordered(
                            draw_audio_overlay,
                            range(AUDIO_OUTPUT_FRAMES),
                            chunksize=32)):
                        if k % 1200 == 0:
                            print(
                                f"  audio {k}/{AUDIO_OUTPUT_FRAMES}",
                                flush=True)
        if rng is None:
            print(f"mux -> {OUT_MP4} (tmpfs {mp4_actual})", flush=True)
            print("Analysis mux: waiting for 1 GPU token ...", flush=True)
            with resource_tokens.acquire_tokens("gpu"):
                mux(mp4_actual)
            print("done", mp4_actual, flush=True)
        else:
            print("done (frames only)", len(frames), flush=True)
    finally:
        if mp4_lease is not None:
            mp4_lease.release()
        if sim_lease is not None:
            sim_lease.release()


if __name__ == "__main__":
    try:
        _stem_lease = resource_tokens.acquire_stem(CONFIG_PROFILE.sim_stem)
    except resource_tokens.ResourceBusyError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(75) from exc
    try:
        main()
    finally:
        _stem_lease.release()
