#!/usr/bin/env bash
# Capture Sega CD playback with the akiyan/blastem fork in native FFV1/FLAC.
#
# Usage:
#   tools/record_movie.sh --config profiles/PROFILE.toml --seconds 160
#   tools/record_movie.sh --disc out/PROFILE.cue --no-build --seconds 160
#
# Options:
#   --config TOML         Build and boot the profile's disc.
#   --disc CUE            Use an explicit disc.
#   --seconds N          Length of the bounded capture (default: 160).
#   --tag NAME           Output prefix (default: rec_<disc basename>).
#   --trim SEC           Drop SEC seconds from the beginning (default: 0).
#   --auto-audio-trim    Find a window from the recorded audio.
#   --input-script FILE  Override the bundled frame-indexed START input.
#   --vdp-event-log      Retain the VDP event stream for this run.
#   --preview            Also produce a lossy H.264/AAC preview.
#   --out NAME           Preview filename (default: <tag>_preview.mp4).
#   --no-build           Boot an existing disc.
#   --release-build      Build the HUD-free disc.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PYTHON="${PYTHON:-$ROOT/tools/python.sh}"
export PYTHON
ORIGINAL_ARGS=("$@")

CONFIG=""
DISC=""
OUT=""
REC_SECS=160
TRIM=0
TAG=""
BUILD=1
BUILD_DEBUG=1
AUTO_AUDIO_TRIM=0
PREVIEW=0
INPUT_SCRIPT="$ROOT/tools/blastem_start.txt"
VDP_EVENT_LOG=0
BIOS_REGION="${BIOS_REGION:-jp}"
export BIOS_REGION

while [ $# -gt 0 ]; do
  case "$1" in
    --config) CONFIG="$2"; shift 2;;
    --disc) DISC="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --preview) PREVIEW=1; shift;;
    --seconds) REC_SECS="$2"; shift 2;;
    --trim) TRIM="$2"; AUTO_AUDIO_TRIM=0; shift 2;;
    --tag) TAG="$2"; shift 2;;
    --backend)
      [ "${2:-}" = "blastem" ] || { echo "record_movie.sh uses the akiyan/blastem fork" >&2; exit 2; }
      shift 2;;
    --input-script) INPUT_SCRIPT="$2"; shift 2;;
    --vdp-event-log) VDP_EVENT_LOG=1; shift;;
    --record-size)
      [ "${2:-}" = "320x224" ] || { echo "BlastEm capture uses native 320x224" >&2; exit 2; }
      shift 2;;
    --auto-audio-trim) AUTO_AUDIO_TRIM=1; shift;;
    --no-build) BUILD=0; shift;;
    --release-build) BUILD_DEBUG=0; shift;;
    -h|--help) sed -n '2,/^set -euo pipefail/p' "$0" | sed '$d'; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

case "$BIOS_REGION" in
  jp) REGION_SUFFIX="";;
  us) REGION_SUFFIX="_us";;
  *) echo "BIOS_REGION must be jp or us" >&2; exit 2;;
esac
[ -f "$INPUT_SCRIPT" ] || { echo "input script not found: $INPUT_SCRIPT" >&2; exit 2; }

if [ -n "$CONFIG" ]; then
  CONFIG_STEM="$("$PYTHON" tools/encode_config.py "$CONFIG" --print-stem)"
  # A release build writes out/<stem>_release.cue; DEBUG keeps out/<stem>.cue.
  if [ "$BUILD_DEBUG" -eq 1 ]; then
    CONFIG_DISC="out/${CONFIG_STEM}${REGION_SUFFIX}.cue"
  else
    CONFIG_DISC="out/${CONFIG_STEM}${REGION_SUFFIX}_release.cue"
  fi
  if [ -z "$DISC" ]; then
    DISC="$CONFIG_DISC"
  elif [ "$BUILD" -eq 1 ] && [ "$DISC" != "$CONFIG_DISC" ]; then
    echo "--disc $DISC does not match --config output $CONFIG_DISC" >&2
    exit 2
  fi
