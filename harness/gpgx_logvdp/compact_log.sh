#!/usr/bin/env bash
#
# Preserve a complete LOGVDP run as fast gzip and compact the normal RA log.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <retroarch.log> <full-log.gz>" >&2
  exit 2
fi

INPUT_LOG="$1"
FULL_LOG="$2"
[ -s "$INPUT_LOG" ] || {
  echo "LOGVDP input log is missing or empty: $INPUT_LOG" >&2
  exit 1
}
mkdir -p "$(dirname "$FULL_LOG")"

COMPACT_TMP="$(mktemp "${INPUT_LOG}.compact.XXXXXX")"
FULL_TMP="$(mktemp "${FULL_LOG}.new.XXXXXX")"
cleanup() {
  rm -f -- "$COMPACT_TMP" "$FULL_TMP"
}
trap cleanup EXIT

# -1 keeps post-run handling cheap. LOGVDP data is repetitive enough that the
# fastest level still removes most of its size.
gzip -1 -c "$INPUT_LOG" > "$FULL_TMP"
gzip -t "$FULL_TMP"

FULL_BASENAME="$(basename "$FULL_LOG")"
{
  printf '# Full GPGX LOGVDP trace: %s\n' "$FULL_BASENAME"
  awk '
    function is_dma_trace(line) {
      return line ~ /DMA type/ ||
             line ~ /CPU frozen for/ ||
             line ~ /DMA ends in/
    }
    function is_noisy_logvdp_trace(line) {
      return line ~ /VDP 68k status read/ ||
             line ~ /VDP Z80 status read/ ||
             line ~ /HVC latch read/ ||
             line ~ /HVC read/ ||
             line ~ /Unused VDP Write/ ||
             line ~ /INT Level .* ack/ ||
             line ~ /VINT cleared/ ||
             line ~ /HINT cleared/ ||
             line ~ /VDP register .* write/ ||
             line ~ /VRAM .* write/ ||
             line ~ /CRAM .* write/ ||
             line ~ /VSRAM .* write/ ||
             line ~ /VRAM .* read/ ||
             line ~ /CRAM .* read/ ||
             line ~ /VSRAM .* read/ ||
             line ~ /Invalid .* write/ ||
             line ~ /Invalid .* read/
    }
    /^\[libretro ERROR\]/ {
      if (is_dma_trace($0)) {
        print
        next
      }
      if (is_noisy_logvdp_trace($0)) {
        dropped++
        next
      }
    }
    /^$/ {
      blank++
      next
    }
    {
      print
    }
    END {
      printf "# LOGVDP compacted: dropped_trace_lines=%d dropped_blank_lines=%d\n",
             dropped, blank
    }
  ' "$INPUT_LOG"
} > "$COMPACT_TMP"

RAW_BYTES="$(wc -c < "$INPUT_LOG" | tr -d '[:space:]')"
FULL_BYTES="$(wc -c < "$FULL_TMP" | tr -d '[:space:]')"
COMPACT_BYTES="$(wc -c < "$COMPACT_TMP" | tr -d '[:space:]')"

mv -f "$FULL_TMP" "$FULL_LOG"
mv -f "$COMPACT_TMP" "$INPUT_LOG"
trap - EXIT

echo "GPGX LOGVDP log: raw=${RAW_BYTES}B compact=${COMPACT_BYTES}B gzip=${FULL_BYTES}B"
