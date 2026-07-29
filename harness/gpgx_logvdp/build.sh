#!/usr/bin/env bash
#
# Build the pinned Genesis Plus GX libretro core with upstream LOGVDP enabled.
#
# The fetched source and installed binary are generated under vendor/ and are
# deliberately excluded from this repository. The harness, pinned commit, and
# build-only compatibility declaration remain tracked and reproducible.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
UPSTREAM_URL="https://github.com/ekeeke/Genesis-Plus-GX.git"
UPSTREAM_COMMIT="46652c7fd74bd64a99f624b0bd53a768de0ff672"
VENDOR_DIR="${GPGX_VENDOR_DIR:-$ROOT/vendor/gpgx-logvdp}"
CORE_FILENAME="genesis_plus_gx_logvdp_libretro.so"
CORE_PATH="$VENDOR_DIR/$CORE_FILENAME"
MANIFEST_PATH="$VENDOR_DIR/manifest.tsv"
COMPAT_HEADER="$ROOT/harness/gpgx_logvdp/logvdp_error_decl.h"

usage() {
  cat <<EOF
usage: $0 [--force | --check | --print-core]

  (no option)    build only when the installed core is absent or invalid
  --force        fetch and rebuild even when the installed core is valid
  --check        verify the installed core, manifest, and LOGVDP strings
  --print-core   print the managed core path without building it

Environment:
  GPGX_VENDOR_DIR   alternate generated install directory
  GPGX_BUILD_JOBS   parallel build jobs (default: host CPU count)
  CC                C compiler executable (default: cc)
EOF
}

MODE="build"
FORCE=0
if [ $# -gt 1 ]; then
  usage >&2
  exit 2
fi
if [ $# -eq 1 ]; then
  case "$1" in
    --force) FORCE=1 ;;
    --check) MODE="check" ;;
    --print-core) MODE="print-core" ;;
    -h|--help) usage; exit 0 ;;
    *) usage >&2; exit 2 ;;
  esac
fi

if [ "$MODE" = "print-core" ]; then
  printf '%s\n' "$CORE_PATH"
  exit 0
fi

manifest_value() {
  local key="$1"
  awk -F '\t' -v wanted="$key" \
    '$1 == wanted { print $2; found = 1; exit } END { if (!found) exit 1 }' \
    "$MANIFEST_PATH"
}

check_installed() {
  local quiet="${1:-0}"
  local reason=""
  local recorded_sha=""
  local actual_sha=""

  if [ ! -s "$CORE_PATH" ]; then
    reason="core is missing: $CORE_PATH"
  elif [ ! -s "$MANIFEST_PATH" ]; then
    reason="manifest is missing: $MANIFEST_PATH"
  elif [ "$(manifest_value upstream_commit 2>/dev/null || true)" != "$UPSTREAM_COMMIT" ]; then
    reason="manifest has a different upstream commit"
  elif [ "$(manifest_value log_define 2>/dev/null || true)" != "LOGVDP" ]; then
    reason="manifest does not identify a LOGVDP build"
  elif [ "$(manifest_value have_chd 2>/dev/null || true)" != "0" ]; then
    reason="manifest does not match the qualified HAVE_CHD setting"
  elif ! LC_ALL=C grep -aFq "DMA type %d" "$CORE_PATH"; then
    reason="core does not contain the upstream DMA trace"
  elif ! LC_ALL=C grep -aFq "DMA ends in %d cycles" "$CORE_PATH"; then
    reason="core does not contain the upstream DMA completion trace"
  else
    recorded_sha="$(manifest_value core_sha256 2>/dev/null || true)"
    actual_sha="$(sha256sum "$CORE_PATH" | awk '{print $1}')"
    if [ -z "$recorded_sha" ] || [ "$recorded_sha" != "$actual_sha" ]; then
      reason="core SHA-256 does not match its manifest"
    fi
  fi

  if [ -n "$reason" ]; then
    if [ "$quiet" -eq 0 ]; then
      echo "GPGX LOGVDP core check failed: $reason" >&2
      echo "rebuild it with: $ROOT/harness/gpgx_logvdp/build.sh --force" >&2
    fi
    return 1
  fi
  return 0
}

if [ "$MODE" = "check" ]; then
  check_installed
  CORE_SHA="$(sha256sum "$CORE_PATH" | awk '{print $1}')"
  echo "GPGX LOGVDP core: OK"
  echo "core: $CORE_PATH"
  echo "upstream: $UPSTREAM_COMMIT"
  echo "sha256: $CORE_SHA"
  exit 0
fi

if [ "$FORCE" -eq 0 ] && check_installed 1; then
  echo "GPGX LOGVDP core is already current: $CORE_PATH"
  exit 0
fi

for tool in git make awk grep sha256sum; do
  command -v "$tool" >/dev/null 2>&1 || {
    echo "missing required build tool: $tool" >&2
    exit 1
  }
