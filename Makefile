PROJECT := SCFMV_MCD
OUT_DIR := out
DISC_DIR := $(OUT_DIR)/disc
BOOT_DIR := boot
CFG_DIR := cfg
# Release region.  It picks the security code the console validates and the
# disc-header fields that name the region, and it names the movie disc so a
# second region cannot overwrite the first.  jp is the default and keeps the
# unsuffixed output paths every other tool already uses.
SECURITY_REGION ?= jp
CONFIG ?=
PYTHON ?= tools/python.sh

# A movie build is identified by its TOML filename.  Keep packed streams under
# out/<toml-stem>/, transient build/staging files under tmp/<toml-stem>/, and
# the bootable pair at out/<toml-stem>.iso + .cue.  Standalone hardware tests
# keep their fixed names.
ifeq ($(strip $(MAKECMDGOALS)),)
MOVIEPLAY_REQUESTED := all
else
MOVIEPLAY_REQUESTED := $(filter all disc movieplay movieplay-internal movieplay-module test1m,$(MAKECMDGOALS))
endif
ifneq ($(strip $(MOVIEPLAY_REQUESTED)),)
ifeq ($(strip $(CONFIG)),)
$(error CONFIG is required; for example: make disc CONFIG=profiles/bad-apple.toml)
endif
endif

ifneq ($(strip $(CONFIG)),)
CONFIG_STEM := $(shell $(PYTHON) tools/encode_config.py "$(CONFIG)" --print-stem)
ifeq ($(strip $(CONFIG_STEM)),)
$(error invalid CONFIG: $(CONFIG))
endif
else
CONFIG_STEM := movieplay
endif

MOVIEPLAY_STREAM_DIR := $(OUT_DIR)/$(CONFIG_STEM)
MOVIEPLAY_TMP_DIR := tmp/$(CONFIG_STEM)
MOVIEPLAY_BUILD_DIR := $(MOVIEPLAY_TMP_DIR)/build
MOVIEPLAY_DISC := $(MOVIEPLAY_TMP_DIR)/disc
# 既定はリリースビルド。DEBUG=1 でデバッグオーバーレイを有効化する。
DEBUG ?= 0
# リリースディスクは _release を付けて、同じ packed stream から作った
# DEBUG ディスクと出力先で衝突させない。
DISC_SUFFIX := $(if $(filter 1,$(DEBUG)),,_release)
# jp keeps the plain name, so every existing recording, burn and release path
# stays valid; another region gets its own disc rather than overwriting it.
REGION_SUFFIX := $(if $(filter jp,$(SECURITY_REGION)),,_$(SECURITY_REGION))
MOVIEPLAY_ISO := $(OUT_DIR)/$(CONFIG_STEM)$(REGION_SUFFIX)$(DISC_SUFFIX).iso
MOVIEPLAY_CUE := $(OUT_DIR)/$(CONFIG_STEM)$(REGION_SUFFIX)$(DISC_SUFFIX).cue
MOVIEPACK_OUTPUTS := \
	$(MOVIEPLAY_STREAM_DIR)/HEADER.DAT \
	$(MOVIEPLAY_STREAM_DIR)/BODY.DAT \
	$(MOVIEPLAY_STREAM_DIR)/MOVIE.DAT \
	$(MOVIEPLAY_STREAM_DIR)/paltab.bin \
	$(MOVIEPLAY_STREAM_DIR)/palidx.bin
PLAYER_CONSTANTS := $(MOVIEPLAY_STREAM_DIR)/player_constants.inc
SP_EXTENSION_OBJ := $(MOVIEPLAY_BUILD_DIR)/movieplay_sp_ext.o
SP_EXTENSION_BIN := $(MOVIEPLAY_BUILD_DIR)/movieplay_sp_ext.bin
SP_EXTENSION_CONSTANTS := $(MOVIEPLAY_BUILD_DIR)/sp_extension.inc
MOVIEPLAY_SECURITY := $(MOVIEPLAY_BUILD_DIR)/security.bin
MOVIEPLAY_REGION_INC := $(MOVIEPLAY_BUILD_DIR)/disc_region.inc
MOVIEPLAY_DEBUG_FONT := $(MOVIEPLAY_BUILD_DIR)/dbgfont.bin
MULTI_MENU ?= 0
MULTI_PLAYER_INCLUDE ?= $(MOVIEPLAY_BUILD_DIR)/multi_player.inc
ifeq ($(filter 1,$(MULTI_MENU)),1)
MOVIEPLAY_MULTI_INCLUDE_DEPS := $(MULTI_PLAYER_INCLUDE)
else
MOVIEPLAY_MULTI_INCLUDE_DEPS :=
endif

MARSDEV ?= $(HOME)/toolchains/mars
M68K_PREFIX ?= $(MARSDEV)/m68k-elf/bin/m68k-elf-

AS := $(M68K_PREFIX)as
CC := $(M68K_PREFIX)gcc
LD := $(M68K_PREFIX)ld
OBJCOPY := $(M68K_PREFIX)objcopy
MKISOFS := $(shell command -v mkisofs 2>/dev/null || command -v genisoimage 2>/dev/null || true)

ASFLAGS := -m68000 --register-prefix-optional --bitwise-or
CFLAGS_M68K := -m68000 -ffreestanding -fno-builtin -fomit-frame-pointer -O2 -Wall -Wextra
LDFLAGS := -nostdlib --oformat binary

.PHONY: all disc setup movieplay-setup clean check-tools test1m cdcbench fontbench still256 movieplay movieplay-internal movieplay-module moviepack dmabench cpuvrambench streamtest pcmtest adpcmtest upscaletest asictest prgtest movieplay-force multi-disc

