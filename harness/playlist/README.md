# Playlist qualification

`tools/playlist_build.py` produces a disc and a build manifest containing the
ordered entries, effective profile hashes, packed-file hashes, player entry
addresses, and ISO hash. `record.py` locks that playlist and its referenced SIM
stems, leases their data, snapshots the manifest, and records the immutable ISO
through the standard fixed-Replay FFV1/FLAC recorder.

```sh
make playlist CONFIG=profiles/playlist.toml
tools/python.sh harness/playlist/record.py \
  --manifest out/playlist/playlist.json \
  --seconds 870 --min-cycles 1 --tag playlist_six --workspace-gb 24
```

Choose a recording duration covering boot, every requested full cycle, all
loading intervals, and frame 0 of the following cycle. For a measured long run,
`--workspace-gb` reserves an explicit managed tmpfs allocation instead of the
recorder's conservative per-minute estimate. It does not bypass resource locks
or change emulator timing. Account for raw LOGVDP output, native video, both
compressed traces, and the filesystem's user quota before choosing its size.

The dispatcher writes an eight-word marker into VRAM while display and audio
are stopped, then clears VRAM before launching the movie. The existing LOGVDP
core records the marker without an additional per-frame player operation.
Markers contain a signature, entry index, cycle, visit, and terminator. The
analyzer accepts only exact ordered progression from entry 0, cycle 0, visit 1.
Missing, malformed, truncated, or reordered markers fail qualification.

HUD frame resets identify movie visits independently. Each complete visit must
contain every expected movie frame and pass the ordinary schema-16 HUD gate
using that entry's effective profile and cadence. Only the final capture tail
may be incomplete; it must start at frame 0. A successful minimum of N cycles
also requires the boundary to the first frame of cycle N+1. The aggregate gate
binds the recording, full trace, build manifest, and ISO with SHA-256 hashes.

Persistent outputs under `logs/` include one HUD TSV and gate per complete
visit, a boundary TSV, an aggregate gate, and the capture receipt. Boundary
duration means the last observed HUD sample of the preceding movie through
the next movie's first frame; it is not an exact CD-load-only timer.

After each complete DEBUG recording, render, inspect, and publish the first
cycle's per-movie timeline, hudline, and mixline using the standard skills.
Inspect transitions and later visits in the native recording as well. Keep
the recording leased until inspection is finished; inactive media are
disposable, while persistent TSVs support re-rendering their graphs.

`render.py` orchestrates the standard renderers using explicit item-to-timeline
TSV mappings. It writes a persistent graph receipt, but does not publish before
visual inspection. Use the timeline Gist publisher for each inspected PNG.

```sh
tools/python.sh harness/playlist/render.py logs/BOUNDARIES_gate.json \
  --timeline jam=logs/JAM_timeline.tsv \
  --timeline mania=logs/MANIA_timeline.tsv \
  --timeline lunar=logs/LUNAR_timeline.tsv \
  --timeline badapple=logs/BADAPPLE_timeline.tsv \
  --timeline machi=logs/MACHI_timeline.tsv \
  --timeline tears=logs/TEARS_timeline.tsv
```

```sh
tools/python.sh -m unittest discover -s tools -p 'test_playlist*.py'
tools/python.sh -m unittest discover -s harness/playlist -p 'test_*.py'
```

The qualification ladder starts with the two shortest configured movies for
ten cycles plus three independent boots through wraparound, then adds one
movie at a time and requires at least three cycles at each size. Preserve
resolution, cadence, and quality settings while diagnosing an initialization
or delivery regression. Apply entry-specific quality overrides only when
measured resource limits justify them.

## HUD-free release qualification

`make playlist CONFIG=profiles/playlist.toml DEBUG=0 PLAYLIST_ENCODE=0`
builds `out/playlist_release.iso` and its cue sheet, with a separate
`out/playlist/playlist_release.json` manifest. Both manifests record the
encoder/player versions and each entry's packed-stream and palette hashes.

After the matching DEBUG cycle passes, record the release for the same duration:

```sh
tools/python.sh harness/playlist/record.py \
  --manifest out/playlist/playlist_release.json \
  --baseline-gate logs/DEBUG_BOUNDARIES_gate.json \
  --seconds 870 --min-cycles 1 --tag playlist_six_release --workspace-gb 24
```

The recorder leases the DEBUG recording through the comparison. `release.py`
requires identical entry order, profile hashes, stream/palette bytes, versions,
core, and duration, verifies release dispatcher progression, and invokes the
standard release LOGVDP comparison without increasing its tolerance. The result
is a release trace check, not a HUD gate. Its visual-inspection status remains
pending: extract named stills with the standard verification helper and confirm
startup, every movie, wraparound, and the absence of the HUD before delivery.

## Finite-read and snapshot diagnostics

The boot, dispatcher, and resident return readers authenticate each transferred
sector's BCD MSF (minute/second/frame address) against the requested absolute
LBA. They acknowledge mismatched buffered sectors without advancing the write
destination. A per-read budget of 75 mismatches ends in status `DEAD` instead
of allowing an unbounded scan. This protects module and directory reads from
a preceding file's sector remaining buffered across `CDC_STOP + ROM_READN`.
If the transferred address is later than the requested one, the loader
reissues the remaining extent at its unchanged destination. The movie-selection
loader and each movie's initial HEADER/arm/suffix read wait about 100 ms after
STOP. These waits occur before timed delivery and PCM start. The movie player
anchors its very first sector to the requested LBA, so a stale first sector
also triggers exact recovery. Encoded streams and steady CD-1x budgets stay fixed.

`tools/playlist_build.py --packed-manifest BUILD_JSON` supports a player-only
diagnostic rebuild when disposable SIM data is absent. It authenticates source
bytes, encoded settings and every HEADER/BODY/palette file against that build,
requiring the same encoder version. Reordering is allowed. This option does not
establish a new playback qualification or authorize an upload.

For a stopped-player investigation, `tools/run_headless.sh` accepts
`--snapshot-on-exit --max-frames N`. It saves an emulator state at that exact
emulated frame count and runs uncapped when no video recording is requested.
Use a leased managed tmpfs `OUTDIR`, the ordinary EMU/stem locks, and the exact
disc and input Replay being diagnosed. This state-only run is diagnostic
evidence; it does not replace synchronized A/V recording and HUD qualification.

`read_state.py` reads the pinned x86 GPGX 1.7.6 core's RetroArch snapshot,
reports playlist counters, and optionally inspects the selected Sub module's
RAM and the dispatcher images. The Sub RAM location is anchored by the
explicit module header; the CPU-register offset follows `scd_context_save`
in upstream commit `46652c7fd74bd64a99f624b0bd53a768de0ff672`.

```sh
tools/python.sh harness/playlist/read_state.py /MANAGED/PATH/playlist.state.auto \
  --sp-module tmp/playlist/disc/V0004SP.BIN \
  --menu-ip tmp/playlist/disc/MENUIP.BIN \
  --menu-sp tmp/playlist/disc/MENUSP.BIN
```

A leading stale sector can be proved by an exact 2,048-byte displacement:
Main RAM bytes 2,048..20,479 match dispatcher bytes 0..18,431, and the Word-RAM
loader's header appears at bank offset `0x1E800` instead of `0x1E000`.
Compare snapshots before recovery, after recovery, and after EOF before
attributing a corrupt saved extent to an unsafe memory allocation. A shifted
loader can itself overwrite the extent with an invalid directory lookup.
