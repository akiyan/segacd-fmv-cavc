# Managed GPGX LOGVDP core

## Goal

This harness builds the Genesis Plus GX libretro core used by the recording
tools instead of relying on a distribution-installed core. It enables the
upstream `LOGVDP` trace so each RetroArch run can report the exact VDP DMA
timing model, including:

- V-counter and master-cycle position at each DMA update;
- active-display or blanking transfer rate;
- accesses processed and remaining DMA length;
- calculated cycles until DMA completion; and
- 68000 bus-freeze duration.

The stable local install path is:

```text
vendor/gpgx-logvdp/genesis_plus_gx_logvdp_libretro.so
```

Everything under `vendor/gpgx-logvdp/` is generated and git-ignored. The core
binary, build log, and manifest must not be committed.

## Build and verify

From the repository root:

```sh
harness/gpgx_logvdp/build.sh
harness/gpgx_logvdp/build.sh --check
```

Use `--force` to fetch and rebuild even when the installed core and manifest
already pass:

```sh
harness/gpgx_logvdp/build.sh --force
```

The manifest is a two-column UTF-8 TSV containing the upstream commit, build
settings, compiler, binary size, and SHA-256. A normal build is a no-op when
that receipt and the installed binary are valid.

The build pins upstream commit
`46652c7fd74bd64a99f624b0bd53a768de0ff672`, dated 2022-11-28. This keeps the
emulator generation aligned with the distribution core used for the existing
playback qualifications. CHD support is disabled, as it was in that package;
the current CUE/BIN recording path does not use CHD. The bundled Tremor decoder
is used instead of a distribution `libvorbisfile`, so the generated core does
not inherit that package dependency.

No upstream source patch is applied. `LOGVDP` is selected through the upstream
Makefile's `CODE_DEFINES` input. The pinned `vdp_ctrl.c` calls the existing
frontend logger without importing its declaration, which current C compilers
reject. The build therefore force-includes
`harness/gpgx_logvdp/logvdp_error_decl.h`; this supplies only the matching
function declaration and does not change emulator logic.

## Runtime logs

`tools/run_headless.sh` uses the managed core by default and writes the
RetroArch/core output to:

```text
<OUTDIR>/retroarch_<tag>.log
```

The upstream trace can be isolated from a completed run with:

```sh
rg 'DMA type|DMA ends|CPU frozen' \
  <OUTDIR>/retroarch_<tag>.log
```

`LOGVDP` is an upstream compile-time switch, not a runtime option. It also logs
ordinary VDP register, status, and data-port activity, so a complete playback
log can be large. Keep the raw log until the DMA diagnosis is extracted; do
not treat host wall-clock slowdown from log output as a change to emulated
cycle accounting.

Set `CORE=/absolute/path/to/another_libretro_core.so` only for an explicit A/B.
There is no automatic fallback to a system Genesis Plus GX package.
