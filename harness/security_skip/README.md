# Japanese security-code analysis

`extract_jp_sub_bios.py` reproduces the stock Japanese Mega-CD 2 BIOS's own
Kosinski decompression calls at Main-CPU addresses `0x06A4..0x06E8`. It
extracts the three embedded Sub-CPU modules at their real PRG-RAM addresses so
the disc-recognition and security-code path can be disassembled statically.

```sh
tools/python.sh harness/security_skip/extract_jp_sub_bios.py \
  original/jp_mcd2_9212.bin /tmp/jp-sub-bios
```

`verify_jp_bios.py` checks the relevant opcodes, embedded security reference,
launch address, display strings, and wait count directly without writing any
BIOS-derived output:

```sh
tools/python.sh harness/security_skip/verify_jp_bios.py \
  original/jp_mcd2_9212.bin
```

The extraction inputs and destinations come directly from the BIOS:

| BIOS ROM source | Sub PRG-RAM destination |
|---:|---:|
| `0x16000` | `0x00000` |
| `0x13400` | `0x06000` |
| `0x1A000` | `0x18000` |

## Verified Japanese BIOS path

The low Sub-CPU module contains the disc classifier and the complete reference
security program. Its boot-disc path is:

1. `0x3B78..0x3B9A` compares the first 16 bytes of each candidate sector with
   `SEGADISC`, `SEGABOOTDISC`, `SEGADATADISC`, and `SEGADISCSYSTEM`.
2. `0x3BBC` advances the matched sector buffer by `0x200` bytes.
3. `0x3DDC..0x3DF8` compares 170 words (340 bytes) against the reference
   security program embedded at Sub PRG-RAM `0x3DFA`.
4. `0x3D5E..0x3D76` copies the first 1536 IP bytes from that same sector buffer
   into the boot destination. The checked source and the loaded source are not
   separate ISO objects.

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
Doing so would require changing or replacing the BIOS, adding an external
loader, or relying on an undefined physical read race; the latter is not a
reproducible build target.

## Isolated fast experiment build

`build_jp_experiment.py` creates a separate ISO/CUE pair under
`out/security-skip/` without simulating, packing, assembling, or changing the
normal disc artifacts. It verifies all 340 BIOS-checked bytes before and after
the build and changes only the unchecked final word by default.

```sh
tools/python.sh harness/security_skip/build_jp_experiment.py \
  out/issue32-smoke.iso --name tail-6006 --tail-word 6006
```

An optional `--boot-image` replaces the complete 32-KiB boot area while still
requiring the byte-exact checked range. This supports later IP/SP experiments
without rebuilding or overwriting the cached movie stream. Every invocation
writes a TSV receipt containing both ISO hashes, the exact tail word, the disc
ID, and whether that ID enters the security verifier.

The disassembly also proves that only the `SEGABOOTDISC` and
`SEGADISCSYSTEM` classifier results call the verifier. The isolated builder
therefore accepts `--disc-id disc|boot|data|system`, limited to the four exact
IDs embedded in this BIOS. This option exists to test the BIOS's other
code-defined paths without arbitrary marker fuzzing:

```sh
tools/python.sh harness/security_skip/build_jp_experiment.py \
  out/issue32-smoke.iso --name disc-id --disc-id disc
```

Passing the static comparison is necessary but does not prove that a tail-word
experiment resumes boot correctly. Each candidate still needs a fixed-frame
run with the unmodified Japanese BIOS.
