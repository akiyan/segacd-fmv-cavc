# O_LOADS v2 equivalence proof

The full-stream pattern-supply verifier models both sides of the player
handoff independently:

1. It walks the real version-23 `HEADER.DAT` and `BODY.DAT` and applies each
   compact four-byte source run directly, matching the pre-v2 semantic path.
2. It expands the same runs into exact 22-byte `O_LOADS v2` records, including
   source resolution, VDP register values, inline Prg payloads, parity WordBuf
   cursors, and ring wrap.
3. It consumes those records with Main's single-cursor rules and compares the
   resulting VRAM state after every frame.
4. It recomputes the even/odd byte peaks and requires exact equality with the
   two PSUP v4 fields that size the physical Word-RAM banks.

Run it against one completed encode:

```sh
tools/python.sh harness/pattern_supply/verify.py \
  --header out/PROFILE/HEADER.DAT \
  --body out/PROFILE/BODY.DAT \
  --decisions /dev/shm/segacd-fmv-ttrc/sim-.../data/decisions.pkl
```

Success prints `O_LOADS v2 equivalence: OK` after the ordinary full display
replay. Small record-layout and corruption checks also run under
`tools/test_loads_v2.py`.
