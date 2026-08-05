# Project Guidance

This repository is now a SEGA-CD FMV Encoder project. Do not steer new work
back toward the old game-specific port unless the user explicitly asks for it.

## Explanation Style

- Avoid math jargon and dense technical terms when a plain explanation is
  enough.
- Prefer everyday wording first.
- If a technical term is necessary, define it immediately in simple language.
- The priority is that the explanation is understandable, not that it uses the
  most formal vocabulary.

## Chat Media Links

- In Codex chat responses, never use inline embedding syntax for video or
  audio, including Markdown image syntax such as `![...](...)`.
- Present local media artifacts and uploaded video or audio as ordinary
  clickable Markdown links only. This applies even when the client supports
  inline playback, because embedded media can make the Codex app unstable.

## Terminology and Intent Checks

This project has several similarly named objects whose substitution changes the
entire design. Be deliberately strict about checking the user's terminology
before beginning broad investigation, benchmarking, or implementation.

- If a statement combines terms in a way that looks inconsistent with the
  current format, hardware ownership, or the preceding discussion, treat it as
  a possible wording slip. Do not silently reinterpret it or investigate every
  possible meaning.
- First restate the intended **object, operation, and memory domain** in one
  short question. For example: "Do you mean keeping the routing table, rather
  than PrgBuf pattern payload, resident in Word RAM?"
- This confirmation is required whenever the ambiguity would change the file
  format, memory map, bank ownership, buffering model, cycle analysis, or work
  branch. Ask even when one interpretation seems likely.
- After the user corrects a term, discard conclusions based on the mistaken
  interpretation and re-evaluate from the corrected object.

Keep these distinctions explicit:

- **routing table**: per-delivery-slot sector counts used to sort BODY sectors;
  it is not pattern data.
- **PrgBuf** (`Prg` in analysis): the streamed PRG-RAM circular buffer holding
  prefetched 32-byte cold patterns. Internal `RING_*` constants describe its
  ring-buffer implementation.
- **WordBuf0 / WordBuf1** (`Wr0` / `Wr1`): distinct boot-preloaded pattern
  sequences in the two physical 1M Word-RAM banks, selected by frame parity;
  they are not duplicate caches.
- **DicBuf** (`Dic`): a 256-entry boot-preloaded pattern dictionary copied once
  to Main RAM. Entries are addressed by index and may be reused without being
  consumed.
- **APPLY ring**: the PRG-RAM circular queue holding continuous control blocks.
- **resident pattern**: currently a pattern retained in the VRAM tile pool. A
  boot-preloaded WordBuf pattern is a physical source, not another VRAM-resident
  cache level.
- **whole-movie quality budget**: encoder-only spending accounting. It is not a
  physical buffer and has no analysis meter. The old name “Tank” is retired.
- **Buf category**: an encoder funding class for an exact cold load using saved
  quality allowance or a boot-preload credit. It is not a physical `Buf` meter.
- **Word RAM output bank**: the 1M/1M frame handoff area exchanged between Sub
  and Main CPUs; it is not automatically shared by both CPUs at once.

## Language Policy

- Use English by default for repository files, documentation, code comments,
  and general project text.
- Use Japanese for commit messages, GitHub issues, and pull request comments.

## Commit Attribution (all agents — Claude, Codex, etc.)

- Do NOT add `Co-Authored-By: Claude ...`, `Co-Authored-By:` any AI, or
  `Claude-Session:` / `Codex-Session:` trailers to commit messages. The public
  repo's Contributors must not list an AI assistant.
- Author and committer are the human owner only (`akiyan`); never an
  `@anthropic.com`/AI address.
- This repo is public and its history was rewritten once to strip such trailers.
  Every agent working here must follow this so it does not reappear.

## YouTube Upload Style (codec analysis videos)

Titles and descriptions for the codec analysis videos follow this fixed style.

- **Language**: English. In descriptions, write English first, then the same
  content in Japanese after it.
