#!/usr/bin/env bash
# Run the standalone akiyan/blastem fork under the shared emulator token pool.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ "${1:-}" = "--backend" ]; then
  if [ "${2:-}" != "blastem" ]; then
    echo "run_headless.sh uses the akiyan/blastem fork" >&2
    exit 2
  fi
  shift 2
fi
if [ "${SEGACD_EMU_TOKEN_HELD:-0}" != "1" ]; then
  exec "$ROOT/tools/python.sh" "$ROOT/tools/resource_tokens.py" run \
    --resource emu --count 1 -- \
    env SEGACD_EMU_TOKEN_HELD=1 "$0" "$@"
fi
exec "$ROOT/tools/python.sh" "$ROOT/tools/run_blastem.py" "$@"