all: disc

setup:
	@mkdir -p $(OUT_DIR) $(DISC_DIR)

movieplay-setup: setup
	@mkdir -p $(MOVIEPLAY_STREAM_DIR) $(MOVIEPLAY_BUILD_DIR) $(MOVIEPLAY_DISC)

# Hold one output-stem lock across pack, assembly, ISO staging, and CUE
# publication. Nested pack invocations inherit the lock marker and are
# reentrant; a separate process targeting the same stem fails immediately.
disc movieplay:
	$(PYTHON) tools/resource_tokens.py run-stem --config "$(CONFIG)" -- \
		$(MAKE) movieplay-internal

check-tools:
	@test -x "$(PYTHON)" || (echo "missing project Python launcher: $(PYTHON). Run tools/bootstrap_python.sh --cpu" && exit 1)
	@test -x "$(AS)" || (echo "missing assembler: $(AS). Set MARSDEV=/path/to/mars or M68K_PREFIX=m68k-elf-" && exit 1)
	@test -x "$(CC)" || (echo "missing compiler: $(CC). Set MARSDEV=/path/to/mars or M68K_PREFIX=m68k-elf-" && exit 1)
	@test -x "$(LD)" || (echo "missing linker: $(LD). Set MARSDEV=/path/to/mars or M68K_PREFIX=m68k-elf-" && exit 1)
	@test -x "$(OBJCOPY)" || (echo "missing objcopy: $(OBJCOPY). Set MARSDEV=/path/to/mars or M68K_PREFIX=m68k-elf-" && exit 1)
	@test -n "$(MKISOFS)" || (echo "missing mkisofs/genisoimage" && exit 1)

$(BOOT_DIR)/security.bin: $(BOOT_DIR)/sec_$(SECURITY_REGION).bin
	@cp $< $@

# --- 1M Word RAM swap self-test (standalone, no CD / no M_INIT) ---
TEST1M_DISC := $(OUT_DIR)/disc_test1m

test1m: check-tools $(OUT_DIR)/TEST1M.iso $(OUT_DIR)/TEST1M.cue

$(OUT_DIR)/test1m_ip.o: $(BOOT_DIR)/test1m_ip.s $(BOOT_DIR)/security.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/test1m_ip.bin: $(OUT_DIR)/test1m_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/test1m_sp.o: $(BOOT_DIR)/test1m_sp.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/test1m_sp.bin: $(OUT_DIR)/test1m_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<

$(OUT_DIR)/test1m_boot.bin: $(OUT_DIR)/test1m_ip.bin $(OUT_DIR)/test1m_sp.bin $(BOOT_DIR)/test1m_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/test1m_boot.s -o $(OUT_DIR)/test1m_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/test1m_boot.out $@

$(OUT_DIR)/TEST1M.iso: $(OUT_DIR)/test1m_boot.bin $(MOVIEPLAY_STREAM_DIR)/MOVIE.DAT
	@mkdir -p $(TEST1M_DISC)
	@printf "1M Word RAM swap self-test\n" > $(TEST1M_DISC)/README.TXT
	@cp $(MOVIEPLAY_STREAM_DIR)/MOVIE.DAT $(TEST1M_DISC)/MOVIE.DAT
	@rm -f $@ $(OUT_DIR)/TEST1M.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_T1M" -o $@ $(TEST1M_DISC)

$(OUT_DIR)/TEST1M.cue: $(OUT_DIR)/TEST1M.iso
	@rm -f $@
	@printf 'FILE "TEST1M.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- Isolated CDC throughput test (standalone, IP+SP only, BENCH.DAT on disc) ---
CDCBENCH_DISC := $(OUT_DIR)/disc_cdcbench
CDCBENCH_DAT_SECTORS ?= 1536

cdcbench: check-tools $(OUT_DIR)/CDCBENCH.iso $(OUT_DIR)/CDCBENCH.cue

$(BOOT_DIR)/hexfont.bin: tools/gen_hexfont.py
	$(PYTHON) tools/gen_hexfont.py

$(OUT_DIR)/cdcbench_ip.o: $(BOOT_DIR)/cdcbench_ip.s $(BOOT_DIR)/security.bin $(BOOT_DIR)/hexfont.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/cdcbench_ip.bin: $(OUT_DIR)/cdcbench_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/cdcbench_sp.o: $(BOOT_DIR)/cdcbench_sp.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/cdcbench_sp.bin: $(OUT_DIR)/cdcbench_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<

$(OUT_DIR)/cdcbench_boot.bin: $(OUT_DIR)/cdcbench_ip.bin $(OUT_DIR)/cdcbench_sp.bin $(BOOT_DIR)/cdcbench_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/cdcbench_boot.s -o $(OUT_DIR)/cdcbench_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/cdcbench_boot.out $@

$(OUT_DIR)/CDCBENCH.iso: $(OUT_DIR)/cdcbench_boot.bin
	@mkdir -p $(CDCBENCH_DISC)
	@printf "CDC throughput test\n" > $(CDCBENCH_DISC)/README.TXT
	dd if=/dev/urandom of=$(CDCBENCH_DISC)/BENCH.DAT bs=2048 count=$(CDCBENCH_DAT_SECTORS) status=none
	@rm -f $@ $(OUT_DIR)/CDCBENCH.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_CDCB" -o $@ $(CDCBENCH_DISC)

$(OUT_DIR)/CDCBENCH.cue: $(OUT_DIR)/CDCBENCH.iso
	@rm -f $@
	@printf 'FILE "CDCBENCH.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- fontbench: gate-array Font bit vs CPU LUT の 1bpp->4bpp 展開ベンチ ---