- **Title**: English, fixed format `SEGA-CD FMV of <work> - <specs> <ver>`.
  - `<work>`: the work name. For a native/kanji title, give the
    transliteration followed by the native title in parentheses, e.g.
    `Romaji (native)`. A romaji-only work needs no parentheses.
  - `<specs>`: the descriptive spec suffix (mode, resolution/grid, "max
    resolution", etc.). No **sequence** version numbers (no `vNNN`).
  - `<ver>`: the encoder/player build version `YYYYMMDD.eN.pM` (from
    `tools/av_version.txt`). `e` = shared encoder implementation and defaults
    (`sim.py` / `pack_stream.py`), `p` = shared player implementation
    (`boot/movieplay_*.s`). Bump `e` or `p` only when that shared side changes
    in a way that can alter its output; never decrease either. Do **not** bump
    `e` for a source-specific profile edit such as its input, trim, geometry,
    frame rate, cold cap, or another encoder setting. Those values are tracked
    by the profile/settings identity and are not encoder build revisions.
    Likewise, do not bump `p` merely because a different profile or stream is
    played. When bumping, set the date to today if it differs. This is the
    title build version only; the on-disc `HEADER.DAT` layout has no independent
    version field. Update `tools/av_version.txt` whenever
    you bump.
  - Example: `SEGA-CD FMV of <Work> - max resolution 320x224/40x28 20260710.e1.p1`.
- **Description structure** (in both languages, in this order):
  1. Overview — one or two lines on what the video is.
     Name the codec **Sega CD Constraint-Aware Video Codec**. Do not use the
     current binary magic as a public codec or format name.
  2. Output and source specs — the SEGA-CD output (mode, grid WxH, tile count,
     fps, audio, Prg/Wr0/Wr1/Dic capacities, CRAM palette switch count) and the
     Source (resolution, fps, audio).
  3. How to read the analysis layout — what each panel, meter, and timeline
     shows and how to interpret it (left = SEGA-CD sim output; right = Source /
     category map / 60 fps audio waveform and spectrum; bottom status =
     Req with its Miss count, Cold, Band, R2V, Run, Prg, Wrd, and Pre, then the
     palette strip and the stacked Req / supply / Run / Band timelines; the
     category legend is Raw, Same, Near, Flbk, Miss, Prg, Wrd, Dic, plus Scrl
     on a movie with adopted hardware scroll — Scrl is a cell the active
     scroll carried to its correct position without an update this frame,
     scroll reuse rather than a Miss. Such a movie also shows the legend's
     right-aligned hardware-scroll indicator: green chevrons pointing in the
     on-screen flow direction plus axis:position and speed per frame while a
     window is active, dimmed to "SCROLL ---" between windows; a movie with
     no adopted window shows neither Scrl nor the indicator). Define Band
     as useful
     `BODY.DAT` payload + control bytes in the physical delivery slot, excluding
     all pad and the untimed `HEADER.DAT` / BODY-arm / frame-0 regions, divided
     by that slot's actual physical CD read time. Its range is 0 to CD 1x
     (150 KiB/s); pad is unused bandwidth. Define R2V as the words the Main CPU
     moves into VRAM for that frame: pattern data, the Word-RAM DMA first-word
     repair, name-table/HUD words, and palette words. Wrd is the two Word-RAM
     banks shown as one meter; Pre is prefetched cold work that is not displayed
     yet.
  4. What the encoder does — first a short list of the techniques applied, then
     the details for each.
  5. Project link — always include the source repository URL:
     `https://github.com/akiyan/segacd-fmv-cavc` . Put it in every description
     (both the English and the Japanese section).
- **Describe only what the current build renders.** Take every panel, meter,
  and category name from `tools/layout_preview.py` and `tools/analysis_style.py`
  and spell them the same way. Describe an encoder technique only when
  `tools/sim.py` still implements it. Do not carry wording forward from an
  earlier description without checking it against the current code; a term that
  no longer exists in the build must not appear in a new description.
- **CRAM switch count (permanent).** Every codec video (analysis and
  real-playback) MUST state how many times the palette (CRAM) switches, as part
  of the output spec section in both languages. Read the count with
  `tools/cram_switches.py <sim_out>`, which prints `cram_segments=<N>
  cram_switches=<N-1>` from the sim's `frame_seg`. The count belongs to the
  encode, so the analysis render and its playback recording report the same
  numbers. Do not add YouTube chapters and do not put timestamp links in the
  description: these uploads carry no chapter list at all, at CRAM switch points
  or anywhere else.
- Do not show bitrate in the Source spec line.
- Uploads are unlisted, category 20 (Gaming). Descriptive titles, not vNNN.
- **"Upload" always means the latest version.** Before uploading, rebuild the
  artifact from the current code and data (re-encode / re-render if anything
  changed since it was last made); never upload a stale file. Re-uploads use
  `--force` (the previous video stays unlisted).
- Never put `<` or `>` in the description — YouTube rejects it with
  `invalidDescription` (HTTP 400). Write "0.3s or more", "within 4s", etc.

## Documentation Policy

- Keep public documentation in [`README.md`](README.md).
- Keep agent and maintenance instructions in `AGENTS.md`.
- Write every public Markdown document located at the repository root in
  English first, followed by a complete Japanese version below it. Keep the
  two language sections structurally equivalent and update both together.
- Describe only the current system in public root documentation. Do not use
  chronology-dependent narratives such as "previously", "formerly", "the old
  implementation", or "this was changed to". State the active behavior
  directly. [`REMOVED.md`](REMOVED.md) is the only exception: it preserves
  timeless implementation and reimplementation notes for features that are
  absent from the active system, without release chronology or historical
  storytelling.
- Keep Markdown self-contained. Do not link to or name GitHub issues from
  Markdown files; describe the current behavior or plan directly instead.
- Do not add new scattered Markdown documents for project notes at the repo root.
- **Harness / diagnostic docs are allowed under `harness/`.** When a debugging
  effort needs its own tooling and notes (detectors, repro scripts, findings),
  put both the scripts and their [`README.md`](README.md) under `harness/<topic>/`. This is
  the sanctioned place for build-your-own-detector work; keep each topic's doc
  next to its code so the harness stays reproducible.
- These dedicated reference docs are sanctioned and must be kept current:
  - [`MOVIE.md`](MOVIE.md) - the `HEADER.DAT` + `BODY.DAT` on-disc stream
    format. Keep in sync with
    `tools/pack_stream.py` and the `boot/movieplay_*.s` player.
  - [`CONFIG.md`](CONFIG.md) - the tunable settings, throttles and buffers
    (PrgBuf, boot preloads, quality budget, cold cap, audio sync, CD pump, DMA
    budget, encoder knobs, per-source env). Keep in
    sync with `tools/av_config.py`, `tools/sim.py`, `tools/pack_stream.py` and the
    `boot/movieplay_*.s` player.
  - [`HUD.md`](HUD.md) - the on-hardware values-only DEBUG HUD reference. Keep
    its field order, widths, timing units, rendering path, and OCR workflow in
    sync with `boot/movieplay_ip.s`, `tools/read_frameno.py`, and the HUD
    harnesses.
  - [`PLAYER.md`](PLAYER.md) - the live Main/Sub player memory maps with named
    ranges, unallocated space, the startup sequence, and the per-frame
    CPU handoff. Keep
    its addresses and limits in sync with `tools/av_config.py`,
    `tools/check_player_ring.py`, and `boot/movieplay_*.s`.
  - [`REMOVED.md`](REMOVED.md) - the archive for removed feature designs,
    dependencies, and implementation notes needed for a possible clean
    reimplementation. It is not a description of the active pipeline.
  - [`ENCODE.md`](ENCODE.md) - the current simulation-encoding flow and a
    versioned full-encode timing example. Keep its short stage names aligned
    with the timers and comments in `tools/sim.py`.
- Keep the analysis-overlay specification beside its implementation:
  `tools/layout_preview.py` owns layout and reading rules,
  `tools/analysis_style.py` owns category semantics and colours, and
  `tools/render_analysis.py` owns real-data, TSV, and mux timing. Do not create
  a separate `ANALYSIS.md`.
- Claude skill files under `.claude/skills/**/SKILL.md` are allowed and should
  remain in place.
- Do not reintroduce game-specific extraction notes or copyrighted sample
  metadata.

## Delimited Log Format

- Use TSV for every project-owned delimited log, diagnostic table, and
  machine-readable row series. Write UTF-8, a header row, tab separators, LF
  line endings, and the `.tsv` extension.
- Do not create `.csv` files or comma-delimited internal logs. Python may use
  the standard `csv` module as an implementation detail only when
  `delimiter="\t"` is explicit.
- Name CLI options and documentation after the format (`--tsv`, `--hud-tsv`),
  not `--csv`. CSV is allowed only when an external system explicitly requires
  that interchange format; keep such conversion at the external boundary.

## Canonical Path

This project is the **Sega CD Constraint-Aware Video Codec**. Generic file
names keep implementation details independent from the public codec name. The
current encoder/player path is:

```text
tools/sim.py -> tools/pack_stream.py -> boot/movieplay_*.s
```

The on-disc stream is split into static boot state in `HEADER.DAT` and an
untimed audio/frame-0 arm followed by timed frame-1+ slots in `BODY.DAT`.
On-disc data compatibility across layout changes (including between specialized
and generic player builds) is not maintained: update every consumer of the
shared format together.
The packer also writes a concatenated `MOVIE.DAT` compatibility container for
offline tools; the player does not read it.

Resolution, aspect, and frame rate are **per-source encoder settings**
within Sega CD limits, not fixed presets:

- Resolution and aspect inside the fixed H40 320x224 aperture, with the tile
  grid sized to the per-frame DMA budget. H40 is the only display mode; see
  [`REMOVED.md`](REMOVED.md) for what an H32 reimplementation would need.
- Frame rate = the source's native rate.
- Audio = checkpointed 22.05 kHz mono IMA ADPCM, decoded directly by the Sub
  CPU through full lookup tables installed once in Sub PRG-RAM. It is the only
  audio format in the on-disc CAVC layout. Physical
  hardware and additional modes/cadences are broader compatibility checks
  rather than implementation blockers (see [ADPCM.md](ADPCM.md)). Z80 offload
  remains shelved because BUSREQ-based feeding contends with Main CPU video
  work.

The old `OP.STR` / RLE and `PROBE.BIN` bring-up paths have been removed.
`make disc CONFIG=profiles/PROFILE.toml` builds the `HEADER.DAT` + `BODY.DAT`
disc played by `boot/movieplay_*.s`. The TOML filename is the artifact identity:
packed stream files live under `out/PROFILE/`, transient build, disc-staging,
and direct-emulator scratch files live under `tmp/PROFILE/`, and the bootable
pair is `out/PROFILE.iso` + `out/PROFILE.cue`.

## Output Paths (tmpfs and logs/)

All generated media and image artifacts are disposable and live directly in
the project-managed tmpfs workspace at `/dev/shm/segacd-fmv-cavc`: native
lossless emulator captures, analysis/straight-sim/preview/compilation MP4s,
recording sidecars, verification stills, and timeline/hudline/mixline PNGs.
Disposable sim directories live there too. Tools print the actual path that
downstream stages must use. The repository has no media-output directory and
must not create one. Inactive oldest tmpfs entries are evicted when the next
run needs room, while active leases are never removed. The pipeline retains a
recording lease through its HUD stage so the lossless input cannot disappear
between recording and analysis.

Keep analysis data persistently under git-ignored `logs/`: every per-frame
timeline/HUD TSV, plus its HUD gate JSON, image layout JSON, and Gist receipt.
A persistent receipt can outlive its evicted tmpfs image; re-render from the
TSV rather than treating the receipt as proof that the image still exists.
Timeline and HUD TSV filenames include both encoder and player versions. Use
one stem per encode:

Completed sim directories are reused automatically only when source bytes,
effective encoder/TOML settings, and the output-affecting encoder-code
fingerprint match. The tmpfs entry name spells out source, mode, geometry, fps,
fit, cold cap, and short source/settings/encoder fingerprints. Profile
filenames and TOML formatting do not split otherwise identical encodes.
Interrupted entries have no completion marker and are reset on the next run.
Use `CBRSIM_FORCE_REENCODE=1` only for an explicitly requested clean encode.

```
stem = <input-basename>_<display-mode>_<resolution>_<audio-format>
       e.g. OP1_ps2_H40_320x144_adpcm22
```

| Artifact | Path |
|---|---|
| Analysis-frame video (from `sim`) | printed direct tmpfs path ending in `<stem>_analysis.mp4` |
| Per-frame analysis data (same values as the overlay) | `logs/<datetime>_<profile>_<sha10>_eNN_pNN_timeline.tsv` |
| Per-frame playback HUD data and gate | `logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv` and matching `_gate.json` |
| Image layout and Gist metadata | `logs/<image-stem>_<image-sha10>_<kind>.json` |
| Straight sim output, video+audio, no overlay (`export_sim_video.py`) | printed direct tmpfs path ending in `<stem>_sim.mp4` |
| Sim inputs, stats, and decision data | deterministic direct tmpfs `.../sim-.../data/` path; analysis creates `preview/` and `catmap/` there on demand |
| Lossless emulator capture (`record`) | printed direct tmpfs path ending in `<stem>_emu_lossless.mkv` |
| Verification preview (`record`, opt-in `--preview` only) | printed direct tmpfs path ending in `<stem>_emu_preview.mp4` |
| Upload compilation (`compilation`) | printed direct tmpfs path ending in `<stem>_emu.mp4` |

- `<input-basename>`: the source file name without extension.
- `<display-mode>`: always `H40`, kept so an artifact path stays self-describing.
- `<resolution>`: the Sega CD output resolution in pixels, `WxH` (e.g. `320x144`).
- `<audio-format>`: always `adpcm22` (see [ADPCM.md](ADPCM.md)).

## Hardware Facts

- Keep CD reads continuous where possible. Reissuing `CDC_STOP + ROM_READN`
  costs too much bandwidth.
- 1M/1M Word RAM bank swaps are cheap enough for frame-granular buffering.
- RF5C164 wave RAM writes use the odd byte window and correct PCM bank select.
- Keep three Sub-program domains separate: the SP source inside the disc system
  area, the BIOS-loaded resident destination in Sub PRG-RAM, and boot-only
  scratch in Sub PRG-RAM. The BIOS can load a multi-sector SP. The active
  layout places the source at `0x6000`, reserves 5 KiB at resident PRG
  `0x6000..0x73FF`, and places the 64 KiB ISO scratch in the inactive
  timed-ring tail `0x67000..0x76FFF`.
- Do not infer generic live scratch from an address gap. Marker tests qualify
  continuous-read stability at `0x7400..0x7FFF` and rewritten scratch at
  `0x08000..0x097FF`; the active map assigns most of those ranges to ADPCM,
  PCM, and pending-sector state. `0x09800..0x0BFFF` is BIOS-touched during
  continuous reads. Prefer checked high PRG allocations for routing and
  queues.
- Long CDC drain gaps can silently drop sectors. Streaming code must keep
  pumping while Main CPU work is happening.
- In Sub-CPU wait loops, service an already-arrived or already-cleared
  `CMD_SWAP` before another opportunistic sector pump. Continue pumping while
  Main is genuinely idle; once the handshake is pending, future-data work must
  not consume the current fixed-cadence display deadline.
- `total_len` fields in apply/control blocks must stay even.

### CD 1x deadline invariant

- Treat the timed BODY read as an absolute 75-sector/s physical service clock
  at every point in playback. CD 1x is not a whole-movie average budget.
- Keep the player-only frame -1 outside that clock. With no simulated frame -1,
  the timed BODY suffix must remain stopped until the visible frame-0 flip;
  pumping future sectors during frame -1 creates unmodeled producer lead even
  when the displayed sentinel itself is correct.
- Do not advance PCM through the first timed `ROM_READN` startup interval.
  Launch the suffix only after the frame-0 flip, use the first frame-1 control
  sector as the proof that 75-sector/s service is flowing, start PCM there,
  and finish that physical slot before releasing Main. The remaining slot and
  VBlank phase establish the first movie interval; CD startup latency is not
  an audio packet and must not become A/V lead.
- Every cumulative sector prefix must fit the CD 1x time elapsed by that exact
  display deadline, including only startup lead that the model explicitly
  proves. A routing-table slot limit is a format capacity, not proof that the
  slot can be delivered by its deadline.
- Never accept a heavy slot that creates positive rate lead on the assumption
  that a later light slot, omitted pad, or a zero final average will repay it.
  Later work can repair byte accounting; it cannot return display time that
  has already elapsed. Exact finite-buffer schedules therefore require zero
  rate lead at every prefix, not merely at the end.
- Prove three conditions separately for any delivery change: on-disc route
  capacity, cumulative physical delivery by every deadline, and finite
  producer/consumer-buffer bounds. Fix a violated construction condition
  before considering a larger APPLY ring, a smaller PrgBuf, or another buffer
  trade that would only absorb the invalid lead.

### VDP DMA rules (measured)

- Enable DMA first: VDP reg 1 bit 4 (M1, e.g. `0x8174`). The BIOS default
  leaves it off and DMA requests are then silently ignored (symptom: only
  CPU-written words appear, everything else stays blank).
- The DMA length registers (`0x93/0x94`) count down to zero during a transfer;
  rewrite them before **every** DMA. Reassert autoinc (`0x8F02`) too.
- Poll DMA completion (status bit 1) before touching VDP registers again.
- Issue DMAs inside VBlank only, and split large transfers across VBlanks with
  a word budget (`VBLANK_DMA_WORDS`); a transfer spilling into active display
  corrupts on strict emulators/hardware.
- **DMA from Word RAM: `src+2`, full length, normal destination, then CPU-write
  the destination's FIRST word after the DMA.** Verified against the GPGX
  source (`vdp_ctrl.c`): the first word the VDP receives is stale bus data and
  the last source word is discarded — the emulator models this as `dst += 2;
  length -= 1`, i.e. **the destination's first word is never written by the
  DMA**. So: program source = `src+2` (delivers `A[1..L-1]` to `dst[1..L-1]`),
  then repair `dst[0] = A[0]` with one CPU write per transfer. Without the
  repair, fresh tiles keep one stale VRAM word each (dark 4px dashes scattered
  on updated tiles; settled frames look clean). The variant "CPU first word +
  DMA `src+2 -> dst+2` with `len-1`" is WRONG here: every word lands one early
  (vertical striping). Every pattern run uses DMA, including one- and two-tile
  runs. Split each run at the remaining VBlank budget boundary and apply this
  first-word repair to every Word-RAM DMA chunk.
- DMA from Main RAM needs no correction. Trigger writes: first control word,
  then the second word containing CD5 (`0x80`); keep the pre-DMA register
  writes (`0x93-0x97`) before the control words.

## Debugging Method (hardware/emulator investigations)

When playback breaks, do not guess from one symptom. Prove each layer
innocent in order, with byte-level or frame-level evidence:

1. **Data layer**: replay the exact writer/reader logic in a small Python
   replica against the real `HEADER.DAT` + `BODY.DAT` pair (all frames, not samples). If the
   format walks cleanly, the data and format are innocent.
2. **Logic layer**: when changing stream layout or allocation, prove display
   equivalence in Python first (old vs new must produce identical
   cell->pattern states for every frame) before touching assembly.
3. **Assembly layer**: disassemble the built binary
   (`m68k-elf-objdump -m 68000 -b binary -D`) and read the changed region.
   Confirm the instructions match intent before blaming hardware.
4. **Regression check**: rebuild yesterday's artifact from a `git worktree`
   of the old commit and `cmp` it byte-for-byte with today's. `IDENTICAL`
   means the regression is not in the code you changed.
5. **Bisect in time**: use the `ISO_HOLD_N` freeze diagnostic to hold the
   player at frame N and screenshot. Binary-search N to find the first bad
   frame instead of staring at post-collapse garbage.
6. **Environment last, but verify it**: boot the BIOS with no START presses
   to confirm the emulator itself is healthy; check core/BIOS mtimes.

Emulator pitfalls learned the hard way:

- Uncapped headless RetroArch can run many times faster than realtime. Never
  map screenshot wall-clock time to frame numbers; a shot at "12 seconds" can
  be far past the section you meant to check. Use `ISO_HOLD_N` for exact
  diagnostic frames, or an input Replay plus `--max-frames` for an exact
  recording window.
- A crashed RetroArch commonly leaves the log ending at `SET_GEOMETRY`.
  A healthy run returns zero and reaches `Content ran for a total of` plus
  `Unloading core`; some RetroArch builds additionally print `Average monitor
  Hz`, but 1.22.2 does not do so consistently. A natural `--max-frames` exit
  also requires a readable Matroska trailer and packet plus decoded-frame counts
  equal to the requested limit. Check the appropriate ending before trusting
  black/garbage screenshots (exit code 139 usually means runaway reads past
  mapped regions).
- Every consumer of a shared data format must be updated together: a
  diagnostic path that still writes the old layout (e.g. `dump_ring_head`)
  will corrupt a new-format reader and can crash the whole emulator.
- Guard stream readers against corrupt counts (clamp to remaining, treat 0
  as end). On compact formats, corruption otherwise turns into unbounded
  runaway reads instead of one glitched frame.

## HQ Deliverable Encode (final mp4)

`record` owns the native lossless capture; `compilation` owns the upload
transcode. Keep the complete recording, including the Mega-CD startup. Do not
leave a non-square SAR for YouTube to rescale: bake the mode's pixel aspect into
a high-resolution square-pixel raster with nearest-neighbour scaling:

```sh
tools/python.sh tools/tmpfs_workspace.py run-file \
  --output <stem>_emu.mp4 --kind compilation-mp4 --required-gb 8 \
  --input "$LOSSLESS" -- \
  ffmpeg -i "$LOSSLESS" \
    -vf "scale=2048:1568:flags=neighbor,setsar=1" \
    -c:v libx264 -crf 10 -preset slow -pix_fmt yuv420p \
    -c:a aac -b:a 192k -movflags +faststart '{output}'
```

The final line printed by `run-file` is the direct tmpfs MP4 path. Use that
path for verification and upload.

- H40 320x224 PAR 32:35 becomes a 2048x1568 SAR 1:1 aperture. A practical-size
  exact integer replication is impossible, so nearest-neighbour assigns each
  source column to 6 or 7 output columns without colour blending. Vertical
  replication is an exact 7x.
- The nearest-neighbour enlargement preserves source colour samples, but the
  H.264 mezzanine and YouTube delivery are re-encoded and are not end-to-end
  lossless. Use CRF 10 to give YouTube a clean high-resolution input.
- Do not add `-ss`, `-t`, an fps filter, or `-r` to the standard upload path.
- Upload the full-quality tmpfs artifact before it is evicted. Do not downscale
  the deliverable itself to fit a file-transfer size limit; render a separate
  `896x576` crf20 preview when a small copy is needed.

## Debugging Method — additions

- **Identify the owner before optimizing work.** State the object, operation,
  CPU, and memory domain. Main-CPU run/locality work does not remove a
  Sub-CPU pump, audio, copy, or handoff bottleneck, and player optimization
  does not repair an encoder schedule that exceeds a physical deadline.
- **Keep target quality fixed while testing a regression.** Resolution, fps,
  cold cap, filters, palette policy, and other target-quality settings stay
  fixed. Encoder decisions and concrete sim results may change when the model
  is corrected. Lowering workload until a failure disappears measures a
  workaround, not the original regression. If a previously qualified quality
  point now fails, treat it as a regression; once failure is reproduced at or
  below that baseline, stop lowering the cold cap. Resume upper-bound tuning
  only after the cause is corrected at the original quality point.
- **Separate correctness, non-regression, and measured benefit.** A change can
  be valid and playback-safe without addressing the observed failure. Prefer a
  player-only A/B on the same packed stream, and report those three conclusions
  independently. Do not automatically stack the next optimization stage, spend
  PrgBuf/APPLY capacity, or enlarge resident code merely because the preceding
  change was theoretically faster; require an observable benefit or a separate
  correctness need.
- **Interpret waiting in context, not as severity.** A faster Sub path can
  reach the next sector wait earlier and therefore increase
  `cd_wait_count`; that alone is neither improvement nor regression. Keep it
  diagnostic-only and read it with `sector_slip`, `control_desync`,
  `audio_resync`, visible playback, cadence, `prgbuf_jitter_peak_kib`,
  `adpcm_decode_units`, and `sub_wait_scanlines`.
- **A graph near zero is not proof of zero.** Fixed whole-movie scales can hide
  a small positive balance. Add an exact signed diagnostic when zero,
  underflow, wraparound, or debt matters, and preserve its per-frame minimum
  rather than inferring it from a circular pointer distance.
- **Use HUD fields to falsify hypotheses, then follow transitions.** Add the
  smallest measurement that can disprove the current explanation. Correlation
  at one low-water interval is not causation; align encoder decisions, live
  balances, queue guards, displayed-frame cadence, and cumulative recovery
  transitions on one frame axis before naming the cause. Instrumentation must
  remain observational rather than steering playback. When added HUD work or
  a unified layout increases runtime cost, requalify the instrumented standard
  build on representative fast and slow cadences before relying on its data.
- **Derive resources from cadence, then qualify each cadence.** Control size,
  PCM work, routing lifetime, PrgBuf ceiling, jitter, and resident-code margin
  differ with fps. Use one fps-derived source of truth rather than a 15fps or
  30fps exception, and run representative full-playback checks for both slow
  and fast cadences after shared player or scheduler changes.
- **Treat failures near the first frames as startup-sequence failures until
  proven otherwise.** The boot/header drain, frame-0 expansion, PrgBuf
  prebuffer, Word-RAM handoff, continuous `BODY.DAT` read start, first routing
  entry, and PCM start make this window different from steady playback. Before
  changing a steady-state knob such as cold cap, compare the first bad HUD
  frame with the first timed pattern load and inspect those handoffs in order.
  If `sector_slip`, `cd_wait_count`, `control_desync`, or another fault begins
  before timed cold loads begin, do not attribute it to cold cap; diagnose the
  startup path first.
- **Transient vs persistent artifacts**: if an `ISO_HOLD_N` freeze of frame N
  is clean but live playback of the same frame shows artifacts, the corruption
  is stochastic per run (timing/phase dependent), not deterministic data
  corruption. Diff consecutive 60fps captures of one 15fps game frame: if the
  artifact is identical across them, the tile content was wrong for that whole
  game frame (upstream of scanout).
- **Quantify artifacts with a detector, then A/B builds**: eyeballing dithered
  frames misleads. Write a small detector (e.g. dark isolated horizontal
  dashes = pixels much darker than both vertical neighbors on a bright field)
  and run it over recordings of each build generation. 3.2/frame vs a 0.4
  false-positive floor identified the Word-RAM DMA first-word bug in one pass.
- **Legacy 192-line captures and window screenshots are not pixel-exact**:
  window screenshots are non-integer scaled, so pixel-perfect comparisons
  against decoded ground truth fail on dithered content (a 1px sampling shift
  flips half the dither pixels). Use the current native 320x224 FFV1
  recording or emulator-side dumps for pixel-level checks, and treat cell-mean
  correlation as alignment-tolerant but detail-blind.
- **The sim is a MODEL of the hardware — when the two disagree, suspect the sim,
  not just the encoder tuning.** The hardware's job is to reproduce the sim
  faithfully (the sim's Miss/residual is expected and fine; extra garbage or a
  freeze on top of it is a divergence). When the hardware cannot reproduce the
  sim *no matter how you tune*, STOP and question whether the sim mis-models the
  hardware's real limit — do not keep shaving the encoder to fit a symptom.
  Precedents: the CRAM emulation had a sim-side bug; an older 22.05 kHz ADPCM
  player exceeded the 68000 streaming margin, while the later optimized Sub
  path had to be re-qualified rather than inheriting that conclusion; Z80
  offload introduced Main-bus contention (see `ADPCM.md`); and the streaming
  Prg ring: the old sim quality reservoir was set at 440 then 400 KB while the
  physical ring was about 420 KB, i.e. it assumed effectively the *entire* ring
  was usable for time shifting. Real CD-delivery jitter makes the usable ring smaller, so a
  schedule the pack calls feasible (`under`=0, `ring_min`≈1–2 KB) still underruns
  live. The fix was a sim-side correction — keep the quality and schedule
  ceilings a jitter margin below the physical ring so the sim only decides
  loads the hardware can actually deliver —
  not a per-frame cold cap papering over it. Keep `pack_stream.py`'s
  `RING_CAP_KB` tied to the player's real `RING_SIZE` minus that margin. Shape
  useful payload to the CD-1x allowance (replace rate padding while space is
  available), and require every exact finite-buffer route to keep rate lead at
  zero. A later light frame cannot repay display time already lost to a heavy
  slot.

## Recording Rules

- Use emulator-synchronized A/V output for verification.
- After every full DEBUG recording, render the complete first-loop HUD TSV with
  `.agents/skills/hudline/scripts/render_hudline.py`, inspect and show the PNG,
  and publish it to a public Gist. Require the matching `/timeline` from the
  exact sim decision log, then immediately render, inspect, show, and publicly
  publish `/mixline`. Generate and publish the timeline first when it is
  absent. Preserve all three images, their layout JSON files, and Gist receipts
  next to the recording. The HUD result has a binary `gate` (`PASS` or `FAIL`)
  and a separate `alert` (`NONE`, `WARNING`, or `FAIL`). `NONE` and `WARNING`
  keep the gate at `PASS`; only alert `FAIL` makes the gate `FAIL`.
  `cd_wait_count` is diagnostic only and never changes either result; report
  its minimum, mean, median, and maximum together with the same
  `adpcm_decode_units` statistics.
  Publish failed gates and their mixlines too as diagnostic evidence, but do
  not proceed to analysis/playback uploads when `gate` is `FAIL`.
- Extract visual-check stills with `tools/extract_verification_frames.sh`. It
  creates a never-reused directory and a source-hashed manifest for each
  invocation, then builds the montage from that invocation's explicit frame
  list. Never montage a shared check directory with `*.png`; loose stills from
  an older recording or transcode can silently contaminate the result.
- Do not verify playback by replacing audio with an offline source.
- Real/emulator recordings use a `DEBUG=1` disc by default, including the Plane A HUD. Build
  release only when the user explicitly requests it. `tools/record_movie.sh` enforces this;
  its `--release-build` option is the explicit release override.
- Prefer:

```sh
tools/record_movie.sh --config profiles/PROFILE.toml \
  --seconds 180 --tag STEM_emu
```

- The high-level recorder defaults to FFV1/FLAC and writes its bounded
  pixel-lossless MKV, Replay, and emulator logs into one leased tmpfs
  directory. The lossy H.264 verification preview is opt-in via `--preview`
  and is not produced normally; verify with stills extracted from the MKV. It uses the qualified fixed-Replay offline path by default: the
  same DEBUG disc, Mega-CD startup, CD player, START transition, movie and tail,
  with audio sync, rate control and video vsync disabled so the fixed
  emulator-frame run can proceed uncapped.
- `--offline-record` is an explicit spelling of that default.
  `--realtime-lossless` selects the paced FFV1/FLAC fallback for qualification
  or diagnosis. Explicit `--preset realtime` instead selects paced H.264 4:2:0
  and must not be used as a `compilation` input.
- If the default has no `--input-replay`, `record_movie.sh` first records one
  in the same leased tmpfs directory, 120 emulator frames longer than the main run.
  A supplied Replay must also extend beyond `--max-frames`; Replay EOF is a
  hard failure because RetroArch may otherwise repeat a cached end frame.
  Replays belong to the exact disc, core and configuration that created them;
  regenerate after any of those change.
- Requalify after changing RetroArch, the core, offline harness/recording code,
  or recorder settings, and whenever a result is suspect. Play the same Replay
  once with `--realtime-lossless --preset ffv1-flac` and once with the offline
  default. Run `tools/compare_recordings.py` on the two bounded MKVs and require
  exact decoded-frame hashes, PCM SHA-256/sample count, packet PTS/DTS/durations
  and stream metadata. Repeat the offline run and compare it too. The
  Replay-generation run is not the realtime baseline. Routine recordings use
  frame/packet counts, audio-stream presence, logs, and visual samples without
  rerunning all three qualification captures; waveform thresholds are not a
  recording gate.
- The default keeps the Mega-CD startup. Use trimming only when the user
  explicitly asks for a movie-only clip.
- Run RetroArch/Xvfb through `tools/run_headless.sh`; it acquires an EMU token,
  allocates a private X display and RetroArch system directory, and cleans up
  only its own processes.
- If a run is black, silent, or has no duration, treat it as failed and rerun
  after checking `retroarch_<tag>.log` and `xvfb_<tag>.log` in the selected
  tmpfs recording directory printed by `record_movie.sh`.

## Shared-Machine Resource Tokens and Profile Isolation

Independent profiles may run concurrently. Do not use process-name scans as a
scheduler; the project tools coordinate their heavy stages through Linux
`flock` tokens in `tools/resource_tokens.py`:

- **CPU**: `SEGACD_CPU_TOKENS`, defaulting to affinity CPUs minus two.
  `CBRSIM_WORKERS` is both the worker count and the exact CPU-token request.
  Sim holds these tokens only for Extract, Palette, and Quantize; analysis
  rendering and record-preview transcoding also honor them.
- **GPU**: `SEGACD_GPU_TOKENS`, default 1. GPU palette/quantization and NVENC
  muxing acquire it only while using the device.
- **EMU**: `SEGACD_EMU_TOKENS`, default 2. Every `run_headless.sh` invocation
  acquires one. The two-instance default is qualified by same-Replay
  FFV1/FLAC comparisons across two concurrent profiles, with exact decoded
  video, PCM, timestamps, packet durations, and metadata.
- **output stem**: one exclusive lock covers a complete profile pipeline. A
  second process targeting the same `<stem>` fails immediately rather than
  sharing packed files, tmpfs artifacts, or recording paths.

Every interactive `$run` must use `tools/parallel_run.py` for its local
sim-through-HUD pipeline, including a run with only one profile. This retains
the stem lock and sim tmpfs lease across stage boundaries even when unrelated
Codex sessions start runs without coordinating with each other. It divides CPU
workers across jobs, isolates failures, and writes per-profile logs plus a TSV
summary. `--jobs 1` is the single-profile form; `--sequential` retains a
reproducible comparison mode. Direct stage commands are for standalone skills
and diagnosis, not the normal `$run` path.

Xvfb normally allocates a free display with `-displayfd`; `--display :N` is an
explicit diagnostic override and fails if that display is already active.
RetroArch's system directory and generated configs are private to one run.
tmpfs eviction, reservations, lease changes, and public alias replacement are
serialized and atomic.

Never bypass these locks for a normal run, never kill another session's
processes, and only stop processes started by the current session.

### Project Python environments

Do not run project tools with the system `python3` or inherit distribution
site-packages. The repository pins `uv`, CPython and every Python package:

- `tools/bootstrap_python.sh --cpu` creates the CPU environment in `.venv`.
  Use `tools/python.sh` for pack, tests, builds, recording checks and CPU tools.
- `tools/bootstrap_python.sh --gpu` creates the separate CUDA environment in
  `.venv-gpu`. Use
  `tools/python.sh --gpu` for GPU sim/render.
- The launcher must fail when its selected environment is absent. Never add a
  silent fallback to `/usr/bin/python`, a distro NumPy/Pillow, or an older venv.
- `.python-version`, `.python-version-gpu`, `pyproject.toml` and `uv.lock` are
  the reproducible source of truth. The environments themselves remain
  git-ignored.
- The YouTube credential environment is intentionally separate and is not part
  of the codec tool lock.

### NVIDIA/CUDA in the Codex sandbox

The normal Codex workspace sandbox can hide `/dev/nvidia*` even when the host
driver and GPU are healthy. Inside that sandbox, `nvidia-smi` then reports that
it cannot communicate with the driver and CuPy reports `cudaErrorNoDevice`.
Do not treat those sandbox-only symptoms as proof that the NVIDIA driver is
broken, and do not reinstall the driver or reboot the workstation on that
evidence alone.

- Check `nvidia-smi` and a small CuPy allocation outside the sandbox first.
- Run GPU `tools/sim.py` and `tools/render_analysis.py` outside the sandbox so
  they can access the NVIDIA device nodes.
- Use `tools/python.sh --gpu`, which selects the isolated `.venv-gpu` containing
  managed CPython 3.13.14 + NumPy 2.3.5 + Pillow 12.1.1 + CuPy 14.1.1. This
  exact environment completed a full 2,535-frame Lunar sim. The CPU
  `.venv` remains on managed CPython 3.14.4. The former
  `cbrsim-gpu-stable` venv inherited system NumPy/Pillow and is rollback-only.
  The still older `cbrsim-gpu` venv's NumPy 2.5.1 corrupted long runs (segfaults
  and NumPy `SystemError`) even though short CUDA allocations passed. The sim
  rejects that exact unsafe combination before doing work.
- The GPU sim initializes CUDA before its CPU frame-loader pool. Those workers
  must use multiprocessing `spawn`, never `fork`: forking the live CUDA parent
  can segfault the parent interpreter part-way through precomputation.
  CPU-only sim runs may keep the cheaper `fork` path. GPU runs default to the
  verified four feeder processes; `CBRSIM_WORKERS` remains a diagnostic override.
- If `/sbin/ub-device-create --verbose` says the `/dev/nvidia*` nodes already
  exist with correct permissions outside the sandbox, the host device setup is
  healthy; the missing nodes seen inside the sandbox are an isolation artifact.
- Reboot only when the outside-sandbox checks also fail and host kernel logs or
  device state support it.

### Analysis renderer multiprocessing in the Codex sandbox

`tools/render_analysis.py` creates a multiprocessing pool. The normal Codex
workspace sandbox can reject the pool's local IPC socket with
`PermissionError: Operation not permitted` even though rendering is healthy.
Run real-frame and full analysis renders outside the sandbox; do not replace a
failed pool render with a single-process result and call the multiprocessing
path verified. On Linux the renderer explicitly uses the proven `fork` context
because Python 3.14's new `forkserver` default can reset its worker connection
after the large read-only analysis tables have loaded.
