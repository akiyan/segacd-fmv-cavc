# Palette-boundary diagnosis

A VRAM pattern contains palette indices, not independent RGB colours. A CRAM
switch must not reinterpret surviving cells under an incompatible palette.
Compare exact cell/pattern/CRAM states on both sides of a boundary; a visually
clean source preview alone cannot prove a correct packed stream.

Current stream qualification uses `harness/pattern_supply/verify.py` against
HEADER.DAT/BODY.DAT and the matching decisions. `harness/palette_capacity`
provides a current-format fixture and actual LOGVDP all-cell/palette comparison.
Use HUD frame identity to align real captures; wall-clock guesses drift, and
window screenshots are not pixel-exact. Distinguish the intended old/new states
from old-content/new-CRAM and new-content/old-CRAM combinations when diagnosing
a flash.

Monolithic TTRC v1 decoding is outside the active format contract and has no
maintained test path. No compatibility with that layout is claimed.
