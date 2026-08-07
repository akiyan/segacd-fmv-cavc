---
name: regions
description: Build release discs for every NTSC region (Japan and North America) across one or more profiles, package each as a zip with its cue sheet and README, verify the zips against the built bytes, and publish them together as one draft GitHub release. Use for "リージョン別にビルドして配布", "make the release zips", "GitHub Releases に iso を上げて", or "/regions".
---

# regions: per-region disc images and their GitHub release

One build becomes one release, holding one zip per title per region.
Everything about a particular title comes from its profile TOML; nothing is
typed into the tools.

Run every command from the repository root.

## Scope

Japan and North America. Both are NTSC.

Europe is not a release target and must not be published. The player displays
H40 V28 and paces every frame, the audio sync, and the CD delivery deadlines
against a 60 Hz field rate, so a 50 Hz console needs the timing model
re-derived rather than a different security code. `boot/region_eu.inc` exists
so the build knob keeps assembling for diagnostics; `region_release.py` and the
harness both refuse it.

## Arguments

```text
/regions [profiles/A.toml profiles/B.toml ...]
```

With no argument, use `profiles/bad-apple.toml` and
`profiles/tears-of-steel.toml`.

## Stage 1: Have a stream worth shipping

A release disc is built from the profile's current packed stream, so the
profile must already have a completed sim whose `decisions.pkl` matches the
TOML. When `make disc` reports a profile hash mismatch, the TOML changed after
the sim; refresh it before building:

```sh
tools/python.sh tools/parallel_run.py --through sim --jobs N profiles/A.toml ...
```

Do not publish a disc whose playback has never been qualified. If the profile
has no gate-`PASS` recording at this encoder/player version, say so and either
run `run` first or state plainly in the report that the release is unqualified.

## Stage 2: Build and package

One command for the whole release. `--config` is repeatable, and it builds each
profile's `DEBUG=0` disc per region and writes its zip:

```sh
tools/python.sh tools/region_release.py build \
  --config profiles/A.toml --config profiles/B.toml
```

The regions of one profile share an output-stem lock, so the tool builds
everything one after another. Add `--force` only to overwrite a zip that is
already there, and `--date YYYYMMDD` only when the release must be dated other
than today.

Outputs land in `out/releases/`:

```text
out/releases/<profile-stem>_<REGION>_<date>.e<N>.p<M>.zip
```

Each zip holds `<profile-stem>_<REGION>.iso`, its `.cue`, and a `README.txt`
naming the region, the encode, the source, and how to burn it.

## Stage 3: Verify before anything leaves the machine

```sh
tools/python.sh harness/regions/verify_release.py out/releases/*.zip
```

Require a zero exit and a `PASS` line for every zip plus the cross-region
`HEADER.DAT`/`BODY.DAT` line for every profile. A failure stops publication;
fix the build rather than the check.
[`harness/regions/README.md`](../../../harness/regions/README.md) states what
each check proves.

Report honestly what the verification does not cover: a North American disc is
checked at the byte level only. This repository has no North American Mega-CD
BIOS and the hardware here is Japanese, so no North American disc in this
project has been booted anywhere.

## Stage 4: Publish

Uploading is outward-facing, so it is a separate, deliberate step.

Show the user the release body first. It is English only: the release page is
the project's public face, and the README inside each zip is where the same
information is given in both languages.

```sh
tools/python.sh tools/region_release.py notes \
  --config profiles/A.toml --config profiles/B.toml \
  --zip out/releases/A_JP_....zip --zip ...
```

Push the branch before publishing, then create the draft against the commit
that carries the tooling:

```sh
tools/python.sh tools/region_release.py publish \
  --config profiles/A.toml --config profiles/B.toml \
  --target "$(git rev-parse HEAD)" \
  --zip out/releases/A_JP_....zip --zip ...
```

The default is a draft. Ask the user before turning a draft into a public
release; `--no-draft` publishes on creation, and an existing release's assets
are replaced only with `--clobber`.

One release, tagged `disc-<date>.e<N>.p<M>`, with every title's zips attached
to it and one section per title. Do not split a build across several releases.
After uploading, download the assets back and compare their hashes with the
local zips, so the release is verified end to end.

## Report

The release tag and URL, whether it is still a draft, and for each profile its
zips with their sizes and the verification result. Name any profile whose
playback is not qualified at this encoder/player version, and repeat that North
American discs carry byte-level evidence only.