done
BUILD_CC="${CC:-cc}"
command -v "$BUILD_CC" >/dev/null 2>&1 || {
  echo "missing C compiler: $BUILD_CC" >&2
  exit 1
}
[ -f "$COMPAT_HEADER" ] || {
  echo "missing LOGVDP compatibility declaration: $COMPAT_HEADER" >&2
  exit 1
}

BUILD_JOBS="${GPGX_BUILD_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)}"
if ! [[ "$BUILD_JOBS" =~ ^[1-9][0-9]*$ ]]; then
  echo "GPGX_BUILD_JOBS must be a positive integer: $BUILD_JOBS" >&2
  exit 2
fi

mkdir -p "$VENDOR_DIR"
WORK_DIR="$(mktemp -d "$VENDOR_DIR/.build.XXXXXX")"
SOURCE_DIR="$WORK_DIR/source"
BUILD_LOG="$WORK_DIR/build.log"
cleanup() {
  rm -rf -- "$WORK_DIR"
}
trap cleanup EXIT

echo "Fetching Genesis Plus GX $UPSTREAM_COMMIT ..."
git init -q "$SOURCE_DIR"
git -C "$SOURCE_DIR" remote add origin "$UPSTREAM_URL"
git -C "$SOURCE_DIR" fetch -q --depth 1 origin "$UPSTREAM_COMMIT"
git -C "$SOURCE_DIR" checkout -q --detach FETCH_HEAD
ACTUAL_COMMIT="$(git -C "$SOURCE_DIR" rev-parse HEAD)"
if [ "$ACTUAL_COMMIT" != "$UPSTREAM_COMMIT" ]; then
  echo "fetched unexpected commit: $ACTUAL_COMMIT" >&2
  exit 1
fi

echo "Building LOGVDP libretro core with $BUILD_JOBS jobs ..."
if ! make -C "$SOURCE_DIR" -f Makefile.libretro \
    -j"$BUILD_JOBS" \
    platform=unix \
    HAVE_CHD=0 \
    CC="$BUILD_CC" \
    CODE_DEFINES="-DLOGVDP -include $COMPAT_HEADER" \
    >"$BUILD_LOG" 2>&1; then
  install -m 0644 "$BUILD_LOG" "$VENDOR_DIR/build.failed.log"
  tail -80 "$BUILD_LOG" >&2
  echo "GPGX build failed; complete log: $VENDOR_DIR/build.failed.log" >&2
  exit 1
fi

CANDIDATE_CORE="$SOURCE_DIR/genesis_plus_gx_libretro.so"
[ -s "$CANDIDATE_CORE" ] || {
  echo "build did not produce $CANDIDATE_CORE" >&2
  exit 1
}
LC_ALL=C grep -aFq "DMA type %d" "$CANDIDATE_CORE" || {
  echo "built core is missing the LOGVDP DMA trace" >&2
  exit 1
}
LC_ALL=C grep -aFq "DMA ends in %d cycles" "$CANDIDATE_CORE" || {
  echo "built core is missing the LOGVDP completion trace" >&2
  exit 1
}

CORE_SHA="$(sha256sum "$CANDIDATE_CORE" | awk '{print $1}')"
CORE_BYTES="$(wc -c < "$CANDIDATE_CORE" | tr -d '[:space:]')"
COMPILER_VERSION="$("$BUILD_CC" --version | sed -n '1p' | tr '\t' ' ')"
BUILD_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
MANIFEST_TMP="$WORK_DIR/manifest.tsv"
{
  printf 'key\tvalue\n'
  printf 'schema_version\t1\n'
  printf 'upstream_url\t%s\n' "$UPSTREAM_URL"
  printf 'upstream_commit\t%s\n' "$UPSTREAM_COMMIT"
  printf 'log_define\tLOGVDP\n'
  printf 'have_chd\t0\n'
  printf 'vorbis_decoder\tbundled-tremor\n'
  printf 'compat_header\t%s\n' "harness/gpgx_logvdp/logvdp_error_decl.h"
  printf 'compiler\t%s\n' "$COMPILER_VERSION"
  printf 'build_utc\t%s\n' "$BUILD_UTC"
  printf 'core_filename\t%s\n' "$CORE_FILENAME"
  printf 'core_bytes\t%s\n' "$CORE_BYTES"
  printf 'core_sha256\t%s\n' "$CORE_SHA"
} > "$MANIFEST_TMP"

CORE_TMP="$VENDOR_DIR/.${CORE_FILENAME}.new"
MANIFEST_INSTALL_TMP="$VENDOR_DIR/.manifest.tsv.new"
install -m 0755 "$CANDIDATE_CORE" "$CORE_TMP"
install -m 0644 "$MANIFEST_TMP" "$MANIFEST_INSTALL_TMP"
mv -f "$CORE_TMP" "$CORE_PATH"
mv -f "$MANIFEST_INSTALL_TMP" "$MANIFEST_PATH"
install -m 0644 "$BUILD_LOG" "$VENDOR_DIR/build.log"
rm -f "$VENDOR_DIR/build.failed.log"

check_installed
echo "Installed GPGX LOGVDP core: $CORE_PATH"
echo "sha256: $CORE_SHA"
