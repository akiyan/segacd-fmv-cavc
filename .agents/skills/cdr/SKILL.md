---
name: cdr
description: Burn a Sega CD disc image to CD-R so it boots on real Mega-CD / Sega CD hardware. Checks the image is a Sega CD disc, reports its region, verifies the medium is blank and large enough, picks a write speed the medium rates, and writes one Disc-At-Once data track. Use for "CD-Rに焼いて", "実機で動かしたい", "burn the iso", or "/cdr".
---

# cdr: burn a disc image for real hardware

A CD-R is spent on the first attempt, so this skill checks everything it can
before writing and refuses anything it cannot justify.

Run every command from the repository root.

## What gets burned

`make disc CONFIG=profiles/PROFILE.toml DEBUG=0` writes
`out/PROFILE_release.iso`, a Mode1/2048 image with one data track. That is what
goes on the disc. The `.cue` beside it exists for emulators and is not used
here: a single-track data disc needs no cue sheet.

Prefer the release disc for real hardware. A DEBUG disc boots equally well but
draws the counter row over the picture.

## Preconditions

- `cdrskin` installed (`sudo apt install cdrskin`). Do not substitute another
  burner without qualifying it; the SAO behaviour below is what matters.
- A drive that reports `Can write CD-R: 1` in `/proc/sys/dev/cdrom/info`.
- A blank CD-R. The tool refuses a non-blank disc rather than appending a
  session.

## Burn

Report first, then write. The dry run is the default:

```sh
tools/python.sh .agents/skills/cdr/scripts/burn_iso.py \
  out/PROFILE_release.iso --expect-region J
```

It prints the image's Sega CD header, volume name, internal title, size, and
region, then the medium's make, rated speed range, and capacity. Read the
region line against the console you will use. When it all matches:

```sh
tools/python.sh .agents/skills/cdr/scripts/burn_iso.py \
  out/PROFILE_release.iso --expect-region J --burn
```

Pass `--expect-region` whenever the target console is known. The image carries
a region byte at offset 0x1F0 (`J` Japan, `U` North America, `E` Europe) and a
console rejects a disc whose security code is not its own. Catching that
mismatch before the write is the difference between a rebuild and a wasted
disc.

## Why the fixed choices

- **Disc-At-Once, single session.** Track-At-Once leaves a two-second pregap
  that an early-1990s Sega CD drive can fail to read past. SAO is not a
  preference here.
- **Speed comes from the medium.** The tool clamps any request into the ATIP
  range the disc reports. Burning below a high-speed dye's rated floor makes
  the burn worse, not safer, so a lower request is raised to the floor.
- **`burnfree` on.** Buffer underrun protection costs nothing on a disc this
  small.

## When real hardware will not boot it

Separate the disc from the data before rebuilding anything:

- A Sega CD's pickup was designed for pressed discs, whose reflectivity is
  higher than any CD-R. Media brand and dye genuinely change the result on
  these consoles; a different CD-R can boot where another does not.
- Region is the other common cause. Re-read the region line from the dry run.
- If the burn itself reported a complete track and the drive buffer never
  starved, the write is not the suspect. Confirm the image boots in the
  emulator (`tools/record_movie.sh --disc out/PROFILE_release.cue --no-build
  --seconds 30`) to prove the data, then treat it as a medium or pickup issue.

Do not claim a disc boots on hardware unless it was actually tried there.
