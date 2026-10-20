#!/usr/bin/env bash
# Run project Python tools from the uv-managed, system-independent environment.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_DIR="$ROOT/.venv"
VERSION_FILE="$ROOT/.python-version"
BOOTSTRAP_MODE=--cpu

RUNTIME_ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --gpu)
      ENV_DIR="$ROOT/.venv-gpu"
      VERSION_FILE="$ROOT/.python-version-gpu"
      BOOTSTRAP_MODE=--gpu
      shift ;;
    --workspace-root|--scratch-root|--array-storage)
      if [ "$#" -lt 2 ]; then echo "$1 requires a value" >&2; exit 2; fi
      RUNTIME_ARGS+=("$1" "$2")
      shift 2 ;;
    --help-runtime) exec "$ROOT/tools/runtime.sh" --help ;;
    *) break ;;
  esac
done

PYTHON="$ENV_DIR/bin/python"
if [ ! -x "$PYTHON" ]; then
  echo "missing $ENV_DIR; run: tools/bootstrap_python.sh $BOOTSTRAP_MODE" >&2
  exit 1
fi

EXPECTED_VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"
ACTUAL_VERSION="$("$PYTHON" -c 'import platform; print(platform.python_version())')"
if [ "$ACTUAL_VERSION" != "$EXPECTED_VERSION" ]; then
  echo "wrong Python in $ENV_DIR: expected $EXPECTED_VERSION, got $ACTUAL_VERSION" >&2
  echo "rebuild it with: tools/bootstrap_python.sh $BOOTSTRAP_MODE" >&2
  exit 1
fi
if grep -Eq '^include-system-site-packages[[:space:]]*=[[:space:]]*true' "$ENV_DIR/pyvenv.cfg"; then
  echo "unsafe environment $ENV_DIR inherits system site-packages; rebuild it" >&2
  exit 1
fi

# Project tools intentionally import their siblings as top-level modules
# (for example, ``import av_config``).  Make that contract independent of the
# caller's working directory and preserve any caller-supplied search path.
PROJECT_PYTHONPATH="$ROOT/tools:$ROOT"
if [ -n "${PYTHONPATH:-}" ]; then
  PROJECT_PYTHONPATH="$PROJECT_PYTHONPATH:$PYTHONPATH"
fi
export PYTHONPATH="$PROJECT_PYTHONPATH"

exec "$ROOT/tools/runtime.sh" "${RUNTIME_ARGS[@]}" -- "$PYTHON" "$@"
