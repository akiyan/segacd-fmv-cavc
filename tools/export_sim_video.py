#!/usr/bin/env python3
"""sim の素の出力(映像+音声)を『ストレートに』mp4 化する。解析オーバーレイ無し。

render_analysis.pyは解析時にpreview/（オーバーレイ無しの復号フレーム）をdecisionから
生成する。本ツールはそのpreview/を実機画面(モード別サイズ)へ
中央配置し、表示アスペクト(PAR)を適用して、sim 音声を多重化した素の mp4 を書き出す。
= エミュ録画の「理想版」(ハード再生アーティファクトもデバッグHUDも無い Encoder ideal output)。

ffmpeg の pad+scale だけで完結(PILループ不要=速い)。

env:
  CBRSIM_OUT      profileのsim要求名。cbr_pathsがtmpfs実体pathへ解決する。
                  解析工程が生成したpreview/とstats.npz指定音声を使う
  STRAIGHT_OUT    tmpfs artifactに使う要求mp4名
  STRAIGHT_SCALE  整数拡大率 (既定 4)

usage: python3 tools/export_sim_video.py
"""
import os
import sys
import glob
import subprocess
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import layout_preview as L
import tmpfs_workspace
from cbr_paths import artifact_path, sim_work_dir

SIM = str(sim_work_dir())
SCALE = int(os.environ.get("STRAIGHT_SCALE", "4"))
OUT = Path(os.environ.get(
    "STRAIGHT_OUT", str(artifact_path("sim", sim_dir=SIM))))


def main():
    sim_lease = tmpfs_workspace.lease_managed_path(Path(SIM))
    actual_out = None
    out_lease = None
    try:
        actual_out, out_lease = tmpfs_workspace.allocate_file(
            OUT,
            kind="straight-sim-mp4",
            required_bytes=512 * 1024 ** 2,
        )
        _export(actual_out)
        print("done", actual_out, flush=True)
    finally:
        if out_lease is not None:
            out_lease.release()
        if sim_lease is not None:
            sim_lease.release()


def _export(actual_out: Path):
    z = np.load(f"{SIM}/stats.npz", allow_pickle=True)
    fps = int(z["fps"])
    pv = sorted(glob.glob(f"{SIM}/preview/*.png"))
    if not pv:
        raise SystemExit(
            "preview PNGs are missing; run tools/render_analysis.py first")
    if not pv:
        sys.exit("no preview frames in %s/preview" % SIM)
    W, H = Image.open(pv[0]).size                       # コンテンツ画素(タイルグリッド)
    SW, SH = max(L.SCREEN_W, W), max(L.SCREEN_H, H)     # 実機画面サイズ(コンテンツを中央配置)
    par = L.PAR                                         # 1ドット横長比(表示アスペクト補正)
    padx, pady = (SW - W) // 2, (SH - H) // 2
    outw = 2 * round(SW * SCALE * par / 2)              # 表示アスペクトを焼く(偶数化=yuv420p)
    outh = 2 * round(SH * SCALE / 2)

    if "audio_playback_file" in z:
        audio = Path(SIM) / str(z["audio_playback_file"])
        if not audio.is_file():
            sys.exit("stats.npz playback audio is missing: %s" % audio)
    else:
        legacy_audio = sorted(glob.glob(f"{SIM}/audio_*.wav"))
        audio = Path(legacy_audio[0]) if len(legacy_audio) == 1 else None
    start = int(Path(pv[0]).stem)                       # 先頭フレーム番号(通常0)
    vf = "pad=%d:%d:%d:%d,scale=%d:%d:flags=neighbor" % (SW, SH, padx, pady, outw, outh)
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-framerate", str(fps), "-start_number", str(start),
           "-i", "%s/preview/%%05d.png" % SIM]
    if audio is not None and audio.exists():
        cmd += ["-i", str(audio)]
    cmd += ["-vf", vf, "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-r", str(fps)]
    if audio is not None and audio.exists():
        cmd += ["-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += [str(actual_out)]
    print("straight sim -> %s  (%dx%d @ %dfps, mode=%s, content=%dx%d screen=%dx%d)"
          % (OUT, outw, outh, fps, L.MODE_NAME, W, H, SW, SH), flush=True)
    subprocess.run(cmd, check=True)


if __name__ == "__main__":
    main()
