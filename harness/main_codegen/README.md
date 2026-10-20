# Main-CPU generated-handler cycle diagnostics

The player emits bitmap handlers into Main RAM. `PLAYER.md` describes the
active allocation. Qualify emitter changes against the built player and actual
handler memory or playback traces; a second Python emitter is not evidence
that the assembly emitted those bytes.

Measure the per-frame instruction cost against a real packed stream with:

```sh
tools/python.sh harness/main_codegen/measure_cycles.py \
  --header out/lunar/HEADER.DAT \
  --body out/lunar/BODY.DAT
```

The cycle model follows the actual word-displacement branches and indexed jump
shown by `m68k-elf-objdump`. Its timings come from the official
[MC68000 User's Manual](https://www.nxp.com/docs/en/reference-manual/MC68000UM.pdf),
Section 8, Tables 8-1, 8-2, 8-4, 8-5, 8-6, 8-7, 8-9, and 8-10. It measures the
packed mask distribution for every frame and excludes the one-time startup
generator. Platform wait states are also outside this instruction-cycle model.
