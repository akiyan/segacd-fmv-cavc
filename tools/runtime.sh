#!/usr/bin/env bash
# Apply storage options to any pipeline command and all of its children.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
while [ "$#" -gt 0 ]; do
  case "$1" in
    --workspace-root|--scratch-root|--array-storage)
      if [ "$#" -lt 2 ] || [ -z "$2" ]; then
        echo "$1 requires a value" >&2
        exit 2
      fi
      case "$1" in
        --workspace-root) export CAVC_WORKSPACE_ROOT="$2" ;;
        --scratch-root) export CAVC_SCRATCH_ROOT="$2" ;;
        --array-storage) export CAVC_ARRAY_STORAGE="$2" ;;
      esac
      shift 2 ;;
    --) shift; break ;;
    --help)
      echo 'Usage: tools/runtime.sh [--workspace-root DIR] [--scratch-root DIR] [--array-storage memory|disk] -- COMMAND [ARGS...]'
      echo 'Default workspace: repo/tmp/workspace. Scratch: TMPDIR or workspace/scratch. Arrays: memory.'
      exit 0 ;;
    *) echo "unknown runtime option: $1 (put the command after --)" >&2; exit 2 ;;
  esac
done
if [ "$#" -eq 0 ]; then
  echo 'command required after --' >&2
  exit 2
fi
export CAVC_WORKSPACE_ROOT="${CAVC_WORKSPACE_ROOT:-${SEGACD_TMPFS_ROOT:-$ROOT/tmp/workspace}}"
export CAVC_SCRATCH_ROOT="${CAVC_SCRATCH_ROOT:-${TMPDIR:-$CAVC_WORKSPACE_ROOT/scratch}}"
export CAVC_ARRAY_STORAGE="${CAVC_ARRAY_STORAGE:-memory}"
case "$CAVC_ARRAY_STORAGE" in
  memory|disk) ;;
  *) echo 'array storage must be memory or disk' >&2; exit 2 ;;
esac
mkdir -p -- "$CAVC_WORKSPACE_ROOT" "$CAVC_SCRATCH_ROOT"
CAVC_WORKSPACE_ROOT="$(cd "$CAVC_WORKSPACE_ROOT" && pwd -P)"
CAVC_SCRATCH_ROOT="$(cd "$CAVC_SCRATCH_ROOT" && pwd -P)"
# tempfile, mktemp and child encoders inherit the same explicit scratch root.
export TMPDIR="$CAVC_SCRATCH_ROOT" TMP="$CAVC_SCRATCH_ROOT" TEMP="$CAVC_SCRATCH_ROOT"
exec "$@"
