# Stock BIOS security-path analysis

This harness checks whether a bootable homebrew disc can avoid the stock
Mega-CD / Sega CD licence presentation while leaving the console BIOS
unmodified. The intended result is an accurate unlicensed presentation, not a
claim that the software was produced under a Sega licence.

The analysis scripts read a user-supplied BIOS locally. No BIOS-derived module
or patched BIOS is stored in the repository. Isolated experiment discs are
written under `out/security-skip/` and never replace normal build artifacts.

## Extracting the Sub-CPU BIOS modules

The stock BIOSes store their Sub-CPU modules in Kosinski-compressed form. The
two extractors reproduce the BIOS decoder and place the modules at their real
Sub PRG-RAM addresses so they can be disassembled locally:

```sh
tools/python.sh harness/security_skip/extract_jp_sub_bios.py \
  original/jp_mcd2_9212.bin /tmp/jp-sub-bios

tools/python.sh harness/security_skip/extract_us_sub_bios.py \
  original/us_scd1_9210.bin /tmp/us-sub-bios
```

| Region | BIOS ROM source | Sub PRG-RAM destination |
|---|---:|---:|
| JP | `0x16000` | `0x00000` |
| JP | `0x13400` | `0x06000` |
| JP | `0x1A000` | `0x18000` |
| US | `0x15800` | `0x00000` |
| US | `0x13400` | `0x06000` |
| US | `0x19800` | `0x18000` |

The byte-level checkers perform the same decompression in memory and assert
the relevant classifier, comparison loop, launch path, licence call, display
strings, and wait-loop instructions without writing BIOS-derived output:

```sh
tools/python.sh harness/security_skip/verify_jp_bios.py \
  original/jp_mcd2_9212.bin

tools/python.sh harness/security_skip/verify_us_bios.py \
  original/us_scd1_9210.bin
```

## Verified Japanese Mega-CD 2 BIOS path

The low Sub-CPU module contains the disc classifier and the complete reference
security program. Its boot-disc path is:

1. `0x3B78..0x3B9A` compares the first 16 bytes of each candidate sector with
   `SEGADISC`, `SEGABOOTDISC`, `SEGADATADISC`, and `SEGADISCSYSTEM`.
2. `0x3BBC` advances the matched sector buffer by `0x200` bytes.
3. `0x3DDC..0x3DF8` compares 170 words (340 bytes) against the reference
   security program embedded at Sub PRG-RAM `0x3DFA`.
4. `0x3D5E..0x3D76` copies the first 1536 IP bytes from that same sector buffer
   into the boot destination. The checked source and loaded source are the
   same ISO object.

The checked range ends immediately before security offset `0x154`. The final
word at offset `0x154` is not compared. The otherwise exact security program
writes this word to Sub PRG-RAM `0x0528`; the standard value `0x6006` changes
the resident wait loop from `bra.s 0x0524` to `bra.s 0x0530`, which resumes the
Sub BIOS boot path. The Main-CPU call to BIOS licence routine `0x0364` is at
security offset `0x26`, inside the byte-exact checked range.

The remaining loader and display path has also been checked statically and
with a fixed 900-frame Genesis Plus GX trace using the unmodified BIOS:

- `SEGADISC` and `SEGADATADISC` skip the verifier, but the BIOS classifies
  both as non-boot discs and never reaches the IP loader.
- `SEGABOOTDISC` passes the same verifier as `SEGADISCSYSTEM` and reaches the
  same Main-CPU launch: BIOS `0x05E8` jumps to `0xFFFF0000`. The `IP_Entry`
  header field does not replace that launch address.
- The continuation IP loader at Sub PRG-RAM `0x3C7C` receives the `0xFFFF`
  left by the security comparison loop and reads a fixed 32 sectors (64 KiB).
  `IP_Size` is only used by the `IP_Addr=0x200`, `IP_Size=0x600` no-read
  special case. It cannot request enough data to wrap the 256-KiB Word-RAM
  CDC DMA window and overwrite the checked prefix.
- Main BIOS `0x603C..0x6102` consumes the display data beginning at security
  offset `0x2E`. Its image and both licence strings end at checked offset
  `0x153`, followed by their `0xFF` terminator. The routine then waits exactly
  180 frames. It does not consume the unchecked tail or later IP bytes.

These paths leave no deterministic disc-only way to boot through the
unmodified Japanese Mega-CD 2 BIOS without executing its licence display.
Changing or replacing the BIOS, using an external loader, or relying on an
undefined physical read race are different execution environments; the race
is not a reproducible disc-build target.

