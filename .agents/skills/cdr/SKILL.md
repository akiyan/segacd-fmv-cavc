---
name: cdr
description: "Write an existing Sega CD ISO to a blank CD-R when explicitly requested, including /cdr or burn the ISO. A general wish to test real hardware is not a request to spend a disc."
---

# Burn a CD-R

This Linux harness requires cdrskin, a CD-R-capable drive and a blank medium.
Use an existing requested ISO; prefer DEBUG=0 for HUD-free playback. Do not
re-encode source video as a side effect of burning.

Run the default dry check, inspect image/region, capacity, blank state and rated
speed, then burn when they match the requested disc/console:

```sh
tools/python.sh .agents/skills/cdr/scripts/burn_iso.py \
  out/PROFILE_release.iso --expect-region J
tools/python.sh .agents/skills/cdr/scripts/burn_iso.py \
  out/PROFILE_release.iso --expect-region J --burn
```

Use the actual known region. The harness writes one Mode1/2048 track in
Disc-At-Once, clamps speed to the medium's ATIP range and refuses nonblank media.
An explicit burn request authorizes writing this matching medium; do not ask
again solely because a CD-R is consumable. A mismatched device/image/region
needs resolution before writing.

Report the actual burn result. A complete write is not proof of bootability;
separate image correctness, console region and physical media/pickup behavior.
Claim hardware playback only after it was observed.
