#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WORK_DIR="$(mktemp -d /tmp/gpgx-logvdp-test.XXXXXX)"
cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

INPUT="$WORK_DIR/retroarch_test.log"
ORIGINAL="$WORK_DIR/original.log"
FULL="$WORK_DIR/gpgx_logvdp_test.log.gz"
cat > "$INPUT" <<'EOF'
# GPGX core: /managed/core.so
[INFO] RetroArch test
[libretro ERROR] [224(224)][100(100)] VRAM 0x100 write -> 0x1 (200)

[libretro ERROR] [224(224)][200(200)] DMA type 0 (18 access/line)(100 cycles left)-> 2 access (16 remaining) (300)

[libretro ERROR] -->CPU frozen for 100 cycles

[libretro ERROR] -->DMA ends in 100 cycles

[libretro ERROR] genuinely unexpected core failure
[INFO] [Runtime] Content ran for a total of: 00 hours, 00 minutes, 01 seconds.
[INFO] [Core] Unloading core...
EOF
cp "$INPUT" "$ORIGINAL"

"$ROOT/harness/gpgx_logvdp/compact_log.sh" "$INPUT" "$FULL" >/dev/null
gzip -cd "$FULL" > "$WORK_DIR/restored.log"
cmp "$ORIGINAL" "$WORK_DIR/restored.log"

grep -Fq "DMA type 0" "$INPUT"
grep -Fq "CPU frozen for 100 cycles" "$INPUT"
grep -Fq "DMA ends in 100 cycles" "$INPUT"
grep -Fq "genuinely unexpected core failure" "$INPUT"
grep -Fq "[Core] Unloading core" "$INPUT"
if grep -Fq "VRAM 0x100 write" "$INPUT"; then
  echo "known non-DMA LOGVDP chatter survived compaction" >&2
  exit 1
fi
grep -Fq "dropped_trace_lines=1" "$INPUT"

echo "GPGX LOGVDP compaction test: OK"
