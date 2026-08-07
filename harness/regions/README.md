# regions: verifying per-region release zips

A release zip leaves the machine and goes on a stranger's console. This
harness reads the built zips back and refuses the ones whose bytes do not
match what the release page says about them.

Run it after `tools/region_release.py build` and before
`tools/region_release.py publish`.

```sh
tools/python.sh harness/regions/verify_release.py out/releases/*.zip
```

Every zip named on the command line is checked on its own, and zips that share
a profile stem are additionally checked against each other. The exit status is
zero only when nothing failed.

## What it proves

Per zip:

1. **The name.** `<profile-stem>_<REGION>_<date>.e<N>.p<M>.zip`, with a region
   tag that is an actual release region. Europe fails here: this player is
   NTSC only.
2. **The members.** Exactly `<profile-stem>_<REGION>.iso`,
   `<profile-stem>_<REGION>.cue`, and `README.txt`, and no member is corrupt.
3. **The cue sheet.** Its `FILE` line names the ISO packed beside it, so the
   pair works from whatever directory it is unpacked into.
4. **The disc.** The image starts with `SEGADISCSYSTEM`, so it is a Sega CD
   disc rather than a data ISO that happens to be the right size.
5. **The header.** The hardware type at 0x100 and the region field at 0x1F0
   are the ones `boot/region_<code>.inc` writes for this region.
6. **The security code.** The 32 KiB boot area contains this region's
   `boot/sec_<code>.bin` exactly once, and neither of the other two regions'
   codes at all. This is the check that catches a build that switched
   `SECURITY_REGION` but reused the previous region's copied inputs, which is
   otherwise invisible until a console rejects the disc.

Across the regions of one profile:

7. **The stream.** `HEADER.DAT` and `BODY.DAT` are byte-identical between
   regions. That is the proof that a region is a boot-area difference and
   nothing else, and that both discs play the same encode.

## Why it reads the ISO itself

Two details are easy to get wrong by comparing files instead of contents.

- **Whole-image comparison does not work for check 7.** `mkisofs` stamps
  creation timestamps into the primary volume descriptor, so two images built
  a second apart differ outside the boot area no matter what the payload is.
  The script walks the ISO 9660 root directory and hashes the two stream files
  themselves.
- **Directory reading is done here rather than shelled out.** The disc has one
  flat directory of a few files, so the primary volume descriptor's root
  record is all that has to be walked. Keeping it in the script means the
  check does not depend on which `isoinfo` build happens to be installed.

## What it does not prove

- **That a console boots the disc.** The security code is compared byte for
  byte against the region's own file, and the header fields against the
  region's own include, but neither is a substitute for a machine. The
  Japanese disc is qualified by emulator recordings and by real Mega Drive 2 /
  Mega CD 2 hardware. The North American disc has no equivalent evidence:
  this repository has no North American Mega-CD BIOS to boot it with in an
  emulator, and the hardware here is Japanese. Treat a North American disc as
  verified at the byte level only, and say so when publishing one.
- **That the encode is good.** Playback quality, the HUD gate, and A/V sync
  belong to the `record` and `hudline` skills. This harness only asks whether
  the packaged disc is the disc it claims to be.
