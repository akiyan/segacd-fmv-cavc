EN / [JP](#jp)

# Tunable settings, throttles, and buffers

This is the numeric-settings reference for the Sega CD Constraint-Aware Video Codec
pipeline:

```text
tools/sim.py -> tools/pack_stream.py -> boot/movieplay_*.s
```

It describes shared defaults, hardware limits, and the per-source TOML schema.
Pure register addresses and fixed memory-map details belong in the source and
[`MOVIE.md`](MOVIE.md). A movie's settings belong in a versioned file under
[`profiles/`](profiles/).

Streaming geometry has one source of truth:
[`tools/av_config.py`](tools/av_config.py). The build checks the player's
assembly constants against it. Do not redefine a derived value elsewhere.

The “Where” column uses these short names:

- **cfg**: `tools/av_config.py`
- **sim**: `tools/sim.py`
- **pack**: `tools/pack_stream.py`
- **sp**: `boot/movieplay_sp.s`, Sub CPU
- **ip**: `boot/movieplay_ip.s`, Main CPU

## Workstation concurrency

Concurrency controls change workstation scheduling, not encoded decisions.
`tools/resource_tokens.py` implements cross-process `flock` tokens and one
exclusive lock per media `<stem>`.

| Name | Default | Meaning |
|---|---:|---|
| `SEGACD_CPU_TOKENS` | affinity CPUs minus 2 | Shared CPU-worker capacity. |
| `CBRSIM_WORKERS` | available CPU tokens | Worker count and exact CPU-token request for one heavy stage. |
| `SEGACD_GPU_TOKENS` | 1 | Concurrent GPU palette/quantization or NVENC stages. |
| `SEGACD_EMU_TOKENS` | 2 | Concurrent `run_headless.sh` emulator instances. |
| `SEGACD_RESOURCE_ROOT` | `/dev/shm/segacd-fmv-ttrc/resources` | Lock-file root. |

Sim acquires CPU/GPU tokens only for Extract, Palette, and Quantize.
`render_analysis.py` and record-preview transcoding use the same token pool.
Xvfb allocates a free display dynamically and each emulator gets a private
RetroArch system directory. `tools/parallel_run.py` divides CPU workers across
profiles and retains the sim tmpfs lease between stages. A second process for
the same stem fails immediately; it never shares managed paths or output files.

## Pattern supplies and quality budget

The player has four physical pattern supplies. The encoder also has a
whole-movie quality budget, which is spending permission rather than player
memory.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| `RING_SIZE` / `RING_SIZE_KB` | 420 KiB (`0x69000`) | sp / cfg | Physical PRG-RAM ring backing `PrgBuf`, `0x0D800..0x767FF`; the following 2 KiB is the third Sub-PRG pending destination (`WORD_PENDING3`), not part of the ring. |
| `RING_PHYSICAL_GUARD_KB` | 4 KiB | cfg | Gap between pump back-pressure and the physical ring end. |
| `BACKPRESSURE_KB` | 416 KiB | cfg / sp | Payload draining stops at this occupancy. |
| `RING_DELIVERY_GUARD_KB` | 2 KiB | cfg | One-sector observation boundary below back-pressure; it is not encoder Supply. |
| `scheduled_delivery_cap_kb(fps)` | 374 / 389 / 394 KiB at 15 / 24 / 30 fps | cfg / sim / pack | Hard scheduled occupancy ceiling; equal to the normal PrgBuf ceiling so live jitter remains unspent. |
| `cadence_jitter_reserve_kb(fps)` | 40 / 25 / 20 KiB at 15 / 24 / 30 fps | cfg | `ceil(20 * 30 / fps)` reserve used to derive the normal ceiling. |
| `ring_jitter_headroom_kb(fps)` | 40 / 25 / 20 KiB at 15 / 24 / 30 fps | cfg | Runtime-only arrival headroom from the scheduled ceiling to the 414 KiB observation boundary. |
| `prg_buf_cap_kb(fps)` | 374 / 389 / 394 KiB at 15 / 24 / 30 fps | cfg / sim / pack / sp | Normal PrgBuf, PREBUFFER, and scheduled Supply ceiling: 414 KiB minus the cadence reserve. |
| `quality_budget_kb(fps)` | same as `prg_buf_cap_kb` | cfg / sim | Offline whole-movie quality-accounting capacity. It has no physical meter. |
| `WordBuf0` | build-derived | sp / ip / sim / pack | Boot-preloaded sequence in the even-frame physical bank; its start follows that parity's exact `32*Prg + 22*run` `O_LOADS v2` peak. |
| `WordBuf1` | build-derived | sp / ip / sim / pack | Different boot-preloaded sequence in the odd-frame bank; its start follows that parity's independently computed peak. |
| `DicBuf` | 512 patterns, 16 KiB | ip / sim / pack | Persistent Main-RAM dictionary, reusable by 9-bit index (top bit in the run source field). |
| routing table | `ceil(frames / 2048) * 2 KiB` in each Word-RAM bank | sp / pack | One byte per frame, sector-rounded, maximum 16,384 frames. |
| `APPLY_SIZE` | 34 KiB (`0x8800`) | sp | Circular control-block queue. |
| frame-0 pattern stage | 36 KiB | sp | Boot-only PRG area `0x72000..0x7B000`. |
| boot VRAM sidecar stage | 24 KiB | cfg / pack / sp / ip | Temporary Word-RAM image at bank `+0x0000..+0x6000`; Main consumes it before frame 0 reuses the range. |

`PrgBuf` is the public object; `RING_*` names describe its circular
implementation. `WordBuf0` and `WordBuf1` contain different sequences, not
duplicate caches. `DicBuf` entries are reusable. The analysis labels are Prg,
Wr0, Wr1, and Dic.

`Buf` is an encoder category for an exact cold load funded by saved quality
allowance or a boot-preload credit. It is not a physical buffer.

## Palette table

All segment palettes and the switch schedule are player-embedded build
inputs: pack writes `paltab.bin` / `palidx.bin` beside the split stream, the
Main-IP image incbins both, and the player copies them to Main RAM at entry.
The PALIDX table lists every switch as `(frame, segment)` and the player
advances through it while `next_switch <= frame_no`. Neither `HEADER.DAT`
nor timed controls carry palette bytes at all, so a palette switch consumes
no same-frame stream payload.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| `PALTAB_MAX_SEG` | 16 | cfg / ip | Fixed palette-segment capacity; the encoder merges detected ranges down to it. |
| PALTAB size | 2 KiB | ip | Main RAM `0xFFB200..0xFFB9FF`. |
| `PALIDX_ENTRIES` | 16 (15 switches + sentinel) | cfg / ip | Player-embedded switch table at Main RAM `0xFFBA00..0xFFBA3F`. |
| `PALTAB_STAGE_KB` | 24 KiB / 12 sectors | cfg / pack | BOOT_STAGE size (boot-VRAM sidecar records only). |
| P0/index1 | darkest usable RGB333 colour | sim / pack / ip | Opaque DEBUG HUD background. |
| P0/index15 | brightest usable RGB333 colour | sim / pack / ip | DEBUG HUD text. |

The encoder reorders only existing colours before quantisation. It does not
change the 60-colour multiset, and transparent index 0 remains zero in all four
palette lines.

## Cold cap

Cold means a 32-byte pattern written to VRAM in the current timed frame,
regardless of whether its source is Prg, WordBuf, or DicBuf. Every profile must
set the positive integer `[encoder].cold_cap`; there is no fps-derived fallback
or diagnostic override. The value must not exceed the 1,535-tile resident pool.

The checked-in profile records the source's qualified playback ceiling.
Temporary comparison profiles use the same key, so artifact identity, tmpfs
handoff, sim, pack, and analysis all receive one value. Lowering a qualified
profile is conservative; raising it requires a new full-length playback
qualification with the complete encoder, stream, Sub-CPU, Main-CPU, audio, and
CD-pump path.

The sim and packer share `tools/tile_alloc.py`. The packer replays the frozen
allocation and requires realized cold to remain within the cold cap.
Frame 0 is exempt because the untimed BODY arm installs it before timed
playback.

## Audio

On-disc format version 23 uses checkpointed 22.05 kHz mono IMA ADPCM only. Sub decodes each
chunk to RF5C164 sign-magnitude samples and writes them to the wave-RAM ring.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| decoded `AUDIO_BYTES` | normally 1472 / 920 / 736 at 15 / 24 / 30 fps | cfg / pack / sp | Even decoded samples per effective playback frame. |
| control audio size | `4 + AUDIO_BYTES / 2` | pack / sp | Predictor, step index, reserved byte, and packed IMA codes. |
| `audio_fd` | header offset 58 | cfg / pack / sp | RF5C164 frequency delta derived from chunk size and playback cadence. |
| ADPCM table image | 8,800 B in five sectors | pack / sp | Unchanged lookup bytes copied once to Sub PRG: next-index at `0x07400`, output LUT at `0x09600`, and signed deltas at `0x0C000`. No Word-RAM copy remains. |
| PCM work buffer | 1,536 B at Sub PRG `0x08000..0x085FF` | sp | Reconstructed chunk; no matching Word-RAM reservation remains. |
| Sub preload extension | 940 B staged at Sub PRG `0x7D260` | make / pack / sp | Position-fixed boot table install, PCM initialization, routing preparation, and queue initialization in existing five-sector padding. The qualified first 88 B execute at `0x76800`; the PCM entry runs at `0x7D560`; with routing up to 8 KiB the second entry executes in place at `0x7D2B8` after prebuffer, while longer-route builds copy the complete extension and use `0x76858`. Size/address/hash and overlap are checked before assembly. |
| `SYNC_LEAD` | `0x3000`, 12,288 B | sp | Initial write-ahead lead. |
| startup prefetch request | 30 frames | cfg / pack / sp | Decoded PCM prefix, clamped by wave-RAM capacity and chunk size. |
| `SYNC_MIN` | `0` | sp | Lower accepted lead. |
| `SYNC_MAX` | `0x6800`, 26,624 B | sp | Upper accepted lead; crossing it triggers re-sync. |
| `WAVE_RING_END` | `0x8000`, 32 KiB | sp | Wave-RAM ring size. |

At 20 fps or below, long ADPCM decode loops poll the CDC after at most 512
packed bytes. The 24–30 fps specialized path omits that counter and call.

## CD pump

Startup reads static HEADER through PREBUFFER, reads the finite untimed BODY
arm, expands frame 0, and hands it to Main while the timed reader remains
stopped. After Main displays frame 0, the original `CMD_STREAM` clear edge
starts one continuous timed BODY read at frame 1. PCM remains stopped through
the first `ROM_READN` latency, starts on the first frame-1 control sector, and
Main remains blocked until Sub finishes that physical slot. This keeps the CD
startup interval out of the audio clock while preserving the ordinary
frame-0-to-frame-1 slot/VBlank phase. Timed BODY delivers 75 sectors per
second, so Sub drains ready sectors throughout timed frame expansion and idle
time.

Back-pressure depends on the next sector's destination:

- control checks APPLY space;
- payload checks PrgBuf space;
- pad checks neither.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| low-rate pump interval | every 64 entries or four run descriptors | sp | CDC service during expansion at 20 fps or below. |
| high-rate pump interval | one end poll for a non-empty descriptor frame | sp | Specialized 24–30 fps path. |
| `CMD_SWAP` priority | handshake before opportunistic pump | sp | A pending display handoff takes priority over future-data work. |
| payload full threshold | 416 KiB | sp | Blocks only payload draining. |
| APPLY full threshold | 30 KiB | sp | Blocks only control draining. |
| `FRAME_SECTORS` | 5 useful sectors | pack / sp | Maximum control + payload represented by one routing byte. |
| `HEADER_SECTORS` | 1 metadata sector | pack / sp | Fixed header sector before BOOT_STAGE and other boot regions. |
| boot-stage read boundary | after metadata + BOOT_STAGE + DicBuf | sp | Stop before the Main handoff; restart `HEADER.DAT` at the exact first unread sector. |
| BODY arm boundary | audio preload + frame-0 control + frame-0 patterns | pack / sp | Read exactly this untimed prefix and stop before frame-0 expansion; start the continuous timed suffix only after frame 0 is visible. |
| Word-RAM swap completion | DMNA bit 1 | sp | Hardware busy flag is polled until the 1M bank switch completes. |

`FEATURE_FIXED_N` makes header `vsync_n` authoritative. Main displays every N
VBlanks and Sub uses the matching reduced `1001*N/800` sector accumulator:

- N=2: 199 two-sector and 201 three-sector slots per 400 frames;
- N=4: 199 five-sector and one six-sector slot per 200 frames.

The N=4 sixth sector is physical pad only because the routing byte still caps
useful data at five sectors. Rates without fixed-N use the delivery-paced
`75 / fps_int` accumulator.

`FEATURE_COLD_RUNS` appends four-byte source-aware run descriptors after one
`n_runs` word. Sub validates and expands them into interleaved 22-byte
`O_LOADS v2` records while keeping the CDC poll points. Main consumes those
records in place against the remaining weighted VBlank budget and splits a DMA
run at a residual boundary; the stream carries no encoded VBlank boundaries.
Allocator slots are physical VRAM slots; pattern loads are emitted in ascending
slot order while name updates remain in cell order.

## Main-CPU transfer budget

| Name | Value | Where | Meaning |
|---|---:|---|---|
| `VB_WORDS_H40` | 3,200 DMA-word equivalents/VBlank | ip | Conservative H40 VBlank work budget. |
| `VB_WORDS_H32` | 2,800 DMA-word equivalents/VBlank | ip | Conservative H32 VBlank work budget. |
| `CPU_VDP_WORD_COST` | 4 DMA-word equivalents/word | ip | Cost charged for every CPU-written VDP data word, including DMA first-word repair and CRAM. |
| runtime transfer windows | cadence N | ip | Up to N fixed-cadence VBlanks; a fifth transfer blank at N=4 or a third at N=2 is reported as a warning. |
| `MAIN_CODEGEN_BASE..LIMIT` | 17.5 KiB, `0xFF2100..0xFF66FF` | ip | Generated Main-CPU handlers and blitters. |
| `O_LOADS v2` records | at most the grid cell count; exact parity peaks in PSUP | sp / ip / sim / pack | Sub-built source-aware physical transfer plan consumed by Main in place. |
| run record size | 22 bytes | sp / ip | Pre-swizzled VDP length/source registers, command, raw destination, and raw source. |

Every pattern run uses DMA. A Word-RAM DMA performs the required CPU
first-word repair. Any run that crosses the current residual budget is split
at that boundary and continues at the next fresh VBlank head.
Prg/WordBuf/DicBuf source boundaries also split runs. A compact WordBuf
descriptor is additionally split at its parity ring end before packing, so
the resulting extra control bytes, `O_LOADS v2` record, and first-word repair
are all charged before playback. Each parity's Word-RAM reservation is sized
from the exact whole-encode record and inline-Prg peak, so there is no separate
Main-RAM record limit.

## Physical delivery allowance

| Name | Value | Where | Meaning |
|---|---:|---|---|
| `CD_BYTES_PER_SECOND` | 153,600 B/s | cfg / sim / pack | SEGA-CD 1x ceiling. |
| `SECTOR` | 2,048 B | cfg / pack | One Mode-1 sector. |
| `PAT` | 32 B | pack | One 8x8 4bpp pattern. |
| `PAT_PER_SEC` | 64 | pack | Patterns per sector. |
| BODY gross supply | exact cadence sectors × 2,048 | sim / pack | Physical slot allowance; frame 0 has none. |
| fixed BODY control | header + updates container + audio | sim / pack | Reserved before optional image decisions. |
| provisional run reserve | four bytes per tentative cold choice | sim | Exact run bytes replace this reserve once allocation is known. |

Before each frame decides optional image work, the shared-sector planner knows
the exact cumulative control size through the preceding frame. It rounds
control and Prg payload independently to physical sectors, reserves every CRAM
switch and run descriptor, and computes both a Prg ceiling and a control-byte
ceiling for the current frame.

The prefix ledger and exact delivery schedule use the normal 374/389/394 KiB
PrgBuf capacity at 15/24/30 fps. The corresponding 40/25/20 KiB interval up to
the 414 KiB observation boundary is runtime-only sector-arrival headroom, not
encoder Supply. Every BODY prefix must fit both the five-useful-sector route
and the fps-derived cumulative CD-1x time available at that point. The exact
finite-PrgBuf route must keep `rate_lead_peak` at zero; later pad cannot repay
elapsed display delay. Sim applies the constraint before image decisions,
freezes the resulting proof, and packer requires exact schedule equality.

`buffer_remaining.npz` schema 7 stores:

- Prg/Wr0/Wr1/Dic remaining capacities and per-frame loads;
- whole-movie quality-budget traces;
- physical BODY useful payload, useful control, pad, and total bytes;
- complete-exact and protected Miss-risk demand/reserve traces; and
- the frozen physical schedule and evaluation boundary.

Useful payload + useful control + pad must equal physical bytes in every BODY
slot. Analysis Band divides useful payload and control by that slot's physical
read time. See [`BUEFFERING.md`](BUEFFERING.md) for the planning flow.

## Encoder quality controls

The sim classifies each cell as Raw, Same, Near, Flbk, Buf, or Miss. Raw and Buf
describe funding; Prg/Wr0/Wr1/Dic describe the physical source.

| Name | Default | Meaning |
|---|---:|---|
| resident VRAM pool | 1,535 tiles | Tiles 1–1,535, ending before the first movie name table at `0xC000`. |
| HUD font | 16 tiles at tile 1,664 | Shared by DEBUG and release startup. |
| `CBRSIM_RESIDENT_K` / `RESIDENT_BW` | 24 / 24 | Candidate search depth and rendered mean-colour bucket width. |
| `CBRSIM_NEAR_YM` / `_YP` / `_C` | 10 / 28 / 24 | Near mean/max luma and mean chroma bounds. |
| `CBRSIM_FLBK_IMPROVE_ONLY` / `_MIN_IMPROVE` | 1 / 0 | Flbk is accepted only when it improves the displayed tile. |
| `CBRSIM_TFLBK_YM` / `_YP` / `_C` | 120 / 252 / 200 | Loose Flbk match bounds. |
| `CBRSIM_DETAIL_ALPHA` | 0.0 | Additional detail priority; zero disables it. |
| `AGING_ALPHA` / `WAIT_CAP` | 0.6 / 10 | Distance-weighted waiting pressure, capped at 7×. |
| `CBRSIM_AGING_DIST_REF` / `_STEP_CAP` | 24 / 2.0 | Error reference and maximum pressure increase per frame. |
| `CBRSIM_GHOST_ESCALATE_SEC` | 0.2 s | Continuous approximation duration before Miss severity. |
| output dither | on | Fixed encoder behavior. |
| segmented palettes | on | Fixed encoder behavior. |
| Near reuse | on | Fixed encoder behavior. |
| boot VRAM prefetch | on | Fixed encoder behavior. |
| timed `raw_prefetch` | on | Optional `[encoder]` setting; set `raw_prefetch = false` to disable it. |
| `encoder.cram_quality_priority_search_frames` | 4 | Frames inspected from each CRAM switch. At most one positive-risk frame is selected, and its reserve is reduced only by the predicted protected-demand shortage. Zero disables this priority. |

The allocator commits free/Same/Near results, selects cold exact loads while
reserving two name-entry bytes for every deferred cell, then fills the
remainder with improving Flbk residents.

### Palette controls

| Name | Default | Meaning |
|---|---:|---|
| `palette.algorithm` | `stl4` | Segmented four-line Tile-Lloyd selector. `mosaic-gm` is also available. |
| `PALETTE_MAP_WEIGHT` | 1.0 | Cost for mapping one RGB333 source colour differently across lines. |
| `PALETTE_SEAM_WEIGHT` | 8.0 | Cost for a quantisation discontinuity introduced at an 8x8 boundary. |
| `PALETTE_SEAM_ITERATIONS` | 2 | Deterministic checkerboard assignment passes. |
| palette sample counts | 120, 240, 480 | Whole-movie training candidates. |
| palette validation count | 120 | Separate validation sample. |
| segment train / validation | 240 / 60 frames | Maximum local-segment samples. |
| segment gain | 0.005 relative / 0.002 per pixel | Minimum improvement for a local segment palette. |
| `CBRSIM_PAL_GROW_REL` / `_ABS` / `_MIN_USAGE` | 0.005 / 0.002 / 0.002 | MOSAIC-GM line-growth thresholds. |
| `CBRSIM_PAL_CORE_SIZES` | 4, 6, 8, 10, 12, 14 | Shared-colour counts tested by MOSAIC-GM. |

`CBRSIM_LOOP_PROFILE=1` reports decision-loop timings and candidate-search
counts without changing decisions. Preview and category PNG generation runs in
`tools/render_analysis.py`, not in the required sim path.

## Quality planning

After palette selection, the encoder dry-runs the exact target through the
shared allocator. It builds two future-demand traces:

- **complete exact**: all exact changed cells and cold patterns;
- **protected Miss-risk**: changes outside Near bounds that can become Flbk or
  Miss.

A CRAM segment switch reserves a full name-table refresh in both traces before
optional earlier updates may spend quality allowance. The planner selects
reusable DicBuf entries, predicts the first PrgBuf pressure frame from
cumulative exact cold demand and provisional payload supply, assigns finite
WordBuf credits by water-filling only the suffix from that frame under parity
constraints, and computes backwards reserve curves. This pressure forecast is
lightweight; the one-pass physical sector planner remains the final proof.
Optional Raw/Buf upgrades use complete-exact demand; normal exact work
protects Miss-risk demand.

For each CRAM switch, the encoder inspects the configured number of frames
starting at the switch and selects at most one frame with the largest positive
protected-demand shortage. Only that shortage is subtracted from the selected
frame's reserve target. The remaining future reserve and all physical sector,
cold, PrgBuf, and jitter limits stay unchanged.

The final reserve is zero, so a light suffix releases saved allowance
naturally. The first suffix whose strict reserve stays zero also exposes its
surplus fresh allowance as a terminal-drain credit. Earlier Raw/Buf upgrades
may borrow that credit; it tapers to zero and the signed quality balance must
be non-negative again at the final frame. Demand beyond the complete capacity
is handled by the normal priority, approximation, carry, and Miss rules. The
physical Prg schedule is constructed in `tools/physical_budget.py` and
materialized by `tools/stream_schedule.py`.

## Per-source TOML profiles

Use one `schema_version = 4` file per source/mode combination.

```sh
tools/python.sh tools/sim.py profiles/<profile>.toml
tools/python.sh tools/render_analysis.py profiles/<profile>.toml
make disc CONFIG=profiles/<profile>.toml DEBUG=1
```

`sim.py` resolves the profile once and stores the effective settings and TOML
SHA-256 in `decisions.pkl`. `pack_stream.py` uses that frozen configuration and
requires a supplied TOML hash to match. Editing a profile therefore requires a
new sim run.

The TOML filename is the artifact identity:

```text
out/<profile>/HEADER.DAT
out/<profile>/BODY.DAT
out/<profile>.iso
out/<profile>.cue
tmp/<profile>/
```

| TOML table | Keys | Meaning |
|---|---|---|
| `[source]` | `path`, `fps`, `duration`, optional `sar` | Input and native timing. `sar` repairs source metadata. |
| `[source.preprocess.endpoint_snap]` | `black_max`, `white_min` | Optional RGB888 endpoint snapping before geometry conversion. |
| `[video]` | `mode`, `width`, `height`, `fit`, optional `active_tiles`, `resize_filter`, `master_denoise`, `master_filter`, `raw_filter` | Sega raster and aspect-aware preprocessing. |
| `[output]` | `directory`, optional `reuse`, `emit_decisions` | Human-readable requested sim identity, decoded-input reuse, and decision-log output. Sim bytes use a deterministic direct tmpfs path. |
| `[encoder]` | required `cold_cap`; optional `raw_prefetch`, `cram_quality_priority_search_frames` | Qualified cold cap, timed raw prefetch, and the non-negative CRAM-risk search length. |
| `[palette]` | `algorithm` | Palette selector. |
| `[analysis]` | optional `source_canvas = [width, height]` | Analysis-only source-panel canvas. |

`fit = "pad"` preserves all source pixels and adds bars. `fit = "crop"` fills
the output raster while preserving displayed aspect and may discard outer
source pixels. `resize_filter` defaults to `lanczos`; `master_denoise` defaults
to true. H32 pixel aspect is 8:7 and H40 is 32:35.

`active_tiles` is the number of tiles ever non-black after conversion. Omission
uses the full grid. A smaller value is verified against every master frame.
It affects accounting, not the profile's cold cap.

The loader rejects unknown keys, unsupported modes, non-tile-aligned
dimensions, unsafe profile names, a missing/non-positive/non-integer cold cap,
a cold cap above the resident-pool size, and a negative or non-integer CRAM-risk
search length.
GPU, the
1,535-tile resident pool, dither, segmented palettes, Near, boot prefetch, and
the four physical supplies are fixed behavior.

## Build switches

| Name | Default | Meaning |
|---|---:|---|
| `MAIN_CODEGEN` | 1 | Generate specialized bitmap handlers and name-table blitters. Zero selects the reference bit loop. |
| `PLAYER_SPECIALIZE` | 1 | Bake generated header/profile constants into both player objects. Zero selects runtime header reads. |
| `DEBUG` | 1 in recording tools | Display the values-only HUD. Set release explicitly when required. |

Specialized builds compare the CRC-32 header signature before playback. The
disc system area reserves `0x6000..0x73FF` for an at-most-5-KiB SP, which the
BIOS loads contiguously at Sub PRG `0x6000`. Boot-only 64-KiB ISO directory
scratch uses `0x67000..0x76FFF` before the timed ring or frame-0 stage owns that
range. This boot arrangement does not consume PrgBuf or change timed CD
delivery. The checked extension occupies
otherwise-unused padding after the ADPCM lookup data in HEADER.DAT; startup
copies its qualified 88-byte entry from the five-sector stage to the unused
timed-ring tail and runs its wave-RAM initializer from staged offset `+0x300`.
The routing entry executes after prebuffer from the protected stage tail when
the route is at most 8 KiB; longer-route builds copy the complete extension
before staging routing. That entry also initializes the ring, APPLY, and
frame-0 queue state. Standard specialized H32/H40 DEBUG keeps
its G state and measurement inline in the resident SP. Startup shows four hexadecimal digits containing safe PrgBuf
preload KiB; a failure shows `BADx`.

## DEBUG HUD limits

[`HUD.md`](HUD.md) is the complete field and OCR reference. The configuration
relevant limits are:

| Field | Healthy meaning |
|---|---|
| S | zero CD re-seeks is ideal |
| D | zero residual stream desync |
| R | zero audio re-sync |
| L | audio lead remains within `SYNC_MIN..SYNC_MAX` |
| C | zero blocking pumps is ideal |
| M | below 2 avoids an extra VBlank spill |
| N | at most the grid cell count; cadence spill is reported by the transfer-window fields |
| J | at most 45 / 30 / 25 KiB above normal PrgBuf at 15 / 24 / 30 fps |

Frame 0 is excluded from HUD values and scale maxima because it is boot work,
not timed playback.

<a id="jp"></a>

# 調整可能な設定、throttle、buffer

Sega CD Constraint-Aware Video Codec pipelineの数値設定リファレンスです。

```text
tools/sim.py -> tools/pack_stream.py -> boot/movieplay_*.s
```

共通default、hardware limit、sourceごとのTOML schemaを扱います。純粋なregister
addressと固定memory mapの詳細はsource codeと [`MOVIE.md`](MOVIE.md) に置きます。
movie固有の設定は [`profiles/`](profiles/) 以下のversion管理されたfileに置きます。

streaming geometryの正本は [`tools/av_config.py`](tools/av_config.py) だけです。
buildがplayer assembly constantとの一致を確認します。導出値を別の場所で再定義しては
いけません。

「場所」列の短縮名は次の通りです。

- **cfg**: `tools/av_config.py`
- **sim**: `tools/sim.py`
- **pack**: `tools/pack_stream.py`
- **sp**: `boot/movieplay_sp.s`、Sub CPU
- **ip**: `boot/movieplay_ip.s`、Main CPU

## Workstation concurrency

concurrency controlはworkstation上のscheduleだけを変え、encode decisionは変えません。
`tools/resource_tokens.py` はprocess間 `flock` tokenと
media `<stem>` ごとのexclusive lockを実装します。

| Name | default | 意味 |
|---|---:|---|
| `SEGACD_CPU_TOKENS` | affinity CPU数 - 2 | 共有CPU worker容量。 |
| `CBRSIM_WORKERS` | 使用可能なCPU token数 | 1つのheavy stageのworker数かつ正確なCPU token要求数。 |
| `SEGACD_GPU_TOKENS` | 1 | 同時GPU palette/quantizationまたはNVENC stage数。 |
| `SEGACD_EMU_TOKENS` | 2 | 同時 `run_headless.sh` emulator instance数。 |
| `SEGACD_RESOURCE_ROOT` | `/dev/shm/segacd-fmv-ttrc/resources` | lock file root。 |

simはExtract、Palette、Quantizeの間だけCPU/GPU tokenを取得します。
`render_analysis.py` とrecord preview transcodeも同じtoken poolを使います。
Xvfbは空きdisplayを動的に割り当て、各emulatorはprivate RetroArch system directoryを
使います。`tools/parallel_run.py` はprofile間でCPU workerを分配し、stage間もsimの
tmpfs leaseを保持します。同じstemの2つ目のprocessは即時FAILし、managed pathや
output fileを共有しません。

## Pattern供給とquality budget

playerには4つの物理pattern供給があります。encoderにはmovie全体のquality budgetも
ありますが、これはplayer memoryではなく支出許可です。

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| `RING_SIZE` / `RING_SIZE_KB` | 420 KiB (`0x69000`) | sp / cfg | PrgBuf物理PRG-RAM ring `0x0D800..0x767FF`。直後2 KiBは3本目のSub-PRG pending destination（`WORD_PENDING3`）でring外。 |
| `RING_PHYSICAL_GUARD_KB` | 4 KiB | cfg | pump back-pressureと物理ring末尾の間隔。 |
| `BACKPRESSURE_KB` | 416 KiB | cfg / sp | このoccupancyでpayload drainを止める。 |
| `RING_DELIVERY_GUARD_KB` | 2 KiB | cfg | back-pressureより1 sector手前の観測境界。encoder Supplyではない。 |
| `scheduled_delivery_cap_kb(fps)` | 15 / 24 / 30 fpsで374 / 389 / 394 KiB | cfg / sim / pack | schedule上のhard occupancy上限。live jitterを未使用で残すため通常PrgBuf上限と同じ。 |
| `cadence_jitter_reserve_kb(fps)` | 15 / 24 / 30 fpsで40 / 25 / 20 KiB | cfg | 通常上限の導出に使う `ceil(20 * 30 / fps)` reserve。 |
| `ring_jitter_headroom_kb(fps)` | 15 / 24 / 30 fpsで40 / 25 / 20 KiB | cfg | scheduled上限から414 KiB観測境界までのruntime専用到着headroom。 |
| `prg_buf_cap_kb(fps)` | 15 / 24 / 30 fpsで374 / 389 / 394 KiB | cfg / sim / pack / sp | 通常PrgBuf、PREBUFFER、scheduled Supply上限。414 KiBからcadence reserveを引く。 |
| `quality_budget_kb(fps)` | `prg_buf_cap_kb` と同じ | cfg / sim | offlineのmovie全体quality accounting容量。物理meterはない。 |
| `WordBuf0` | buildから導出 | sp / ip / sim / pack | 偶数frame physical bankのboot preload sequence。開始位置はそのparityの正確な`32*Prg + 22*run` `O_LOADS v2`ピーク直後。 |
| `WordBuf1` | buildから導出 | sp / ip / sim / pack | 奇数frame bankの異なるboot preload sequence。開始位置は独立計算したそのparityピーク直後。 |
| `DicBuf` | 512 patterns、16 KiB | ip / sim / pack | 9-bit index（最上位bitはrun source field）で再利用するpersistent Main-RAM dictionary。 |
| routing table | 各Word-RAM bankに `ceil(frames / 2048) * 2 KiB` | sp / pack | frame当たり1 byte、sector丸め、最大16,384 frame。 |
| `APPLY_SIZE` | 34 KiB (`0x8800`) | sp | control blockのcircular queue。 |
| frame-0 pattern stage | 36 KiB | sp | boot専用PRG領域 `0x72000..0x7B000`。 |
| boot VRAM sidecar stage | 24 KiB | cfg / pack / sp / ip | bank `+0x0000..+0x6000` のtemporary Word-RAM image。Mainが消費した後にframe 0が同じrangeを再利用する。 |

`PrgBuf` が公開名で、`RING_*` はcircular実装を示します。`WordBuf0` と
`WordBuf1` は異なるsequenceで、duplicate cacheではありません。`DicBuf` entryは
再利用できます。解析上の短縮名はPrg、Wr0、Wr1、Dicです。

`Buf` は保存済みquality allowanceまたはboot-preload creditで正確なcold loadを
賄うencoder categoryです。物理bufferではありません。

## Palette table

全segment paletteと切替スケジュールはplayer内蔵のビルド入力です: packが
split streamの隣に `paltab.bin` / `palidx.bin` を書き、Main-IP imageが両方を
incbinし、playerがentry直後にMain RAMへcopyします。PALIDX表が全切替を
`(frame, segment)` で列挙し、playerは `next_switch <= frame_no` の間advance
します。`HEADER.DAT` もtimed controlもpalette byteを一切持たないため、
palette switchは同frameのstream payloadを消費しません。

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| `PALTAB_MAX_SEG` | 16 | cfg / ip | 固定palette segment上限。encoderは検出rangeをここまでmergeする。 |
| PALTAB size | 2 KiB | ip | Main RAM `0xFFB200..0xFFB9FF`。 |
| `PALIDX_ENTRIES` | 16（15切替+番兵） | cfg / ip | player内蔵切替表。Main RAM `0xFFBA00..0xFFBA3F`。 |
| `PALTAB_STAGE_KB` | 24 KiB / 12 sectors | cfg / pack | BOOT_STAGE size（boot-VRAM sidecar record専用）。 |
| P0/index1 | 使用可能な最暗RGB333色 | sim / pack / ip | 不透明DEBUG HUD background。 |
| P0/index15 | 使用可能な最明RGB333色 | sim / pack / ip | DEBUG HUD text。 |

encoderは量子化前に既存色の順序だけを変えます。60色の集合は変えず、4本すべての
palette lineでtransparent index 0をzeroのままにします。

## Cold cap

Coldは、sourceがPrg、WordBuf、DicBufのどれでも、現在のtimed frameでVRAMへ書く
32-byte patternです。すべてのprofileが正のinteger `[encoder].cold_cap` を必ず指定し、
fps由来fallbackや診断overrideは使いません。値は1,535-tile resident pool以下にします。

checked-in profileは、そのsourceでqualificationした再生上限を記録します。一時的な比較
profileも同じkeyを使うため、artifact identity、tmpfs handoff、sim、pack、analysisへ
1つの値がそのまま流れます。Qualification済みprofileから値を下げるのは保守的な変更
です。引き上げる場合はencoder、stream、Sub CPU、Main CPU、audio、CD pumpを含む
完全な経路で新しい全編再生qualificationが必要です。

simとpackerは `tools/tile_alloc.py` を共有します。packerは固定済みallocationを再生し、
realized coldがcold cap内にあることを要求します。frame 0はtimed playback前に
untimed BODY armが構築するため対象外です。

## Audio

On-disc format version 23のaudioはcheckpointed 22.05 kHz mono IMA ADPCMだけです。Subが各chunkを
RF5C164 sign-magnitude sampleへdecodeし、wave-RAM ringへ書きます。

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| decoded `AUDIO_BYTES` | 15 / 24 / 30 fpsで通常1472 / 920 / 736 | cfg / pack / sp | 実効playback frameごとの偶数decoded sample数。 |
| control audio size | `4 + AUDIO_BYTES / 2` | pack / sp | predictor、step index、reserved byte、packed IMA code。 |
| `audio_fd` | header offset 58 | cfg / pack / sp | chunk sizeとplayback cadenceから導出するRF5C164 frequency delta。 |
| ADPCM table image | 5 sectors内の8,800 B | pack / sp | 変更しないlookup byteをSub PRGへ1回copyする。next-indexは`0x07400`、output LUTは`0x09600`、signed deltaは`0x0C000`。Word-RAM copyはない。 |
| PCM work buffer | Sub PRG `0x08000..0x085FF`の1,536 B | sp | 再構築chunk。対応するWord-RAM予約はない。 |
| Sub preload extension | Sub PRG `0x7D260`へstageする940 B | make / pack / sp | 既存5-sector padding内のposition-fixed boot table install・PCM initialization・routing preparation・queue initialization。Qualified済み先頭88 Bは`0x76800`、PCM入口は`0x7D560`で実行する。routingが8 KiB以下ならprebuffer後に第2入口を`0x7D2B8`でそのまま実行し、長いroutingのbuildはextension全体をcopyして`0x76858`を使う。assemble前にsize/address/hashとoverlapを検査する。 |
| `SYNC_LEAD` | `0x3000`、12,288 B | sp | 初期write-ahead lead。 |
| startup prefetch request | 30 frames | cfg / pack / sp | wave-RAM容量とchunk sizeでclampするdecoded PCM prefix。 |
| `SYNC_MIN` | `0` | sp | 許容lead下限。 |
| `SYNC_MAX` | `0x6800`、26,624 B | sp | 許容lead上限。超えるとre-sync。 |
| `WAVE_RING_END` | `0x8000`、32 KiB | sp | wave-RAM ring size。 |

20 fps以下では長いADPCM decode loopが最大512 packed byteごとにCDCをpollします。
24〜30 fpsのspecialized pathはこのcounterとcallを省きます。

## CD pump

startupはstatic HEADERからPREBUFFERまでを読み、有限でuntimedなBODY armを読んで
frame 0を展開し、timed readerを停止したままMainへ渡します。Mainがframe 0を表示した
後、元の `CMD_STREAM` をclearするedgeでframe 1を起点とするtimed BODYの連続readを
開始します。最初の `ROM_READN` latency中はPCMを停止し、最初のframe-1 control sectorで
PCMを開始し、そのphysical slotが完了するまでMainを待たせます。これによりCD起動待ちは
audio clockへ入らず、通常のframe-0-to-frame-1 slot/VBlank位相を維持します。Timed
BODYは毎秒75 sectorを届けるため、Subはtimed frame展開中とidle中の両方でready
sectorをdrainします。

back-pressureは次sectorの行き先で決まります。

- controlはAPPLY空きを確認する
- payloadはPrgBuf空きを確認する
- padはどちらも確認しない

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| low-rate pump interval | 64 entriesまたは4 run descriptorsごと | sp | 20 fps以下の展開中CDC service。 |
| high-rate pump interval | non-empty descriptor frame末尾に1回 | sp | specialized 24〜30 fps path。 |
| `CMD_SWAP` priority | opportunistic pumpよりhandshake優先 | sp | pending display handoffを将来data workより先に処理する。 |
| payload full threshold | 416 KiB | sp | payload drainだけを止める。 |
| APPLY full threshold | 30 KiB | sp | control drainだけを止める。 |
| `FRAME_SECTORS` | 有効5 sectors | pack / sp | 1 routing byteが表すcontrol + payload上限。 |
| `HEADER_SECTORS` | metadata 1 sector | pack / sp | BOOT_STAGEなどのboot領域より前にある固定header sector。 |
| boot-stage read境界 | metadata + BOOT_STAGE + DicBufの直後 | sp | Main handoff前に停止し、正確な最初の未読sectorから `HEADER.DAT` を再開する。 |
| BODY arm境界 | audio preload + frame-0 control + frame-0 patterns | pack / sp | このuntimed prefixだけを読み、frame-0展開前に停止する。連続timed suffixはframe 0表示後にだけ開始する。 |
| Word-RAM swap completion | DMNA bit 1 | sp | 1M bank switch完了までhardware busy flagをpollする。 |

`FEATURE_FIXED_N` はheaderの `vsync_n` を正式なcadenceにします。MainはN VBlankごとに
表示し、Subは対応する `1001*N/800` の約分sector accumulatorを使います。

- N=2: 400 frame当たり2-sector slotが199個、3-sector slotが201個
- N=4: 200 frame当たり5-sector slotが199個、6-sector slotが1個

N=4の6個目はphysical padだけです。routing byteの有効data上限は5 sectorのままです。
fixed-Nでないrateはdelivery-paced `75 / fps_int` accumulatorを使います。

`FEATURE_COLD_RUNS` は各controlへ1個の`n_runs` wordと、それに続く4-byte
source-aware run descriptorを追加します。SubはCDC poll位置を保ちながら
descriptorを検証し、interleaveした22-byte `O_LOADS v2` recordへ展開します。
Mainはそのrecordをin-placeでweighted VBlank budgetの残量に対してscheduleし、
DMA runを残budget境界で分割します。Streamはencoded VBlank boundaryを持ちません。
Allocator slotは物理VRAM slotで、pattern loadはslot昇順、name updateはcell順です。

## Main-CPU transfer budget

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| `VB_WORDS_H40` | 3,200 DMA-word相当/VBlank | ip | 安全側のH40 VBlank work budget。 |
| `VB_WORDS_H32` | 2,800 DMA-word相当/VBlank | ip | 安全側のH32 VBlank work budget。 |
| `CPU_VDP_WORD_COST` | 4 DMA-word相当/word | ip | DMA先頭word補修とCRAMを含む、CPUがVDP dataへ書く各wordのcharge。 |
| runtime transfer windows | cadence N | ip | fixed cadenceの最大N VBlank。N=4の5本目、N=2の3本目はwarningとして報告する。 |
| `MAIN_CODEGEN_BASE..LIMIT` | 17.5 KiB、`0xFF2100..0xFF66FF` | ip | 生成するMain-CPU handlerとblitter。 |
| `O_LOADS v2` records | grid cell数以下。正確なparityピークはPSUP | sp / ip / sim / pack | Subが構築しMainがin-placeで消費するsource-aware physical transfer計画。 |
| run record size | 22 bytes | sp / ip | 事前変換済みVDP length/source register、command、raw destination、raw source。 |

全pattern runがDMAを使います。Word-RAM DMAは必須のCPU first-word repairを
行います。Current残budget境界を越えるrunはそこで分割し、次のfresh VBlank headから
続きを行います。Prg/WordBuf/DicBufのsource境界もrunを分けます。CompactなWordBuf
descriptorはpack前にparity ring末尾でも分割するため、追加control bytes、
`O_LOADS v2` record、first-word repairをplayback前にすべてchargeします。各parityの
Word-RAM予約はencode全体の正確なrecordとinline Prgピークから決めるため、独立した
Main-RAM record上限はありません。

## 物理delivery allowance

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| `CD_BYTES_PER_SECOND` | 153,600 B/s | cfg / sim / pack | SEGA-CD 1x上限。 |
| `SECTOR` | 2,048 B | cfg / pack | Mode-1 sector 1個。 |
| `PAT` | 32 B | pack | 8x8 4bpp pattern 1個。 |
| `PAT_PER_SEC` | 64 | pack | sector当たりpattern数。 |
| BODY gross supply | 正確なcadence sector数 × 2,048 | sim / pack | 物理slot allowance。frame 0にはない。 |
| fixed BODY control | header + update container + audio | sim / pack | optional image decisionより先に予約する。 |
| provisional run reserve | tentative cold choice当たり4 byte | sim | allocation判明後に正確なrun byteで置き換える。 |

各frameがoptional image workを決める前に、shared-sector plannerは直前frameまでの正確な
累積control sizeを知っています。controlとPrg payloadを独立に物理sectorへ丸め、全CRAM
switchとrun descriptorを予約し、current frameのPrg ceilingとcontrol-byte ceilingを
計算します。

prefix ledgerと正確なdelivery scheduleは、15/24/30 fpsで通常PrgBuf容量
374/389/394 KiBを使います。414 KiB観測境界までの40/25/20 KiBはruntime専用の
sector到着headroomで、encoder Supplyではありません。各BODY prefixはこの容量の下で、
有効5-sector routeと、その時点までにfpsから導出した累積CD-1x時間の両方へ収まる必要が
あります。有限PrgBufを含む正確なrouteは `rate_lead_peak` をzeroに保ち、後のpadで
経過済み表示遅延を返済することは認めません。simは画像決定前に制約を適用してproofを
固定し、packerがscheduleの完全一致を要求します。

`buffer_remaining.npz` schema 7は次を保存します。

- Prg/Wr0/Wr1/Dicの残量、容量、frame別load
- movie全体quality-budget trace
- 物理BODYの有効payload、有効control、pad、総byte
- complete-exactとprotected Miss-riskのdemand/reserve trace
- 固定済みphysical scheduleとevaluation boundary

各BODY slotで有効payload + 有効control + padがphysical byteと一致しなければなりません。
解析Bandは有効payloadとcontrolをそのslotの物理read時間で割ります。planning flowは
[`BUEFFERING.md`](BUEFFERING.md) を参照してください。

## Encoder quality control

simは各cellをRaw、Same、Near、Flbk、Buf、Missに分類します。RawとBufはfundingを示し、
Prg/Wr0/Wr1/Dicは物理sourceを示します。

| Name | Default | 意味 |
|---|---:|---|
| resident VRAM pool | 1,535 tiles | tile 1〜1,535。最初のmovie name table `0xC000` より前まで。 |
| HUD font | tile 1,664から16 tiles | DEBUGとrelease startupで共有。 |
| `CBRSIM_RESIDENT_K` / `RESIDENT_BW` | 24 / 24 | candidate search深さとrendered mean-colour bucket幅。 |
| `CBRSIM_NEAR_YM` / `_YP` / `_C` | 10 / 28 / 24 | Nearのmean/max luma、mean chroma境界。 |
| `CBRSIM_FLBK_IMPROVE_ONLY` / `_MIN_IMPROVE` | 1 / 0 | 表示tileを改善するときだけFlbkを採用。 |
| `CBRSIM_TFLBK_YM` / `_YP` / `_C` | 120 / 252 / 200 | 緩いFlbk match境界。 |
| `CBRSIM_DETAIL_ALPHA` | 0.0 | detail追加priority。zeroで無効。 |
| `AGING_ALPHA` / `WAIT_CAP` | 0.6 / 10 | distance-weighted waiting pressure、最大7倍。 |
| `CBRSIM_AGING_DIST_REF` / `_STEP_CAP` | 24 / 2.0 | error基準とframeごとのpressure増加上限。 |
| `CBRSIM_GHOST_ESCALATE_SEC` | 0.2 s | 連続近似をMiss severityへ上げるまでの時間。 |
| output dither | on | 固定encoder behavior。 |
| segmented palettes | on | 固定encoder behavior。 |
| Near reuse | on | 固定encoder behavior。 |
| boot VRAM prefetch | on | 固定encoder behavior。 |
| timed `raw_prefetch` | on | optional `[encoder]` setting。`raw_prefetch = false`で無効化。 |
| `encoder.cram_quality_priority_search_frames` | 4 | 各CRAM switchから調べるframe数。positive riskが最大の1 frameだけを選び、予測protected-demand不足分だけreserveを減らします。0で無効です。 |

allocatorはfree/Same/Near結果を確定し、全deferred cellの2-byte name entryを予約しながら
cold exact loadを選び、残りを改善するFlbk residentで埋めます。

### Palette control

| Name | Default | 意味 |
|---|---:|---|
| `palette.algorithm` | `stl4` | segmented four-line Tile-Lloyd selector。`mosaic-gm` も選択可能。 |
| `PALETTE_MAP_WEIGHT` | 1.0 | 1つのRGB333 source colourをline間で別mappingするcost。 |
| `PALETTE_SEAM_WEIGHT` | 8.0 | 8x8境界に量子化不連続を作るcost。 |
| `PALETTE_SEAM_ITERATIONS` | 2 | deterministic checkerboard assignment pass数。 |
| palette sample counts | 120, 240, 480 | movie全体training候補。 |
| palette validation count | 120 | 独立validation sample。 |
| segment train / validation | 240 / 60 frames | local segment sample上限。 |
| segment gain | 0.005 relative / 0.002 per pixel | local segment palette採用の最小改善量。 |
| `CBRSIM_PAL_GROW_REL` / `_ABS` / `_MIN_USAGE` | 0.005 / 0.002 / 0.002 | MOSAIC-GM line growth境界。 |
| `CBRSIM_PAL_CORE_SIZES` | 4, 6, 8, 10, 12, 14 | MOSAIC-GMが試すshared-colour数。 |

`CBRSIM_LOOP_PROFILE=1` はdecision loop timingとcandidate search数を報告し、decisionは
変えません。previewとcategory PNG生成は必須sim pathではなく
`tools/render_analysis.py` で実行します。

## Quality planning

palette選択後、encoderは正確なtargetをshared allocatorでdry-runします。2つの将来
demand traceを作ります。

- **complete exact**: 全exact changed cellとcold pattern
- **protected Miss-risk**: Near境界外でFlbkまたはMissになり得るchange

CRAM segment switchは、先行するoptional updateがquality allowanceを使う前に、両trace
へfull name-table refreshを予約します。plannerは再利用可能なDicBuf entryを選び、
exact cold demandと暫定payload供給の累積から最初のPrgBuf pressure frameを予測し、その
frame以降のsuffix内だけをparity制約付きでwater-fillして有限WordBuf creditを割り当て、
後ろ向きreserve curveを計算します。このpressure予測は軽量で、one-pass physical sector
plannerが最終proofのままです。Optional Raw/Buf upgradeはcomplete-exact demand、通常
exact workはMiss-risk demandを保護します。

各CRAM switchについて、encoderはswitch frameから設定frame数を調べ、positiveな
protected-demand不足が最大の1 frameだけを選びます。選択frameのreserve targetから
その不足分だけを引きます。残りの将来reserveと、物理sector、cold、PrgBuf、jitterの
全limitは変えません。

最終reserveはzeroなので、軽い末尾では保存済みallowanceが自然に解放されます。Strict
reserveが継続してzeroになる最初のsuffixは、余るfresh allowanceをterminal-drain
creditとして公開します。前のRaw/Buf格上げはこのcreditを借りられますが、creditは最終
frameでzeroになり、signed quality balanceもnon-negativeへ戻る必要があります。全容量を
超えるdemandは通常のpriority、approximation、carry、Miss ruleで処理します。物理Prg
scheduleは `tools/physical_budget.py` が構築し、`tools/stream_schedule.py` が具体化します。

## SourceごとのTOML profile

source/modeの組み合わせごとに `schema_version = 4` のfileを1つ使います。

```sh
tools/python.sh tools/sim.py profiles/<profile>.toml
tools/python.sh tools/render_analysis.py profiles/<profile>.toml
make disc CONFIG=profiles/<profile>.toml DEBUG=1
```

`sim.py` はprofileを1回解決し、effective settingとTOML SHA-256を `decisions.pkl` に
保存します。`pack_stream.py` はその固定済みconfigurationを使い、指定TOMLのhash一致を
要求します。profileを編集した場合は新しいsim runが必要です。

TOML filenameがartifact identityです。

```text
out/<profile>/HEADER.DAT
out/<profile>/BODY.DAT
out/<profile>.iso
out/<profile>.cue
tmp/<profile>/
```

| TOML table | Keys | 意味 |
|---|---|---|
| `[source]` | `path`, `fps`, `duration`, optional `sar` | inputとnative timing。`sar` はsource metadataを補正する。 |
| `[source.preprocess.endpoint_snap]` | `black_max`, `white_min` | geometry変換前のoptional RGB888 endpoint snapping。 |
| `[video]` | `mode`, `width`, `height`, `fit`, optional `active_tiles`, `resize_filter`, `master_denoise`, `master_filter`, `raw_filter` | Sega rasterとaspect-aware preprocessing。 |
| `[output]` | `directory`, optional `reuse`, `emit_decisions` | human-readableなsim要求identity、decoded-input reuse、decision-log output。sim byteはdeterministicなtmpfs実体pathを直接使う。 |
| `[encoder]` | 必須`cold_cap`、optional `raw_prefetch`、`cram_quality_priority_search_frames` | 認定済みcold cap、timed raw prefetch、非負のCRAM-risk search長。 |
| `[palette]` | `algorithm` | palette selector。 |
| `[analysis]` | optional `source_canvas = [width, height]` | 解析専用Source panel canvas。 |

`fit = "pad"` は全source pixelを保持し、barを追加します。`fit = "crop"` は表示aspectを
保ってoutput rasterを埋めるため、source外周を捨てる場合があります。
`resize_filter` defaultは `lanczos`、`master_denoise` defaultはtrueです。H32 pixel
aspectは8:7、H40は32:35です。

`active_tiles` は変換後に一度でもnon-blackになるtile数です。省略時はfull gridを使い、
小さい値は全master frameに対して検証します。accountingには影響しますがprofileの
cold capには影響しません。

loaderは未知key、未対応mode、tile境界に揃わないdimension、安全でないprofile名、
未指定・非positive・非integerのcold cap、resident-pool sizeを超えるcold cap、負または
非integerのCRAM-risk search長を拒否します。
GPU、1,535-tile resident pool、dither、
segmented palette、Near、boot prefetch、4つの物理供給は固定behaviorです。

## Build switch

| Name | Default | 意味 |
|---|---:|---|
| `MAIN_CODEGEN` | 1 | specialized bitmap handlerとname-table blitterを生成する。zeroはreference bit loop。 |
| `PLAYER_SPECIALIZE` | 1 | 生成済みheader/profile constantを両player objectへ埋め込む。zeroはruntime header read。 |
| `DEBUG` | recording toolでは1 | values-only HUDを表示する。必要なときだけreleaseを明示する。 |

specialized buildはplayback前にCRC-32 header signatureを比較します。Resident Subの
disc system areaは`0x6000..0x73FF`を最大5 KiBのSP用に予約し、BIOSがSub PRG
`0x6000`へ連続loadします。Boot専用64 KiB ISO directory scratchは、timed ringや
frame-0 stageがそのrangeを所有する前に`0x67000..0x76FFF`を使います。このboot配置は
PrgBufを消費せず、timed CD deliveryも変えません。検査済みextensionはHEADER.DAT内の
ADPCM lookup data直後にある未使用padding
へ配置し、startupがqualified済み88-byte入口を5-sector stageから未使用timed-ring
tailへcopyし、staged offset `+0x300`からwave-RAM initializerを実行します。
routingが8 KiB以下ならrouting入口はprebuffer後に保護済みstage tailから実行し、
長いroutingのbuildはrouting stage前にextension全体をcopyします。同じ入口が
timed playback前にring、APPLY、frame-0 queue stateを初期化します。
Standard specialized H32/H40 DEBUGのG stateとmeasurementはresident SP内にinlineで保持します。
startupは安全に受信済みのPrgBuf preload
KiBを4桁hexで表示し、failureは`BADx`を表示します。

## DEBUG HUD limit

fieldとOCRの完全な説明は [`HUD.md`](HUD.md) にあります。設定に関係するlimitは次の
通りです。

| Field | 健全な意味 |
|---|---|
| S | CD re-seekはzeroが理想 |
| D | residual stream desyncがzero |
| R | audio re-syncがzero |
| L | audio leadが `SYNC_MIN..SYNC_MAX` 内 |
| C | blocking pumpはzeroが理想 |
| M | 2未満ならextra VBlank spillなし |
| N | grid cell数以下。cadence spillはtransfer-window fieldで報告 |
| J | 通常PrgBuf超過が15 / 24 / 30 fpsで45 / 30 / 25 KiB以下 |

frame 0はboot workでtimed playbackではないため、HUD valueとscale maximumから除外します。