## Verified US Sega CD 1.10 BIOS path

The US low Sub-CPU module uses the same four disc identifiers, but its security
check is stricter:

1. The classifier strings are at Sub PRG-RAM `0x3F46`, and the classifier path
   reaches the verifier at `0x4020` for `SEGABOOTDISC` and `SEGADISCSYSTEM`.
2. The verifier at `0x4222` initializes its counter to `0x02C1` and executes a
   word compare with `DBNE`. This compares 706 words, exactly all 1412 bytes
   (`0x584`) of `boot/sec_us.bin`, against the embedded reference at `0x423C`.
   There is no unchecked security tail.
3. The first-IP copy at `0x419C` leaves `d1.w=0xFFFF`. The continuation loader
   at `0x4068` rounds that value to a fixed 32-sector (64-KiB) read.
4. Main BIOS `0x51E2` copies 32 KiB from Word RAM to `0xFFFF0000`, selects
   state 20, and the state-table entry at `0x05E6` jumps to `0xFFFF0000`.
   `IP_Entry` is not used as a replacement entry point.
5. The standard security program calls BIOS entry `0x0364` at security offset
   `0x04`. That stub enters the licence routine at BIOS `0x521A`. Both US
   licence strings are inside the fully checked security program. The final
   display hold loop initializes `DBF` with `0x00F0`, so that loop executes
   241 iterations in addition to the preceding presentation stages.

A replay-free fixed 900-frame run completes with the stock US BIOS on Genesis
Plus GX commit `27426f00aa68f9f358c86919e8a40985326fa05b`. A trace-instrumented
build based on commit `46652c7fd74bd64a99f624b0bd53a768de0ff672` reaches Sub PCs
`0x4020` and `0x421E`, reports the 32-sector continuation at `0x4108`, then
reaches Main PCs `0x05E6`, `0xFFFF0000`, and `0x521A` in that order. A
JP-recorded input Replay must not be reused for this US boot test; the regions
have different startup timing and the stale Replay is not part of the BIOS
behavior under test.

The US BIOS therefore has no modifiable security byte at all. Its two
verifier-skipping identifiers are non-boot classifications, while both boot
identifiers compare the complete presentation program and then use the same
fixed launch path. There is no deterministic disc-only licence-display bypass
through this unmodified stock BIOS.

## Isolated fast experiment builds

### Japanese build

`build_jp_experiment.py` creates a separate ISO/CUE pair without simulating,
packing, assembling, or changing normal disc artifacts. It verifies all 340
BIOS-checked bytes before and after the build and changes only the unchecked
final word by default:

```sh
tools/python.sh harness/security_skip/build_jp_experiment.py \
  out/issue32-smoke.iso --name tail-6006 --tail-word 6006
```

An optional `--boot-image` replaces the complete 32-KiB boot area while still
requiring the byte-exact checked range. The `--disc-id` option is limited to
the four exact identifiers embedded in the BIOS:

```sh
tools/python.sh harness/security_skip/build_jp_experiment.py \
  out/issue32-smoke.iso --name disc-id --disc-id disc
```

### US build

`build_us_experiment.py` provides the same isolated path for an existing US
ISO. Because the US BIOS checks all security bytes, this builder has no
security-patch option. It permits only a code-defined disc ID and an optional
32-KiB boot image whose complete 1412-byte security program remains exact:

```sh
tools/python.sh harness/security_skip/build_us_experiment.py \
  out/bad-apple_us_release.iso --name baseline

tools/python.sh harness/security_skip/build_us_experiment.py \
  out/bad-apple_us_release.iso --name nonboot-disc --disc-id disc
```

Every invocation writes a TSV receipt containing the source and output hashes,
the exact checked-byte count, the disc ID, and whether that ID enters the
security verifier. A verifier-skipping output is an explicit non-boot control
case, not a successful display-skip build.

Run a US experiment without a cross-region Replay:

```sh
BIOS_REGION=us OUTDIR=/tmp/security-skip-us \
  tools/run_headless.sh \
  out/security-skip/bad-apple_us_release_ussec_baseline.cue \
  --tag baseline --max-frames 900
```

Run the builder regression tests with:

```sh
tools/python.sh -m unittest \
  harness/security_skip/test_build_jp_experiment.py \
  harness/security_skip/test_build_us_experiment.py
```