fi
if [ "$BUILD" -eq 1 ] && [ -z "$CONFIG" ]; then
  echo "--config is required when building; use --disc CUE --no-build for an existing disc" >&2
  exit 2
fi
if [ -z "$DISC" ]; then
  echo "provide --config TOML, or --disc CUE together with --no-build" >&2
  exit 2
fi

if [ "${SEGACD_RECORD_PROFILE_LOCKED:-0}" != "1" ]; then
  if [ -n "$CONFIG" ]; then
    STEM_ARGS=(--config "$CONFIG")
  else
    STEM_ARGS=(--stem "record-disc:$(realpath -m "$DISC")")
  fi
  exec "$PYTHON" tools/resource_tokens.py run-stem "${STEM_ARGS[@]}" -- \
    env SEGACD_RECORD_PROFILE_LOCKED=1 "$0" "${ORIGINAL_ARGS[@]}"
fi

if [[ ! "$REC_SECS" =~ ^[1-9][0-9]*$ ]]; then
  echo "--seconds must be a positive integer: $REC_SECS" >&2
  exit 2
fi
if [[ ! "$TRIM" =~ ^(0|[1-9][0-9]*)$ ]]; then
  echo "--trim must be a non-negative integer: $TRIM" >&2
  exit 2
fi
[ -z "$TAG" ] && TAG="rec_$(basename "${DISC%.*}")"
case "$TAG" in
    .|..|*/*|*$'\r'*|*$'\n'*) echo "invalid recording tag: $TAG" >&2; exit 2;;
esac
[ -z "$OUT" ] && OUT="${TAG}_preview.mp4"

if [ "${SEGACD_RECORD_TMPFS_HELD:-0}" != "1" ]; then
  RECORD_REQUIRED_GB=$((4 + 2 * ((REC_SECS + 59) / 60)))
  RECORD_KEY="$TAG|$(realpath -m "$DISC")|$REC_SECS|$TRIM|blastem|$BIOS_REGION|$VDP_EVENT_LOG"
  exec "$PYTHON" tools/tmpfs_workspace.py run-directory \
    --kind record --key "$RECORD_KEY" --required-gb "$RECORD_REQUIRED_GB" \
    --input "$INPUT_SCRIPT" -- \
    env SEGACD_RECORD_TMPFS_HELD=1 OUTDIR='{output}' \
      "$0" "${ORIGINAL_ARGS[@]}"
fi

CAPTURE_DIR="${OUTDIR:?managed recording directory is missing}"
OUT="$CAPTURE_DIR/$(basename "$OUT")"

if [ "${SEGACD_RECORD_OUTPUT_LOCKED:-0}" != "1" ]; then
  OUTPUT_LOCK="$(
    realpath -m -s "$CAPTURE_DIR/${TAG}"
  )|$(realpath -m -s "$OUT")"
  exec "$PYTHON" tools/resource_tokens.py run-stem \
    --stem "record-output:$OUTPUT_LOCK" -- \
    env SEGACD_RECORD_OUTPUT_LOCKED=1 "$0" "${ORIGINAL_ARGS[@]}"
fi

mkdir -p "$CAPTURE_DIR" "$(dirname "$OUT")"
command -v ffmpeg >/dev/null 2>&1 || { echo "missing ffmpeg" >&2; exit 1; }
command -v ffprobe >/dev/null 2>&1 || { echo "missing ffprobe" >&2; exit 1; }

if [ "$BUILD" -eq 1 ]; then
  if [ "$BUILD_DEBUG" -eq 1 ]; then
    echo ">> make disc CONFIG=$CONFIG DEBUG=1 (recording default)"
  else
    echo ">> make disc CONFIG=$CONFIG DEBUG=0 (explicit release build)"
  fi
  make disc CONFIG="$CONFIG" DEBUG="$BUILD_DEBUG" SECURITY_REGION="$BIOS_REGION" PYTHON="$PYTHON" >/dev/null
fi
[ -f "$DISC" ] || { echo "disc not found: $DISC (drop --no-build or build it)" >&2; exit 1; }

CAPTURE_LEAD="$TRIM"
[ "$AUTO_AUDIO_TRIM" -eq 1 ] && CAPTURE_LEAD=30
MAX_FRAMES=$(( (CAPTURE_LEAD + REC_SECS + 10) * 60 ))
if [ "$MAX_FRAMES" -le 0 ] || [ "$MAX_FRAMES" -gt 10000000 ]; then
  echo "capture duration is outside the supported range" >&2
  exit 2
fi
PIPELINE_WALL_START_NS="$(date +%s%N)"
echo ">> recording ${REC_SECS}s of $DISC with the BlastEm fork"
RAW_MKV="$CAPTURE_DIR/${TAG}.mkv"
BOUNDED_MKV="$CAPTURE_DIR/${TAG}_lossless.mkv"
BLASTEM_ARGS=()
[ "$VDP_EVENT_LOG" -eq 0 ] || BLASTEM_ARGS=(--vdp-event-log)
LAUNCHER_LOG="$CAPTURE_DIR/${TAG}_launcher.log"
OUTDIR="$CAPTURE_DIR" tools/run_headless.sh "$DISC" --tag "$TAG" \
  --record "$RAW_MKV" --max-frames "$MAX_FRAMES" --input-script "$INPUT_SCRIPT" \
  "${BLASTEM_ARGS[@]}" | tee "$LAUNCHER_LOG"
RUN_RECEIPT="$(sed -n 's/^BLASTEM_RECEIPT=//p' "$LAUNCHER_LOG")"
[ -s "$RUN_RECEIPT" ] || { echo "BlastEm run receipt is missing" >&2; exit 1; }

AUTO_TRIM_WAV=""
if [ "$AUTO_AUDIO_TRIM" -eq 1 ]; then
  AUTO_TRIM_WAV="$CAPTURE_DIR/${TAG}_auto_trim.wav"
  ffmpeg -y -hide_banner -loglevel error -i "$RAW_MKV" -vn -ar 44100 "$AUTO_TRIM_WAV"
  [ -s "$AUTO_TRIM_WAV" ] || { echo "auto audio trim extraction failed: $AUTO_TRIM_WAV" >&2; exit 1; }
  TRIM="$("$PYTHON" - "$AUTO_TRIM_WAV" "$REC_SECS" <<'PY'
import math
import struct
import sys
import wave

path, seconds_s = sys.argv[1:]
seconds = int(seconds_s)

with wave.open(path, "rb") as wav:
    rate = wav.getframerate()
    channels = wav.getnchannels()
    frames = wav.getnframes()
    data = wav.readframes(frames)

samples = struct.unpack("<%dh" % (len(data) // 2), data)
window_samples = seconds * rate * channels
step_samples = rate * channels

best_start = 0
best_rms = -1.0
last = max(0, len(samples) - window_samples)
for start in range(0, last + 1, step_samples):
    seg = samples[start : start + window_samples]
    if not seg:
        continue
    rms = math.sqrt(sum(sample * sample for sample in seg) / len(seg))
    if rms > best_rms:
        best_rms = rms
        best_start = start

if best_rms < 1:
    raise SystemExit(f"no non-silent audio window found; best_rms={best_rms:.4f}")

print(best_start // step_samples)
print(f"auto audio trim: start={best_start // step_samples}s rms={best_rms:.4f}", file=sys.stderr)
PY
)"
  echo ">> auto audio trim selected ${TRIM}s"
fi

if [ "$TRIM" = "0" ]; then
  echo ">> keeping Mega-CD startup in bounded lossless capture -> $BOUNDED_MKV"
  CAPTURE_CODEC_ARGS=(-c copy)
else
  echo ">> trimming ${TRIM}s from the bounded lossless capture -> $BOUNDED_MKV"
  # Decode the precise cut point instead of keeping the previous keyframe.
  CAPTURE_CODEC_ARGS=(-c:v ffv1 -threads:v 2 -pix_fmt bgr0 -c:a flac)
fi
ffmpeg -y -hide_banner -loglevel error -ss "$TRIM" -i "$RAW_MKV" \
  -t "$REC_SECS" -map 0:v:0 -map 0:a:0 "${CAPTURE_CODEC_ARGS[@]}" "$BOUNDED_MKV"

if [ "$PREVIEW" -eq 1 ]; then
  echo ">> transcoding verification preview -> $OUT"
  RECORD_CPU_WORKERS="$(
    "$PYTHON" tools/resource_tokens.py cpu-workers
  )"
  echo ">> preview CPU tokens: $RECORD_CPU_WORKERS"
  "$PYTHON" tools/resource_tokens.py run \
    --resource cpu --count "$RECORD_CPU_WORKERS" -- \
    ffmpeg -y -hide_banner -loglevel error -i "$BOUNDED_MKV" \
      -c:v libx264 -threads "$RECORD_CPU_WORKERS" -crf 18 -pix_fmt yuv420p \
      -c:a aac -b:a 128k -movflags +faststart "$OUT"
  OUT_ACTUAL="$OUT"
else
  echo ">> lossy verification preview disabled (opt-in with --preview)"
  OUT_ACTUAL=""
fi

PIPELINE_WALL_END_NS="$(date +%s%N)"
PIPELINE_WALL_SECONDS="$(awk -v start="$PIPELINE_WALL_START_NS" -v end="$PIPELINE_WALL_END_NS" \
  'BEGIN { printf "%.3f", (end - start) / 1000000000 }')"

ARTIFACTS=("$BOUNDED_MKV")
[ -z "$OUT_ACTUAL" ] || ARTIFACTS+=("$OUT_ACTUAL")
for artifact in "${ARTIFACTS[@]}"; do
  AUDIO_INFO="$(ffprobe -v error -count_packets -select_streams a:0 \
    -show_entries stream=codec_name,sample_rate,channels,nb_read_packets \
    -of csv=p=0 "$artifact")"
  IFS=, read -r AUDIO_CODEC AUDIO_RATE AUDIO_CHANNELS AUDIO_PACKETS <<< "$AUDIO_INFO"
  if [ -z "$AUDIO_CODEC" ] || [ -z "$AUDIO_RATE" ] || [ -z "$AUDIO_CHANNELS" ] ||
     ! [[ "$AUDIO_PACKETS" =~ ^[1-9][0-9]*$ ]]; then
    echo "artifact has no usable audio stream: $artifact" >&2
    exit 1
  fi
  echo "AUDIO=$artifact codec=$AUDIO_CODEC rate=$AUDIO_RATE channels=$AUDIO_CHANNELS packets=$AUDIO_PACKETS"
  ffprobe -hide_banner "$artifact" 2>&1 | grep -E 'Input|Duration|Stream' || true
done

"$PYTHON" - "$RUN_RECEIPT" "$BOUNDED_MKV" "$TRIM" <<'PYTHON'
import json
import sys
from pathlib import Path

from run_blastem import write_receipt

receipt_path, recording = map(Path, sys.argv[1:3])
data = json.loads(receipt_path.read_text(encoding="utf-8"))
if data.get("complete") is not True:
    raise SystemExit(f"incomplete BlastEm receipt: {receipt_path}")
stat = recording.stat()
data["lossless_recording"] = {
    "path": str(recording.resolve()),
    "size": stat.st_size,
    "mtime_ns": stat.st_mtime_ns,
    "trim_seconds": int(sys.argv[3]),
}
write_receipt(receipt_path, data)
PYTHON

rm -f "$RAW_MKV"
[ -z "$AUTO_TRIM_WAV" ] || rm -f "$AUTO_TRIM_WAV"
echo "PIPELINE_WALL_SECONDS=$PIPELINE_WALL_SECONDS"
echo "RECORD_DIR=$CAPTURE_DIR"
echo "LOSSLESS=$BOUNDED_MKV"
[ -z "$OUT_ACTUAL" ] || echo "OUT=$OUT_ACTUAL"
