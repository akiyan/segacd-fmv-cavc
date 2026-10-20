---
name: priorities
description: "Inspect or tune tile-update priority weights and selection order in the current encoder when requested, including /priorities."
---

# Tile update priorities

Read current `tools/sim.py` priority computation and its sort/admission call
sites. Present the actual weights and ordering in a small table with plain
explanations. Distinguish a priority score from a hard capacity/deadline limit.
Do not maintain another formula or default-value list in this skill.

For tuning, name the affected decision layer, preserve target raster/cadence/
cold cap/palette settings, and compare requested work with Miss distributions
and visible results. Do not infer benefit from a larger score or lower wait
counter alone. Use existing artifacts or an authorized encode; a question about
weights is not permission for a costly benchmark. Update owning code/comments
and relevant CONFIG documentation when behavior changes.
