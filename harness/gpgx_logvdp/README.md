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

This removes the runtime dependency on a distribution Genesis Plus GX package;
the generated binary links only the host C and math libraries. RetroArch and
standard build tools (`git`, `make`, and a C compiler) remain host
prerequisites.

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
harness/gpgx_logvdp/test_compact_log.sh
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

`tools/run_headless.sh` uses the managed core by default. After a successful
run it keeps the DMA trace and unexpected core errors in:

```text
<OUTDIR>/retroarch_<tag>.log
```

The complete upstream trace, including every CPU VDP data-port access, remains
available as a fast-compressed sidecar:

```text
<OUTDIR>/gpgx_logvdp_<tag>.log.gz
```

`LOGVDP` is an upstream compile-time switch, not a runtime option. It also logs
ordinary VDP register, status, and data-port activity, so a complete playback
log can be large. `harness/gpgx_logvdp/compact_log.sh` preserves that evidence
with `gzip -1` and removes only the known non-DMA `LOGVDP` chatter from the
plain RetroArch log. It retains any unrecognized core error. Do not treat host
wall-clock slowdown from log output as a change to emulated cycle accounting.

Inspect the standard DMA trace directly:

```sh
rg 'DMA type|DMA ends|CPU frozen' <OUTDIR>/retroarch_<tag>.log
```

Inspect any part of the complete trace without expanding it on disk:

```sh
gzip -cd <OUTDIR>/gpgx_logvdp_<tag>.log.gz | rg 'VDP register'
```

Set `CORE=/absolute/path/to/another_libretro_core.so` only for an explicit A/B.
There is no automatic fallback to a system Genesis Plus GX package.

## Qualification

On 2026-07-29, the managed core was compared with the previously used Ubuntu
core by playing one 3000-frame input Replay through both. Each side recorded
the same 2880 emulator frames, including Mega-CD startup and an eight-second
H40 DEBUG movie:

- managed core SHA-256:
  `51cfd71f338865288e274b271b8ce0d9a1d3dc415688f14db963a29555d9b4ac`;
- Ubuntu core SHA-256:
  `40791618c03ea3f1fa04d925835b10671c8429c5ff9919ef58401303c57df920`;
- all 2880 decoded video frames equal, hash-sequence SHA-256
  `190c8bae28f16284fe6f7cb56de71799dd139606735e463bae06b4eb92baafe8`;
- all 2,119,529 decoded stereo PCM sample frames equal, PCM SHA-256
  `d3ee380194dc63492f44b790186e7a63e6e6353eb61b85c8506f5e551d345c2e`;
- video/audio metadata, packet counts, PTS, DTS, and durations equal; and
- managed LOGVDP recording ran at 7.90x versus 15.82x for the package core.

The managed run's 702,005,465-byte complete log became a 57,731,453-byte gzip
sidecar and a 724,875-byte compact log. DMA update, completion, and CPU-freeze
counts were unchanged by compaction. This qualification establishes equivalent
output for the active CUE/BIN FMV path; it does not claim equivalence for CHD or
external Ogg CD-audio inputs.
