# Resident SP tail marker qualification

This diagnostic verifies that Sub PRG-RAM `0x7400..0x7FFF` remains readable
during a complete continuous `BODY.DAT` transfer.

Build a DEBUG disc with:

```sh
make disc CONFIG=tmp/issue83-bad-apple-75s.toml \
  DEBUG=1 ISO_VERIFY_SP_TAIL=1
```

The diagnostic build omits the third resident Word-sector pending buffer so
the complete 3 KiB interval is free. `verify_profile.py` therefore rejects any
packed route that can need more than the two fixed pending buffers. The
boot-time Sub extension fills the interval with address-derived marker words
and installs a small checker in the already-qualified `0x9700` scratch page.
The timed player checks 64 bytes per content frame, covering the complete
interval every 48 frames. A mismatch increments the existing control-desync
counter, so the ordinary full-loop HUD gate records a failure without adding a
new playback decision or HUD field.

Use a full fixed-Replay recording and require:

- every expected content frame is present;
- `sector_slip`, `control_desync`, and `audio_resync` remain zero;
- the HUD gate reports `PASS`.

This test proves read stability only. The released player does not retain the
marker fill, checker, or per-frame checking work.