# 使い方: make fontbench && tools/run_headless.sh out/FONTBENCH.cue
# 表示行と手順は harness/fontbench/README.md 参照。CD読み無し(起動後は自走)。
FONTBENCH_DISC := $(OUT_DIR)/disc_fontbench

fontbench: check-tools $(OUT_DIR)/FONTBENCH.iso $(OUT_DIR)/FONTBENCH.cue

$(OUT_DIR)/fontbench_ip.o: $(BOOT_DIR)/fontbench_ip.s $(BOOT_DIR)/security.bin $(BOOT_DIR)/hexfont.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/fontbench_ip.bin: $(OUT_DIR)/fontbench_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/fontbench_sp.o: $(BOOT_DIR)/fontbench_sp.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/fontbench_sp.bin: $(OUT_DIR)/fontbench_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<

$(OUT_DIR)/fontbench_boot.bin: $(OUT_DIR)/fontbench_ip.bin $(OUT_DIR)/fontbench_sp.bin $(BOOT_DIR)/fontbench_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/fontbench_boot.s -o $(OUT_DIR)/fontbench_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/fontbench_boot.out $@

$(OUT_DIR)/FONTBENCH.iso: $(OUT_DIR)/fontbench_boot.bin
	@mkdir -p $(FONTBENCH_DISC)
	@printf "font bit expansion bench\n" > $(FONTBENCH_DISC)/README.TXT
	@rm -f $@ $(OUT_DIR)/FONTBENCH.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_FNTB" -o $@ $(FONTBENCH_DISC)

$(OUT_DIR)/FONTBENCH.cue: $(OUT_DIR)/FONTBENCH.iso
	@rm -f $@
	@printf 'FILE "FONTBENCH.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- Phase A: 256x144 静止画レンダラ(描画土台検証, CD読み無し/CPU書き込みのみ) ---
STILL256_DISC := $(OUT_DIR)/disc_still256
STILL256_DATA ?= $(shell $(PYTHON) -c 'import sys; sys.path.insert(0, "tools"); from cbr_paths import sim_work_dir; print(sim_work_dir() / "still256.bin")')

still256: check-tools $(OUT_DIR)/STILL256.iso $(OUT_DIR)/STILL256.cue

$(OUT_DIR)/still256_ip.o: $(BOOT_DIR)/still256_ip.s $(BOOT_DIR)/security.bin $(STILL256_DATA) | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/still256_ip.bin: $(OUT_DIR)/still256_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/still256_boot.bin: $(OUT_DIR)/still256_ip.bin $(OUT_DIR)/cdcbench_sp.bin $(BOOT_DIR)/still256_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/still256_boot.s -o $(OUT_DIR)/still256_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/still256_boot.out $@

$(OUT_DIR)/STILL256.iso: $(OUT_DIR)/still256_boot.bin
	@mkdir -p $(STILL256_DISC)
	@printf "still256 phase A\n" > $(STILL256_DISC)/README.TXT
	@rm -f $@ $(OUT_DIR)/STILL256.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_ST256" -o $@ $(STILL256_DISC)

$(OUT_DIR)/STILL256.cue: $(OUT_DIR)/STILL256.iso
	@rm -f $@
	@printf 'FILE "STILL256.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- dmabench: H40 VRAM DMA スループット実測(再利用可能) ---
# 使い方: make dmabench
#         DMABENCH_DELAY=N でVBlank立ち上がりからNライン遅らせてDMAを開始(既定0)。
#         DMABENCH_RUNS=N (N>0) でplayerと同じWord-RAM DMA +先頭word補修を
#         N本の均等runに分けて実測。DMABENCH_REPAIR=0で補修なしの対照。
# RUNS=0はW=語/VBlankとF=タイル/frame(3 VBlank換算)を表示。
# RUNS>0はさらにR=run数とE=1024語転送のstopwatch tickを表示。結果はBUDGETS.md参照。
DMABENCH_DELAY ?= 0
DMABENCH_RUNS ?= 0
DMABENCH_REPAIR ?= 1
DMABENCH_RUN_TAG := $(if $(filter-out 0,$(DMABENCH_RUNS)),_wr$(DMABENCH_RUNS)$(if $(filter 1,$(DMABENCH_REPAIR)),fix,nofix),)
DMABENCH_TAG := h40$(if $(filter-out 0,$(DMABENCH_DELAY)),d$(DMABENCH_DELAY),)$(DMABENCH_RUN_TAG)
dmabench: check-tools $(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).iso $(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).cue
	@cp $(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).iso $(OUT_DIR)/DMABENCH.iso
	@cp $(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).cue $(OUT_DIR)/DMABENCH.cue

$(OUT_DIR)/dmabench_ip_$(DMABENCH_TAG).o: $(BOOT_DIR)/dmabench_ip.s $(BOOT_DIR)/security.bin $(BOOT_DIR)/dbgfont.bin | setup
	$(AS) $(ASFLAGS) --defsym DELAY_LINES=$(DMABENCH_DELAY) --defsym RUNS=$(DMABENCH_RUNS) --defsym REPAIR=$(DMABENCH_REPAIR) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/dmabench_ip_$(DMABENCH_TAG).bin: $(OUT_DIR)/dmabench_ip_$(DMABENCH_TAG).o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/dmabench_boot_$(DMABENCH_TAG).bin: $(OUT_DIR)/dmabench_ip_$(DMABENCH_TAG).bin $(OUT_DIR)/cdcbench_sp.bin $(BOOT_DIR)/dmabench_boot.s
	cp $(OUT_DIR)/dmabench_ip_$(DMABENCH_TAG).bin $(OUT_DIR)/dmabench_ip.bin
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/dmabench_boot.s -o $(OUT_DIR)/dmabench_boot_$(DMABENCH_TAG).out
	$(OBJCOPY) -O binary $(OUT_DIR)/dmabench_boot_$(DMABENCH_TAG).out $@

