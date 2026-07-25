EN / [JP](#jp)

# Tunable settings, throttles, and buffers

This is the numeric-settings reference for the Tile Texture Reuse Codec
pipeline:

```text
tools/sim.py -> tools/pack_stream.py -> boot/movieplay_*.s
```

It describes shared defaults, hardware limits, and the per-source TOML schema.
Pure register addresses and fixed memory-map details belong in the source and
[`MOVIE.md`](MOVIE.md). A movie's settings belong in a versioned file under
[`configs/`](configs/).

Streaming geometry has one source of truth:
[`tools/av_config.py`](tools/av_config.py). The build checks the player's
assembly constants against it. Do not redefine a derived value elsewhere.

The “Where” column uses these short names:

- **cfg**: `tools/av_config.py`
- **sim**: `tools/sim.py`
- **pack**: `tools/pack_stream.py`
- **sp**: `boot/movieplay_sp.s`, Sub CPU
- **ip**: `boot/movieplay_ip.s`, Main CPU

## Pattern supplies and quality budget

The player has four physical pattern supplies. The encoder also has a
whole-movie quality budget, which is spending permission rather than player
memory.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| `RING_SIZE` / `RING_SIZE_KB` | 428 KiB (`0x6B000`) | sp / cfg | Physical PRG-RAM ring backing `PrgBuf`, from `0x0C000` to `APPLY_BASE`. |
| `RING_PHYSICAL_GUARD_KB` | 4 KiB | cfg | Gap between pump back-pressure and the physical ring end. |
| `BACKPRESSURE_KB` | 424 KiB | cfg / sp | Payload draining stops at this occupancy. |
| `RING_DELIVERY_GUARD_KB` | 2 KiB | cfg | One sector kept below back-pressure. |
| `physical_delivery_cap_kb(fps)` | 422 KiB | cfg / sim / pack | Hard scheduled occupancy ceiling. |
| `ring_jitter_headroom_kb(fps)` | 40 / 25 / 20 KiB at 15 / 24 / 30 fps | cfg | `ceil(20 * 30 / fps)` delivery-jitter reserve. |
| `prg_buf_cap_kb(fps)` | 382 / 397 / 402 KiB at 15 / 24 / 30 fps | cfg / sim / pack / sp | Normal PrgBuf and PREBUFFER ceiling: 422 KiB minus jitter reserve. |
| `quality_budget_kb(fps)` | same as `prg_buf_cap_kb` | cfg / sim | Offline whole-movie quality-accounting capacity. It has no physical meter. |
| `WordBuf0` | 880 patterns, 27.5 KiB | sp / ip / sim / pack | Boot-preloaded sequence in physical bank 0; serves even timed frames. |
| `WordBuf1` | 880 patterns, 27.5 KiB | sp / ip / sim / pack | Different boot-preloaded sequence in physical bank 1; serves odd timed frames. |
| `DicBuf` | 256 patterns, 8 KiB | ip / sim / pack | Persistent Main-RAM dictionary, reusable by 8-bit index. |
| routing table | 16 KiB in each Word-RAM bank | sp / pack | One byte per frame, maximum 16,384 frames. |
| `APPLY_SIZE` | 34 KiB (`0x8800`) | sp | Circular control-block queue. |
| frame-0 pattern stage | 36 KiB | sp | Boot-only PRG area `0x71000..0x7A000`. |
| boot VRAM sidecar stage | 24 KiB | cfg / pack / sp / ip | Word-RAM boot image at bank `+0xA000..+0x10000`; it can fill unreferenced resident VRAM before BODY starts. |

`PrgBuf` is the public object; `RING_*` names describe its circular
implementation. `WordBuf0` and `WordBuf1` contain different sequences, not
duplicate caches. `DicBuf` entries are reusable. The analysis labels are Prg,
Wr0, Wr1, and Dic.

`Buf` is an encoder category for an exact cold load funded by saved quality
allowance or a boot-preload credit. It is not a physical buffer.

## Palette table

All segment palettes are shipped once in BOOT_STAGE and copied to Main RAM.
Timed controls carry only `pal = segment + 1`; zero means no switch. A palette
switch therefore consumes reserved control/name-table work but no same-frame
CRAM payload.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| `PALTAB_MAX_SEG` | 64 | cfg / ip | Palette-segment capacity. |
| PALTAB size | 8 KiB | ip | Main RAM `0xFFB000..0xFFD000`. |
| `PALTAB_STAGE_KB` | 24 KiB / 12 sectors | cfg / pack | BOOT_STAGE size. |
| stage / palette offset | `+0xA000` / `+0xB000` | sp / ip | Word-RAM boot image and palette-table start. |
| P0/index1 | darkest usable RGB333 colour | sim / pack / ip | Opaque DEBUG HUD background. |
| P0/index15 | brightest usable RGB333 colour | sim / pack / ip | DEBUG HUD text. |

The encoder reorders only existing colours before quantisation. It does not
change the 60-colour multiset, and transparent index 0 remains zero in all four
palette lines.

## Cold cap

Cold means a 32-byte pattern written to VRAM in the current timed frame,
regardless of whether its source is Prg, WordBuf, or DicBuf. The shared baseline
is:

```text
baseline cold patterns per frame = max(1, round(5400 / fps))
```

| Content fps | Baseline |
|---:|---:|
| 15 | 360 |
| 24 | 225 |
| 30 | 180 |

Display mode, grid size, and `active_tiles` do not change the baseline.
`[encoder].cold_cap` may raise it after full-length source qualification.
Omission selects the baseline; a lower value is rejected.

The sim and packer share `tools/tile_alloc.py`. The packer replays the frozen
allocation and requires realized cold to remain within the effective cap.
Frame 0 is exempt because HEADER installs it before timed playback.

## Audio

TTRC v16 uses checkpointed 22.05 kHz mono IMA ADPCM only. Sub decodes each
chunk to RF5C164 sign-magnitude samples and writes them to the wave-RAM ring.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| decoded `AUDIO_BYTES` | normally 1472 / 920 / 736 at 15 / 24 / 30 fps | cfg / pack / sp | Even decoded samples per effective playback frame. |
| control audio size | `4 + AUDIO_BYTES / 2` | pack / sp | Predictor, step index, reserved byte, and packed IMA codes. |
| `audio_fd` | header offset 58 | cfg / pack / sp | RF5C164 frequency delta derived from chunk size and playback cadence. |
| ADPCM table | 8,800 B, five sectors | pack / sp | Full lookup image copied to `+0x12800` in both physical Word-RAM banks. |
| PCM work buffer | 1,536 B per bank | sp | Reconstructed chunk at `+0x14C00`. |
| `SYNC_LEAD` | `0x3000`, 12,288 B | sp | Initial write-ahead lead. |
| startup prefetch request | 30 frames | cfg / pack / sp | Decoded PCM prefix, clamped by wave-RAM capacity and chunk size. |
| `SYNC_MIN` | `0` | sp | Lower accepted lead. |
| `SYNC_MAX` | `0x6800`, 26,624 B | sp | Upper accepted lead; crossing it triggers re-sync. |
| `WAVE_RING_END` | `0x8000`, 32 KiB | sp | Wave-RAM ring size. |

At 20 fps or below, long ADPCM decode loops poll the CDC after at most 512
packed bytes. The 24–30 fps specialized path omits that counter and call.

## CD pump

Startup reads HEADER through PREBUFFER, expands and displays frame 0, then
starts one continuous BODY read at frame 1. BODY delivers 75 sectors per
second, so Sub drains ready sectors throughout frame expansion and idle time.

Back-pressure depends on the next sector's destination:

- control checks APPLY space;
- payload checks PrgBuf space;
- pad checks neither.

| Name | Value | Where | Meaning |
|---|---:|---|---|
| low-rate pump interval | every 64 entries or four run descriptors | sp | CDC service during expansion at 20 fps or below. |
| high-rate pump interval | one end poll for a non-empty descriptor frame | sp | Specialized 24–30 fps path. |
| `CMD_SWAP` priority | handshake before opportunistic pump | sp | A pending display handoff takes priority over future-data work. |
| payload full threshold | 424 KiB | sp | Blocks only payload draining. |
| APPLY full threshold | 30 KiB | sp | Blocks only control draining. |
| `FRAME_SECTORS` | 5 useful sectors | pack / sp | Maximum control + payload represented by one routing byte. |
| `HEADER_SECTORS` | 1 metadata sector | pack / sp | Fixed header sector before BOOT_STAGE and other boot regions. |
| Word-RAM swap completion | DMNA bit 1 | sp | Hardware busy flag is polled until the 1M bank switch completes. |

`FEATURE_FIXED_N` makes header `vsync_n` authoritative. Main displays every N
VBlanks and Sub uses the matching reduced `1001*N/800` sector accumulator:

- N=2: 199 two-sector and 201 three-sector slots per 400 frames;
- N=4: 199 five-sector and one six-sector slot per 200 frames.

The N=4 sixth sector is physical pad only because the routing byte still caps
useful data at five sectors. Rates without fixed-N use the delivery-paced
`75 / fps_int` accumulator.

`FEATURE_COLD_RUNS` appends four-byte source-aware run descriptors to each
control. Multi-source blocks and eligible high-rate blocks use these descriptors
directly. Allocator slots are physical VRAM slots; pattern loads are emitted in
ascending slot order while name updates remain in cell order.

## Main-CPU transfer budget

| Name | Value | Where | Meaning |
|---|---:|---|---|
| `VB_WORDS_H40` | 3,400 words/VBlank | ip | H40 VBlank transfer budget. |
| `VB_WORDS_H32` | 2,800 words/VBlank | ip | H32 VBlank transfer budget. |
| `MAIN_CODEGEN_BASE..LIMIT` | 17.5 KiB, `0xFF2000..0xFF65FF` | ip | Generated Main-CPU handlers and blitters. |
| `RUN_TABLE` | 488 records | ip / pack | Maximum source-aware physical cold runs in one frame. |
| run record size | 22 bytes | ip | Pre-swizzled VDP length/source words, command, and fallback fields. |

A one- or two-tile run uses direct CPU writes. Longer runs use Word-RAM DMA,
split at VBlank boundaries when needed, with the required first-word repair.
Prg/WordBuf/DicBuf source boundaries split runs. The 488-record limit is a
fragmentation limit, not the cold-tile cap.

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

The prefix ledger uses the normal 382/397/402 KiB PrgBuf capacity. Scheduled
delivery may use up to 422 KiB, with the difference serving as the automatic
jitter interval. Every BODY prefix must fit the five-useful-sector route
accumulated to that point. Sim freezes this proof and packer requires exact
schedule equality.

`buffer_remaining.npz` schema 6 stores:

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
| timed `raw_prefetch` | off | Optional `[encoder]` setting. |

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
reusable DicBuf entries, assigns finite WordBuf credits under frame-parity
constraints, and computes backwards reserve curves. Optional Raw/Buf upgrades
use complete-exact demand; normal exact work protects Miss-risk demand.

The final reserve is zero, so a light suffix releases saved allowance
naturally. Demand beyond the complete capacity is handled by the normal
priority, approximation, carry, and Miss rules. The physical Prg schedule is
constructed in `tools/physical_budget.py` and materialized by
`tools/stream_schedule.py`.

## Per-source TOML profiles

Use one `schema_version = 3` file per source/mode combination.

```sh
tools/python.sh tools/sim.py configs/<profile>.toml
tools/python.sh tools/render_analysis.py configs/<profile>.toml
make disc CONFIG=configs/<profile>.toml DEBUG=1
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
| `[output]` | `directory`, optional `reuse`, `emit_decisions` | Sim work directory, decoded-input reuse, and decision-log output. |
| `[encoder]` | optional `raw_prefetch`, optional `cold_cap` | Timed raw prefetch and qualified cold-cap raise. |
| `[palette]` | `algorithm` | Palette selector. |
| `[analysis]` | optional `source_canvas = [width, height]` | Analysis-only source-panel canvas. |

`fit = "pad"` preserves all source pixels and adds bars. `fit = "crop"` fills
the output raster while preserving displayed aspect and may discard outer
source pixels. `resize_filter` defaults to `lanczos`; `master_denoise` defaults
to true. H32 pixel aspect is 8:7 and H40 is 32:35.

`active_tiles` is the number of tiles ever non-black after conversion. Omission
uses the full grid. A smaller value is verified against every master frame.
It affects accounting, not the cold-cap baseline.

The loader rejects unknown keys, unsupported modes, non-tile-aligned
dimensions, unsafe profile names, and a `cold_cap` below baseline. GPU, the
1,535-tile resident pool, dither, segmented palettes, Near, boot prefetch, and
the four physical supplies are fixed behavior.

## Build switches

| Name | Default | Meaning |
|---|---:|---|
| `MAIN_CODEGEN` | 1 | Generate specialized bitmap handlers and name-table blitters. Zero selects the reference bit loop. |
| `DMA_RUN_FASTPATH` | 1 | CPU-copy one/two-tile runs and DMA longer runs. Zero selects all-DMA diagnosis. |
| `PLAYER_SPECIALIZE` | 1 | Bake generated header/profile constants into both player objects. Zero selects runtime header reads. |
| `DEBUG` | 1 in recording tools | Display the values-only HUD. Set release explicitly when required. |

Specialized builds compare the CRC-32 header signature before playback. The
Sub linker enforces a 4,096-byte boot-code limit. Startup shows four hexadecimal
digits containing safe PrgBuf preload KiB; a failure shows `BADx`.

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
| N | below the 488-record run-table capacity |
| J | at most 45 / 30 / 25 KiB above normal PrgBuf at 15 / 24 / 30 fps |

Frame 0 is excluded from HUD values and scale maxima because it is boot work,
not timed playback.

<a id="jp"></a>

# 調整可能な設定、throttle、buffer

Tile Texture Reuse Codec pipelineの数値設定リファレンスです。

```text
tools/sim.py -> tools/pack_stream.py -> boot/movieplay_*.s
```

共通default、hardware limit、sourceごとのTOML schemaを扱います。純粋なregister
addressと固定memory mapの詳細はsource codeと [`MOVIE.md`](MOVIE.md) に置きます。
movie固有の設定は [`configs/`](configs/) 以下のversion管理されたfileに置きます。

streaming geometryの正本は [`tools/av_config.py`](tools/av_config.py) だけです。
buildがplayer assembly constantとの一致を確認します。導出値を別の場所で再定義しては
いけません。

「場所」列の短縮名は次の通りです。

- **cfg**: `tools/av_config.py`
- **sim**: `tools/sim.py`
- **pack**: `tools/pack_stream.py`
- **sp**: `boot/movieplay_sp.s`、Sub CPU
- **ip**: `boot/movieplay_ip.s`、Main CPU

## Pattern供給とquality budget

playerには4つの物理pattern供給があります。encoderにはmovie全体のquality budgetも
ありますが、これはplayer memoryではなく支出許可です。

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| `RING_SIZE` / `RING_SIZE_KB` | 428 KiB (`0x6B000`) | sp / cfg | `0x0C000` から `APPLY_BASE` までのPrgBuf物理PRG-RAM ring。 |
| `RING_PHYSICAL_GUARD_KB` | 4 KiB | cfg | pump back-pressureと物理ring末尾の間隔。 |
| `BACKPRESSURE_KB` | 424 KiB | cfg / sp | このoccupancyでpayload drainを止める。 |
| `RING_DELIVERY_GUARD_KB` | 2 KiB | cfg | back-pressureより1 sector手前を空ける。 |
| `physical_delivery_cap_kb(fps)` | 422 KiB | cfg / sim / pack | schedule上のhard occupancy上限。 |
| `ring_jitter_headroom_kb(fps)` | 15 / 24 / 30 fpsで40 / 25 / 20 KiB | cfg | `ceil(20 * 30 / fps)` のdelivery-jitter reserve。 |
| `prg_buf_cap_kb(fps)` | 15 / 24 / 30 fpsで382 / 397 / 402 KiB | cfg / sim / pack / sp | 通常PrgBufとPREBUFFER上限。422 KiBからjitter reserveを引く。 |
| `quality_budget_kb(fps)` | `prg_buf_cap_kb` と同じ | cfg / sim | offlineのmovie全体quality accounting容量。物理meterはない。 |
| `WordBuf0` | 880 patterns、27.5 KiB | sp / ip / sim / pack | 物理bank 0のboot preload sequence。偶数timed frame用。 |
| `WordBuf1` | 880 patterns、27.5 KiB | sp / ip / sim / pack | 物理bank 1の異なるboot preload sequence。奇数timed frame用。 |
| `DicBuf` | 256 patterns、8 KiB | ip / sim / pack | 8-bit indexで再利用するpersistent Main-RAM dictionary。 |
| routing table | 各Word-RAM bankに16 KiB | sp / pack | frame当たり1 byte、最大16,384 frame。 |
| `APPLY_SIZE` | 34 KiB (`0x8800`) | sp | control blockのcircular queue。 |
| frame-0 pattern stage | 36 KiB | sp | boot専用PRG領域 `0x71000..0x7A000`。 |
| boot VRAM sidecar stage | 24 KiB | cfg / pack / sp / ip | bank `+0xA000..+0x10000` のWord-RAM boot image。BODY開始前に未参照resident VRAMを埋められる。 |

`PrgBuf` が公開名で、`RING_*` はcircular実装を示します。`WordBuf0` と
`WordBuf1` は異なるsequenceで、duplicate cacheではありません。`DicBuf` entryは
再利用できます。解析上の短縮名はPrg、Wr0、Wr1、Dicです。

`Buf` は保存済みquality allowanceまたはboot-preload creditで正確なcold loadを
賄うencoder categoryです。物理bufferではありません。

## Palette table

全segment paletteをBOOT_STAGEで1回だけ送り、Main RAMへcopyします。timed controlは
`pal = segment + 1` だけを持ち、zeroは切り替えなしです。palette switchは予約済みの
control/name-table workを消費しますが、同frameのCRAM payloadは不要です。

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| `PALTAB_MAX_SEG` | 64 | cfg / ip | palette segment上限。 |
| PALTAB size | 8 KiB | ip | Main RAM `0xFFB000..0xFFD000`。 |
| `PALTAB_STAGE_KB` | 24 KiB / 12 sectors | cfg / pack | BOOT_STAGE size。 |
| stage / palette offset | `+0xA000` / `+0xB000` | sp / ip | Word-RAM boot imageとpalette tableの開始。 |
| P0/index1 | 使用可能な最暗RGB333色 | sim / pack / ip | 不透明DEBUG HUD background。 |
| P0/index15 | 使用可能な最明RGB333色 | sim / pack / ip | DEBUG HUD text。 |

encoderは量子化前に既存色の順序だけを変えます。60色の集合は変えず、4本すべての
palette lineでtransparent index 0をzeroのままにします。

## Cold cap

Coldは、sourceがPrg、WordBuf、DicBufのどれでも、現在のtimed frameでVRAMへ書く
32-byte patternです。共通baselineは次の通りです。

```text
baseline cold patterns per frame = max(1, round(5400 / fps))
```

| Content fps | Baseline |
|---:|---:|
| 15 | 360 |
| 24 | 225 |
| 30 | 180 |

display mode、grid size、`active_tiles` はbaselineを変えません。
`[encoder].cold_cap` はsource固有の全編認定後にbaselineを引き上げられます。省略時は
baselineを使い、baseline未満は拒否します。

simとpackerは `tools/tile_alloc.py` を共有します。packerは固定済みallocationを再生し、
realized coldがeffective cap内にあることを要求します。frame 0はtimed playback前に
HEADERが構築するため対象外です。

## Audio

TTRC v16のaudioはcheckpointed 22.05 kHz mono IMA ADPCMだけです。Subが各chunkを
RF5C164 sign-magnitude sampleへdecodeし、wave-RAM ringへ書きます。

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| decoded `AUDIO_BYTES` | 15 / 24 / 30 fpsで通常1472 / 920 / 736 | cfg / pack / sp | 実効playback frameごとの偶数decoded sample数。 |
| control audio size | `4 + AUDIO_BYTES / 2` | pack / sp | predictor、step index、reserved byte、packed IMA code。 |
| `audio_fd` | header offset 58 | cfg / pack / sp | chunk sizeとplayback cadenceから導出するRF5C164 frequency delta。 |
| ADPCM table | 8,800 B、5 sectors | pack / sp | 両物理Word-RAM bankの `+0x12800` へcopyする全lookup image。 |
| PCM work buffer | bank当たり1,536 B | sp | `+0x14C00` の再構築chunk。 |
| `SYNC_LEAD` | `0x3000`、12,288 B | sp | 初期write-ahead lead。 |
| startup prefetch request | 30 frames | cfg / pack / sp | wave-RAM容量とchunk sizeでclampするdecoded PCM prefix。 |
| `SYNC_MIN` | `0` | sp | 許容lead下限。 |
| `SYNC_MAX` | `0x6800`、26,624 B | sp | 許容lead上限。超えるとre-sync。 |
| `WAVE_RING_END` | `0x8000`、32 KiB | sp | wave-RAM ring size。 |

20 fps以下では長いADPCM decode loopが最大512 packed byteごとにCDCをpollします。
24〜30 fpsのspecialized pathはこのcounterとcallを省きます。

## CD pump

startupはHEADERからPREBUFFERまでを読み、frame 0を展開・表示してから、frame 1を
起点に1回の連続BODY readを始めます。BODYは毎秒75 sectorを届けるため、Subはframe
展開中とidle中の両方でready sectorをdrainします。

back-pressureは次sectorの行き先で決まります。

- controlはAPPLY空きを確認する
- payloadはPrgBuf空きを確認する
- padはどちらも確認しない

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| low-rate pump interval | 64 entriesまたは4 run descriptorsごと | sp | 20 fps以下の展開中CDC service。 |
| high-rate pump interval | non-empty descriptor frame末尾に1回 | sp | specialized 24〜30 fps path。 |
| `CMD_SWAP` priority | opportunistic pumpよりhandshake優先 | sp | pending display handoffを将来data workより先に処理する。 |
| payload full threshold | 424 KiB | sp | payload drainだけを止める。 |
| APPLY full threshold | 30 KiB | sp | control drainだけを止める。 |
| `FRAME_SECTORS` | 有効5 sectors | pack / sp | 1 routing byteが表すcontrol + payload上限。 |
| `HEADER_SECTORS` | metadata 1 sector | pack / sp | BOOT_STAGEなどのboot領域より前にある固定header sector。 |
| Word-RAM swap completion | DMNA bit 1 | sp | 1M bank switch完了までhardware busy flagをpollする。 |

`FEATURE_FIXED_N` はheaderの `vsync_n` を正式なcadenceにします。MainはN VBlankごとに
表示し、Subは対応する `1001*N/800` の約分sector accumulatorを使います。

- N=2: 400 frame当たり2-sector slotが199個、3-sector slotが201個
- N=4: 200 frame当たり5-sector slotが199個、6-sector slotが1個

N=4の6個目はphysical padだけです。routing byteの有効data上限は5 sectorのままです。
fixed-Nでないrateはdelivery-paced `75 / fps_int` accumulatorを使います。

`FEATURE_COLD_RUNS` は各controlへ4-byte source-aware run descriptorを追加します。
multi-source blockと対象high-rate blockはdescriptorを直接使います。allocator slotは
物理VRAM slotで、pattern loadはslot昇順、name updateはcell順です。

## Main-CPU transfer budget

| Name | 値 | 場所 | 意味 |
|---|---:|---|---|
| `VB_WORDS_H40` | 3,400 words/VBlank | ip | H40 VBlank transfer budget。 |
| `VB_WORDS_H32` | 2,800 words/VBlank | ip | H32 VBlank transfer budget。 |
| `MAIN_CODEGEN_BASE..LIMIT` | 17.5 KiB、`0xFF2000..0xFF65FF` | ip | 生成するMain-CPU handlerとblitter。 |
| `RUN_TABLE` | 488 records | ip / pack | 1 frameのsource-aware physical cold run上限。 |
| run record size | 22 bytes | ip | 事前変換済みVDP length/source word、command、fallback field。 |

1〜2 tileのrunはCPUで直接copyします。長いrunはWord-RAM DMAを使い、必要ならVBlank
境界で分割し、必須のfirst-word repairを行います。Prg/WordBuf/DicBufのsource境界は
runを分けます。488-record上限はfragmentation上限であり、cold tile capではありません。

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

prefix ledgerは通常PrgBuf容量382/397/402 KiBを使います。scheduled deliveryは最大
422 KiBまで使え、その差が自動jitter intervalです。各BODY prefixはその時点までに
累積した有効5-sector routeへ収まらなければなりません。simがproofを固定し、packerが
scheduleの完全一致を要求します。

`buffer_remaining.npz` schema 6は次を保存します。

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
| timed `raw_prefetch` | off | optional `[encoder]` setting。 |

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
frame parity制約の下で有限WordBuf creditを割り当て、後ろ向きreserve curveを計算します。
optional Raw/Buf upgradeはcomplete-exact demand、通常exact workはMiss-risk demandを
保護します。

最終reserveはzeroなので、軽い末尾では保存済みallowanceが自然に解放されます。全容量を
超えるdemandは通常のpriority、approximation、carry、Miss ruleで処理します。物理Prg
scheduleは `tools/physical_budget.py` が構築し、`tools/stream_schedule.py` が
具体化します。

## SourceごとのTOML profile

source/modeの組み合わせごとに `schema_version = 3` のfileを1つ使います。

```sh
tools/python.sh tools/sim.py configs/<profile>.toml
tools/python.sh tools/render_analysis.py configs/<profile>.toml
make disc CONFIG=configs/<profile>.toml DEBUG=1
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
| `[output]` | `directory`, optional `reuse`, `emit_decisions` | sim work directory、decoded-input reuse、decision-log output。 |
| `[encoder]` | optional `raw_prefetch`, optional `cold_cap` | timed raw prefetchと認定済みcold-cap引き上げ。 |
| `[palette]` | `algorithm` | palette selector。 |
| `[analysis]` | optional `source_canvas = [width, height]` | 解析専用Source panel canvas。 |

`fit = "pad"` は全source pixelを保持し、barを追加します。`fit = "crop"` は表示aspectを
保ってoutput rasterを埋めるため、source外周を捨てる場合があります。
`resize_filter` defaultは `lanczos`、`master_denoise` defaultはtrueです。H32 pixel
aspectは8:7、H40は32:35です。

`active_tiles` は変換後に一度でもnon-blackになるtile数です。省略時はfull gridを使い、
小さい値は全master frameに対して検証します。accountingには影響しますがcold-cap
baselineには影響しません。

loaderは未知key、未対応mode、tile境界に揃わないdimension、安全でないprofile名、
baseline未満の `cold_cap` を拒否します。GPU、1,535-tile resident pool、dither、
segmented palette、Near、boot prefetch、4つの物理供給は固定behaviorです。

## Build switch

| Name | Default | 意味 |
|---|---:|---|
| `MAIN_CODEGEN` | 1 | specialized bitmap handlerとname-table blitterを生成する。zeroはreference bit loop。 |
| `DMA_RUN_FASTPATH` | 1 | 1〜2 tile runをCPU、長いrunをDMAで転送する。zeroは診断用all-DMA。 |
| `PLAYER_SPECIALIZE` | 1 | 生成済みheader/profile constantを両player objectへ埋め込む。zeroはruntime header read。 |
| `DEBUG` | recording toolでは1 | values-only HUDを表示する。必要なときだけreleaseを明示する。 |

specialized buildはplayback前にCRC-32 header signatureを比較します。Sub linkerは
4,096-byte boot-code上限を強制します。startupは安全に受信済みのPrgBuf preload KiBを
4桁hexで表示し、failureは `BADx` を表示します。

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
| N | 488-record run-table容量未満 |
| J | 通常PrgBuf超過が15 / 24 / 30 fpsで45 / 30 / 25 KiB以下 |

frame 0はboot workでtimed playbackではないため、HUD valueとscale maximumから除外します。
