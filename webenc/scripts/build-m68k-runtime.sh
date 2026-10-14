#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ -f .toolchain/binutils-build/gas/as-new.wasm && -f .toolchain/binutils-build/ld/ld-new.wasm && -f .toolchain/binutils-build/binutils/objcopy.wasm ]]; then
  node scripts/prepare-m68k-runtime.mjs
  exit 0
fi
mkdir -p .toolchain
if [[ ! -f .toolchain/emsdk/emsdk ]]; then
  git clone --depth 1 https://github.com/emscripten-core/emsdk.git .toolchain/emsdk
fi
.toolchain/emsdk/emsdk install 6.0.12
.toolchain/emsdk/emsdk activate 6.0.12
curl -fsSL https://ftp.gnu.org/gnu/binutils/binutils-2.40.tar.xz -o .toolchain/binutils-2.40.tar.xz
echo '0f8a4c272d7f17f369ded10a4aca28b8e304828e95526da482b0ccc4dfc9d8e1  .toolchain/binutils-2.40.tar.xz' | sha256sum -c -
mkdir -p .toolchain/binutils-src .toolchain/binutils-build
tar -xf .toolchain/binutils-2.40.tar.xz -C .toolchain/binutils-src --strip-components=1
python3 - <<'PY'
from pathlib import Path
p=Path('.toolchain/binutils-src/libiberty/strsignal.c')
p.write_text(p.read_text().replace('psignal (int signo, char *message)', 'psignal (int signo, const char *message)'))
PY
source .toolchain/emsdk/emsdk_env.sh
(
  cd .toolchain/binutils-build
  CFLAGS='-O2' LDFLAGS='-sMODULARIZE=1 -sEXPORT_ES6=1 -sENVIRONMENT=web,worker,node -sALLOW_MEMORY_GROWTH=1 -sINVOKE_RUN=0 -sEXPORTED_RUNTIME_METHODS=FS,callMain' \
    emconfigure ../binutils-src/configure --host=wasm32-unknown-emscripten --target=m68k-elf \
    --disable-nls --disable-werror --disable-shared --enable-static --disable-gprofng \
    --disable-gprof --disable-gdb --disable-sim --disable-gold --disable-libctf --without-zstd --without-debuginfod
  emmake make -j4 all-gas all-ld all-binutils
)
node scripts/prepare-m68k-runtime.mjs