$(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).iso: $(OUT_DIR)/dmabench_boot_$(DMABENCH_TAG).bin
	@mkdir -p $(OUT_DIR)/disc_dmabench
	@printf "dmabench\n" > $(OUT_DIR)/disc_dmabench/README.TXT
	@rm -f $@ $(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "DMABENCH" -o $@ $(OUT_DIR)/disc_dmabench

$(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).cue: $(OUT_DIR)/DMABENCH_$(DMABENCH_TAG).iso
	@rm -f $@
	@printf 'FILE "DMABENCH_$(DMABENCH_TAG).iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- cpuvrambench: VBLANK中 CPU→VRAM data port 書き込みスループット実測(再利用可能) ---
# 使い方: make cpuvrambench
# 左上に W=語/vblank F=タイル/コマ(3vblank換算) を表示。結果は BUDGETS.md 参照。
CPUVRAMBENCH_TAG := h40
cpuvrambench: check-tools $(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).iso $(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).cue
	@cp $(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).iso $(OUT_DIR)/CPUVRAMBENCH.iso
	@cp $(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).cue $(OUT_DIR)/CPUVRAMBENCH.cue

$(OUT_DIR)/cpuvrambench_ip_$(CPUVRAMBENCH_TAG).o: $(BOOT_DIR)/cpuvrambench_ip.s $(BOOT_DIR)/security.bin $(BOOT_DIR)/dbgfont.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/cpuvrambench_ip_$(CPUVRAMBENCH_TAG).bin: $(OUT_DIR)/cpuvrambench_ip_$(CPUVRAMBENCH_TAG).o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/cpuvrambench_boot_$(CPUVRAMBENCH_TAG).bin: $(OUT_DIR)/cpuvrambench_ip_$(CPUVRAMBENCH_TAG).bin $(OUT_DIR)/cdcbench_sp.bin $(BOOT_DIR)/cpuvrambench_boot.s
	cp $(OUT_DIR)/cpuvrambench_ip_$(CPUVRAMBENCH_TAG).bin $(OUT_DIR)/cpuvrambench_ip.bin
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/cpuvrambench_boot.s -o $(OUT_DIR)/cpuvrambench_boot_$(CPUVRAMBENCH_TAG).out
	$(OBJCOPY) -O binary $(OUT_DIR)/cpuvrambench_boot_$(CPUVRAMBENCH_TAG).out $@

$(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).iso: $(OUT_DIR)/cpuvrambench_boot_$(CPUVRAMBENCH_TAG).bin
	@mkdir -p $(OUT_DIR)/disc_cpuvrambench
	@printf "cpuvrambench\n" > $(OUT_DIR)/disc_cpuvrambench/README.TXT
	@rm -f $@ $(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "CPUVRAMBENCH" -o $@ $(OUT_DIR)/disc_cpuvrambench

$(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).cue: $(OUT_DIR)/CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).iso
	@rm -f $@
	@printf 'FILE "CPUVRAMBENCH_$(CPUVRAMBENCH_TAG).iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- Phase B2: 差分ストリーム再生(単バッファ, BODY.DAT を連続供給) ---

movieplay-internal: check-tools $(MOVIEPLAY_ISO) $(MOVIEPLAY_CUE)

# Build one specialized player pair for the resident SP slot. The multi-video
# orchestrator invokes this once per manifest entry and copies the resulting
# binaries under distinct ISO filenames.
movieplay-module: check-tools moviepack $(MOVIEPLAY_BUILD_DIR)/movieplay_ip.bin $(MOVIEPLAY_BUILD_DIR)/movieplay_sp.bin

MENU_CONFIG ?=
# The multi-video disc is a playback deliverable: its players always build as
# release, so the target takes no DEBUG selection.
multi-disc: check-tools
	@test -n "$(MENU_CONFIG)" || (echo "MENU_CONFIG is required; for example: make multi-disc MENU_CONFIG=menus/menu.toml" >&2; exit 1)
	$(PYTHON) tools/multimovie_build.py build \
		--manifest "$(MENU_CONFIG)" \
		--security-region "$(SECURITY_REGION)" --marsdev "$(MARSDEV)" \
		--m68k-prefix "$(M68K_PREFIX)" --python "$(PYTHON)" \
		--mkisofs "$(MKISOFS)"

# A disc build must never trust stream files left by another stream layout,
# profile, or decision log.  Pack from the authenticated current decisions on
# every build, removing the complete old set first so a failed pack cannot fall
# through to a stale disc.
moviepack: check-tools $(SP_EXTENSION_BIN) | movieplay-setup
	@rm -f $(MOVIEPACK_OUTPUTS) $(PLAYER_CONSTANTS)
	$(PYTHON) tools/pack_stream.py --config "$(CONFIG)" \
		--sp-extension "$(SP_EXTENSION_BIN)" --verify

$(MOVIEPACK_OUTPUTS): moviepack
	@test -f $@

ISO_HOLD_N ?= 0
# Diagnostic-only continuous-read qualification for the reclaimed resident-SP
# tail. The diagnostic relocates two pending destinations above PrgBuf and
# rejects streams that could need the normal third destination, leaving the
# complete 0x7400..0x7FFF interval marker-owned.
ISO_VERIFY_SP_TAIL ?= 0
# Main-CPU straight-line bitmap handlers. Full-playback validation is
# complete; MAIN_CODEGEN=0 keeps
# the byte-identical reference player available for fallback/A-B diagnostics.
MAIN_CODEGEN ?= 1
# Bind player hot constants to this profile's HEADER.DAT.  Set to 0 only for
# the generic runtime-header reference player used in A/B diagnostics.
PLAYER_SPECIALIZE ?= 1
# DEBUG changes assembler flags without changing a source timestamp. Force this
# small object to rebuild so `make disc DEBUG=1` can never reuse a release object
# (or vice versa).
movieplay-force:

$(PLAYER_CONSTANTS): $(MOVIEPLAY_STREAM_DIR)/HEADER.DAT tools/player_constants.py tools/cavc_routing.py tools/ima_adpcm.py | movieplay-setup
	$(PYTHON) tools/player_constants.py $< --output $@

$(SP_EXTENSION_OBJ): $(BOOT_DIR)/movieplay_sp_ext.s $(CFG_DIR)/sp_ext.ld tools/av_config.py tools/ima_adpcm.py movieplay-force | movieplay-setup
	$(AS) $(ASFLAGS) $(if $(filter 1,$(ISO_VERIFY_SP_TAIL)),--defsym ISO_VERIFY_SP_TAIL=1) -I$(BOOT_DIR) $< -o $@

$(SP_EXTENSION_BIN): $(SP_EXTENSION_OBJ)
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp_ext.ld -o $@ $<

$(SP_EXTENSION_CONSTANTS): $(SP_EXTENSION_BIN) tools/sp_extension.py tools/av_config.py | movieplay-setup
	$(PYTHON) tools/sp_extension.py $< --output $@

# Both region inputs are copied on every build.  Switching SECURITY_REGION
# changes which source file is read without making the copy older than it, so
# a timestamp rule would leave the previous region's security code and header
# fields in place and the mismatch would only show up on the console.
$(MOVIEPLAY_SECURITY): $(BOOT_DIR)/sec_$(SECURITY_REGION).bin movieplay-force | movieplay-setup
	cp $< $@

$(MOVIEPLAY_REGION_INC): $(BOOT_DIR)/region_$(SECURITY_REGION).inc movieplay-force | movieplay-setup
	cp $< $@

$(MOVIEPLAY_DEBUG_FONT): tools/gen_debugfont.py | movieplay-setup
	$(PYTHON) tools/gen_debugfont.py --output $@

$(MOVIEPLAY_BUILD_DIR)/movieplay_ip.o: $(BOOT_DIR)/movieplay_ip.s $(MOVIEPLAY_SECURITY) $(MOVIEPLAY_REGION_INC) $(MOVIEPLAY_STREAM_DIR)/paltab.bin $(MOVIEPLAY_STREAM_DIR)/palidx.bin $(PLAYER_CONSTANTS) $(SP_EXTENSION_CONSTANTS) $(MOVIEPLAY_DEBUG_FONT) $(MOVIEPLAY_MULTI_INCLUDE_DEPS) tools/av_config.py tools/cavc_routing.py tools/ima_adpcm.py tools/sp_extension.py tools/check_player_ring.py $(CONFIG) movieplay-force | movieplay-setup
	$(PYTHON) tools/check_player_ring.py --constants $(PLAYER_CONSTANTS) --extension $(SP_EXTENSION_BIN) --extension-constants $(SP_EXTENSION_CONSTANTS) $(if $(filter 1,$(ISO_VERIFY_SP_TAIL)),--sp-tail-marker)
	$(AS) $(ASFLAGS) $(if $(filter 1,$(DEBUG)),--defsym DEBUG=1) $(if $(filter 1,$(MAIN_CODEGEN)),--defsym MAIN_CODEGEN=1) $(if $(filter 1,$(PLAYER_SPECIALIZE)),--defsym PLAYER_SPECIALIZED=1) $(if $(filter 1,$(MULTI_MENU)),--defsym MULTI_MENU=1) -I$(MOVIEPLAY_BUILD_DIR) -I$(dir $(MULTI_PLAYER_INCLUDE)) -I$(MOVIEPLAY_STREAM_DIR) -I$(BOOT_DIR) $< -o $@

$(BOOT_DIR)/dbgfont.bin: tools/gen_debugfont.py
	$(PYTHON) tools/gen_debugfont.py

$(MOVIEPLAY_BUILD_DIR)/movieplay_ip.bin: $(MOVIEPLAY_BUILD_DIR)/movieplay_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<
	@bytes=$$(wc -c < $@); \
		if [ "$$bytes" -gt 18944 ]; then \
			echo "ERROR: $@ is $$bytes bytes; transient Main IP data must end before 0xFF4A00" >&2; \
			rm -f $@; \
			exit 1; \
		fi

$(MOVIEPLAY_BUILD_DIR)/movieplay_sp.o: $(BOOT_DIR)/movieplay_sp.s $(PLAYER_CONSTANTS) $(SP_EXTENSION_CONSTANTS) $(MOVIEPLAY_MULTI_INCLUDE_DEPS) tools/av_config.py tools/cavc_routing.py tools/ima_adpcm.py tools/sp_extension.py tools/check_player_ring.py harness/pcm_write_pacing/check_pacing.py $(CONFIG) movieplay-force | movieplay-setup
	$(PYTHON) tools/check_player_ring.py --constants $(PLAYER_CONSTANTS) --extension $(SP_EXTENSION_BIN) --extension-constants $(SP_EXTENSION_CONSTANTS) $(if $(filter 1,$(ISO_VERIFY_SP_TAIL)),--sp-tail-marker)
	$(PYTHON) harness/pcm_write_pacing/check_pacing.py
	$(if $(filter 1,$(ISO_VERIFY_SP_TAIL)),$(PYTHON) harness/sp_tail_marker/verify_profile.py --header $(MOVIEPLAY_STREAM_DIR)/HEADER.DAT --max-pending-sectors 2)
	$(AS) $(ASFLAGS) $(if $(filter 1,$(DEBUG)),--defsym DEBUG=1) $(if $(filter-out 0,$(ISO_HOLD_N)),--defsym ISO_HOLD_N=$(ISO_HOLD_N)) $(if $(filter 1,$(ISO_VERIFY_SP_TAIL)),--defsym ISO_VERIFY_SP_TAIL=1) $(if $(filter 1,$(PLAYER_SPECIALIZE)),--defsym PLAYER_SPECIALIZED=1) $(if $(filter 1,$(MULTI_MENU)),--defsym MULTI_MENU=1) -I$(MOVIEPLAY_STREAM_DIR) -I$(MOVIEPLAY_BUILD_DIR) -I$(dir $(MULTI_PLAYER_INCLUDE)) -I$(BOOT_DIR) $< -o $@

$(MOVIEPLAY_BUILD_DIR)/movieplay_sp.bin: $(MOVIEPLAY_BUILD_DIR)/movieplay_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<
	@bytes=$$(wc -c < $@); \
		limit=5120; \
		if [ "$$bytes" -gt "$$limit" ]; then \
			echo "ERROR: $@ is $$bytes bytes; this build reserves $$limit bytes for SP" >&2; \
			rm -f $@; \
			exit 1; \
		fi

$(MOVIEPLAY_BUILD_DIR)/movieplay_boot.bin: $(MOVIEPLAY_BUILD_DIR)/movieplay_ip.bin $(MOVIEPLAY_BUILD_DIR)/movieplay_sp.bin $(BOOT_DIR)/movieplay_boot.s $(MOVIEPLAY_REGION_INC)
	$(AS) $(ASFLAGS) -I$(MOVIEPLAY_BUILD_DIR) -I$(BOOT_DIR) $(BOOT_DIR)/movieplay_boot.s -o $(MOVIEPLAY_BUILD_DIR)/movieplay_boot.out
	$(OBJCOPY) -O binary $(MOVIEPLAY_BUILD_DIR)/movieplay_boot.out $@
	@bytes=$$(wc -c < $@); \
		if [ "$$bytes" -ne 32768 ]; then \
			echo "ERROR: $@ is $$bytes bytes; the complete boot image must be 32768 bytes" >&2; \
			rm -f $@; \
			exit 1; \
		fi

$(MOVIEPLAY_ISO): $(MOVIEPLAY_BUILD_DIR)/movieplay_boot.bin $(MOVIEPLAY_STREAM_DIR)/HEADER.DAT $(MOVIEPLAY_STREAM_DIR)/BODY.DAT | movieplay-setup
	@mkdir -p $(MOVIEPLAY_DISC)
	@printf "delta stream phase B2\n" > $(MOVIEPLAY_DISC)/README.TXT
	@rm -f $(MOVIEPLAY_DISC)/MOVIE.DAT $(MOVIEPLAY_DISC)/HEADER.DAT $(MOVIEPLAY_DISC)/BODY.DAT
	cp $(MOVIEPLAY_STREAM_DIR)/HEADER.DAT $(MOVIEPLAY_DISC)/HEADER.DAT
	cp $(MOVIEPLAY_STREAM_DIR)/BODY.DAT $(MOVIEPLAY_DISC)/BODY.DAT
	@rm -f $@ $(MOVIEPLAY_CUE)
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_DLT" -o $@ $(MOVIEPLAY_DISC)

$(MOVIEPLAY_CUE): $(MOVIEPLAY_ISO)
	@rm -f $@
	@printf 'FILE "$(notdir $(MOVIEPLAY_ISO))" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- Continuous-stream self-test (standalone, IP+SP only, STREAM.DAT on disc) ---
# NOTE: STREAM_FRAMES / STREAM_FRAME_SECTORS must match NUM_FRAMES / FRAME_SECTORS
# in boot/streamtest_sp.s and boot/streamtest_ip.s.
STREAMTEST_DISC := $(OUT_DIR)/disc_streamtest
STREAM_FRAMES ?= 256
STREAM_FRAME_SECTORS ?= 5

streamtest: check-tools $(OUT_DIR)/STREAMTEST.iso $(OUT_DIR)/STREAMTEST.cue

$(OUT_DIR)/streamtest_ip.o: $(BOOT_DIR)/streamtest_ip.s $(BOOT_DIR)/security.bin $(BOOT_DIR)/hexfont.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/streamtest_ip.bin: $(OUT_DIR)/streamtest_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/streamtest_sp.o: $(BOOT_DIR)/streamtest_sp.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/streamtest_sp.bin: $(OUT_DIR)/streamtest_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<

$(OUT_DIR)/streamtest_boot.bin: $(OUT_DIR)/streamtest_ip.bin $(OUT_DIR)/streamtest_sp.bin $(BOOT_DIR)/streamtest_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/streamtest_boot.s -o $(OUT_DIR)/streamtest_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/streamtest_boot.out $@

$(OUT_DIR)/STREAMTEST.iso: $(OUT_DIR)/streamtest_boot.bin tools/gen_streamtest.py
	@mkdir -p $(STREAMTEST_DISC)
	@printf "Continuous stream self-test\n" > $(STREAMTEST_DISC)/README.TXT
	$(PYTHON) tools/gen_streamtest.py --frames $(STREAM_FRAMES) --frame-sectors $(STREAM_FRAME_SECTORS) --output $(STREAMTEST_DISC)/STREAM.DAT
	@rm -f $@ $(OUT_DIR)/STREAMTEST.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_STRM" -o $@ $(STREAMTEST_DISC)

$(OUT_DIR)/STREAMTEST.cue: $(OUT_DIR)/STREAMTEST.iso
	@rm -f $@
	@printf 'FILE "STREAMTEST.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- RF5C164 PCM self-test (standalone, IP+SP only, looping tone) ---
PCMTEST_DISC := $(OUT_DIR)/disc_pcmtest

pcmtest: check-tools $(OUT_DIR)/PCMTEST.iso $(OUT_DIR)/PCMTEST.cue

$(OUT_DIR)/pcmtest_ip.o: $(BOOT_DIR)/pcmtest_ip.s $(BOOT_DIR)/security.bin $(BOOT_DIR)/hexfont.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/pcmtest_ip.bin: $(OUT_DIR)/pcmtest_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/pcmtest_sp.o: $(BOOT_DIR)/pcmtest_sp.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/pcmtest_sp.bin: $(OUT_DIR)/pcmtest_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<

$(OUT_DIR)/pcmtest_boot.bin: $(OUT_DIR)/pcmtest_ip.bin $(OUT_DIR)/pcmtest_sp.bin $(BOOT_DIR)/pcmtest_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/pcmtest_boot.s -o $(OUT_DIR)/pcmtest_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/pcmtest_boot.out $@

$(OUT_DIR)/PCMTEST.iso: $(OUT_DIR)/pcmtest_boot.bin
	@mkdir -p $(PCMTEST_DISC)
	@printf "RF5C164 PCM self-test\n" > $(PCMTEST_DISC)/README.TXT
	@rm -f $@ $(OUT_DIR)/PCMTEST.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_PCM" -o $@ $(PCMTEST_DISC)

$(OUT_DIR)/PCMTEST.cue: $(OUT_DIR)/PCMTEST.iso
	@rm -f $@
	@printf 'FILE "PCMTEST.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- ADPCM decoder smoke test (standalone, IP+SP only, embedded IMA stream) ---
ADPCMTEST_DISC := $(OUT_DIR)/disc_adpcmtest

adpcmtest: check-tools $(OUT_DIR)/ADPCMTEST.iso $(OUT_DIR)/ADPCMTEST.cue

$(BOOT_DIR)/adpcmtest_font.bin: tools/gen_adpcmtest_font.py
	$(PYTHON) tools/gen_adpcmtest_font.py

$(OUT_DIR)/adpcmtest_ip.o: $(BOOT_DIR)/adpcmtest_ip.s $(BOOT_DIR)/security.bin $(BOOT_DIR)/adpcmtest_font.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/adpcmtest_ip.bin: $(OUT_DIR)/adpcmtest_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/adpcmtest_sp_shell.o: $(BOOT_DIR)/adpcmtest_sp.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/adpcmtest_adpcm.o: $(BOOT_DIR)/adpcmtest_adpcm.c | setup
	$(CC) $(CFLAGS_M68K) -c $< -o $@

$(OUT_DIR)/adpcmtest_tone_ima.bin: tools/gen_adpcmtest_audio.py | setup
	$(PYTHON) tools/gen_adpcmtest_audio.py --pattern --out $@ --rate 22050 --samples 8192

$(OUT_DIR)/adpcmtest_audio.o: $(BOOT_DIR)/adpcmtest_audio.s $(OUT_DIR)/adpcmtest_tone_ima.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/adpcmtest_sp.bin: $(OUT_DIR)/adpcmtest_sp_shell.o $(OUT_DIR)/adpcmtest_adpcm.o $(OUT_DIR)/adpcmtest_audio.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $^

$(OUT_DIR)/adpcmtest_boot.bin: $(OUT_DIR)/adpcmtest_ip.bin $(OUT_DIR)/adpcmtest_sp.bin $(BOOT_DIR)/adpcmtest_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/adpcmtest_boot.s -o $(OUT_DIR)/adpcmtest_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/adpcmtest_boot.out $@

$(OUT_DIR)/ADPCMTEST.iso: $(OUT_DIR)/adpcmtest_boot.bin
	@mkdir -p $(ADPCMTEST_DISC)
	@printf "ADPCM decoder smoke test\n" > $(ADPCMTEST_DISC)/README.TXT
	@rm -f $@ $(OUT_DIR)/ADPCMTEST.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_ADPCM" -o $@ $(ADPCMTEST_DISC)

$(OUT_DIR)/ADPCMTEST.cue: $(OUT_DIR)/ADPCMTEST.iso
	@rm -f $@
	@printf 'FILE "ADPCMTEST.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- 2x CPU-upscale 320x160 / 4-VBlank DMA verification (reuses boot.bin, SP,
#     and the movie PROBE.BIN; only M_INIT.PRG is the upscale Main) ---
UPSCALE_DISC := $(OUT_DIR)/disc_upscale

upscaletest: check-tools setup $(OUT_DIR)/UPSCALE.iso $(OUT_DIR)/UPSCALE.cue

$(OUT_DIR)/upscaletest_main.o: $(BOOT_DIR)/upscaletest_main.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@

$(OUT_DIR)/upscaletest_main.bin: $(OUT_DIR)/upscaletest_main.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/handoff.ld -o $@ $^

$(OUT_DIR)/UPSCALE.iso: $(OUT_DIR)/boot.bin $(OUT_DIR)/upscaletest_main.bin $(DISC_DIR)/PROBE.BIN
	@mkdir -p $(UPSCALE_DISC)
	cp $(OUT_DIR)/upscaletest_main.bin $(UPSCALE_DISC)/M_INIT.PRG
	cp $(DISC_DIR)/PROBE.BIN $(UPSCALE_DISC)/PROBE.BIN
	@printf "upscale 320x160 4-VBlank test\n" > $(UPSCALE_DISC)/README.TXT
	@rm -f $@ $(OUT_DIR)/UPSCALE.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_UPSC" -o $@ $(UPSCALE_DISC)

$(OUT_DIR)/UPSCALE.cue: $(OUT_DIR)/UPSCALE.iso
	@rm -f $@
	@printf 'FILE "UPSCALE.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

# --- ASIC 2x-upscale verification (static frame, Graphics ASIC scaler) ---
ASIC_FRAME ?= 00100
ASIC_DISC := $(OUT_DIR)/disc_asic
# asictest is fixed at 160x80 (20x10 tiles); it keeps its own probe root so it is
# unaffected by the main build's resolution.
ASIC_PROBE_ROOT := $(OUT_DIR)/video/061_asic_160x80

asictest: check-tools setup $(OUT_DIR)/ASIC.iso $(OUT_DIR)/ASIC.cue

$(ASIC_PROBE_ROOT)/palettes.bin: $(OP_SRC) tools/quantize_global4_tiles.py tools/quantize_md_video.py
	$(PYTHON) tools/quantize_global4_tiles.py --input $(OP_SRC) --start 0 --duration 152.866667 --fps 15 --scale-width 160 --scale-height 80 --output-dir $(ASIC_PROBE_ROOT)

$(OUT_DIR)/asic/ASIC.DAT: $(ASIC_PROBE_ROOT)/palettes.bin tools/make_asic_stamps.py | setup
	@mkdir -p $(OUT_DIR)/asic
	$(PYTHON) tools/make_asic_stamps.py \
		--tiles $(ASIC_PROBE_ROOT)/tile/$(ASIC_FRAME).tile \
		--pmap $(ASIC_PROBE_ROOT)/pmap/$(ASIC_FRAME).pmap \
		--pal $(ASIC_PROBE_ROOT)/palettes.bin \
		--out $(OUT_DIR)/asic --dat $(OUT_DIR)/asic/ASIC.DAT

$(OUT_DIR)/asictest_ip.o: $(BOOT_DIR)/asictest_ip.s $(BOOT_DIR)/security.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@
$(OUT_DIR)/asictest_ip.bin: $(OUT_DIR)/asictest_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<

$(OUT_DIR)/asictest_sp.o: $(BOOT_DIR)/asictest_sp.s $(OUT_DIR)/asic/ASIC.DAT | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@
$(OUT_DIR)/asictest_sp.bin: $(OUT_DIR)/asictest_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<

$(OUT_DIR)/asictest_boot.bin: $(OUT_DIR)/asictest_ip.bin $(OUT_DIR)/asictest_sp.bin $(BOOT_DIR)/asictest_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/asictest_boot.s -o $(OUT_DIR)/asictest_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/asictest_boot.out $@

$(OUT_DIR)/ASIC.iso: $(OUT_DIR)/asictest_boot.bin
	@mkdir -p $(ASIC_DISC)
	@printf "asic 2x upscale test\n" > $(ASIC_DISC)/README.TXT
	@rm -f $@ $(OUT_DIR)/ASIC.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "SCFMV_ASIC" -o $@ $(ASIC_DISC)

$(OUT_DIR)/ASIC.cue: $(OUT_DIR)/ASIC.iso
	@rm -f $@
	@printf 'FILE "ASIC.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@

clean:
	@rm -rf $(OUT_DIR)
	@rm -f $(BOOT_DIR)/security.bin

# --- PRG-RAM 書込テスト(CD読込の有無で高位PRGへCPU書込できるか) ---
prgtest: check-tools $(OUT_DIR)/PRGTEST.iso $(OUT_DIR)/PRGTEST.cue

$(OUT_DIR)/prgtest_ip.o: $(BOOT_DIR)/prgtest_ip.s $(BOOT_DIR)/security.bin | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@
$(OUT_DIR)/prgtest_ip.bin: $(OUT_DIR)/prgtest_ip.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/ip.ld -o $@ $<
$(OUT_DIR)/prgtest_sp.o: $(BOOT_DIR)/prgtest_sp.s | setup
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $< -o $@
$(OUT_DIR)/prgtest_sp.bin: $(OUT_DIR)/prgtest_sp.o
	$(LD) $(LDFLAGS) -T $(CFG_DIR)/sp.ld -o $@ $<
$(OUT_DIR)/prgtest_boot.bin: $(OUT_DIR)/prgtest_ip.bin $(OUT_DIR)/prgtest_sp.bin $(BOOT_DIR)/prgtest_boot.s
	$(AS) $(ASFLAGS) -I$(BOOT_DIR) $(BOOT_DIR)/prgtest_boot.s -o $(OUT_DIR)/prgtest_boot.out
	$(OBJCOPY) -O binary $(OUT_DIR)/prgtest_boot.out $@
$(OUT_DIR)/PRGTEST.iso: $(OUT_DIR)/prgtest_boot.bin
	@mkdir -p $(OUT_DIR)/disc_prgtest
	@printf "prg write test\n" > $(OUT_DIR)/disc_prgtest/README.TXT
	@rm -f $@ $(OUT_DIR)/PRGTEST.cue
	$(MKISOFS) -iso-level 1 -G $< -pad -V "PRGTEST" -o $@ $(OUT_DIR)/disc_prgtest
$(OUT_DIR)/PRGTEST.cue: $(OUT_DIR)/PRGTEST.iso
	@rm -f $@
	@printf 'FILE "PRGTEST.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n' > $@
