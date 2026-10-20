---
name: regions
description: "Build and package Japan/North America Sega CD release images when requested, including /regions; publish a draft GitHub release only when distribution/publication is requested."
---

# Region packages

Use profiles named by the user or unambiguously established in the task.
Supported distribution regions are Japan and North America (NTSC); PAL timing
needs a different model and is not a release target.

Require matching completed decisions. A profile mismatch needs investigation,
not an automatic full encode. Keep playback qualification status explicit.

```sh
tools/python.sh tools/region_release.py build \
  --config profiles/A.toml --config profiles/B.toml
tools/python.sh harness/regions/verify_release.py out/releases/SELECTED.zip
```

Pass only this run's zips to verification/publication, not a glob of stale
artifacts. The builder owns per-profile region naming, ISO/cue/README and licence
metadata. Read `harness/regions/README.md` for byte-level coverage. Distinguish
that coverage from a separate emulator boot and actual region-specific hardware.

For requested distribution, prepare release notes with `region_release.py notes`
and create one draft with `publish --target COMMIT` and the exact zips. Existing
publication authorization is sufficient; public promotion or clobbering another
release needs that action in scope. Verify downloaded assets against local hashes.
A local package request ends with local zips. Report release URL/state when
created, package sizes and qualified/unqualified playback accurately.
