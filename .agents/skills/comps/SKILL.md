---
name: comps
description: "Inspect or tune resident-reuse thresholds Same/Near/Flbk in tools/sim.py when requested, including /comps."
---

# Resident reuse thresholds

Read the current comparison code in `tools/sim.py` and any helper it calls.
Report actual setting names, defaults, units and call-site meaning in a compact
table; do not copy values from a skill prompt or assume every threshold uses
one scale. Explain smaller/greater strictness for each specific comparison.

Distinguish VRAM resident reuse from Prg/WordBuf/Dic physical sources. State
which decision tier a proposed edit changes and keep unrelated quality settings
fixed. Apply requested changes to their single owner and relevant documentation.
For empirical comparisons, reuse matching artifacts or run only the authorized
experiment. Compare request/Miss distributions and visual evidence; do not use
starved-frame percentage as a quality score. An explanatory request does not
require a new encode, timeline, commit or upload.
