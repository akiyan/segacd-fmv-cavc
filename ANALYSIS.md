EN / [JP](#jp)

# Analysis Overlay Reference

This document defines, exactly and completely, every element drawn in the
1920x1080 analysis frame produced by `tools/render_analysis.py` for the
**Sega CD Constraint-Aware Video Codec**. The layout "source of truth" is
`tools/layout_preview.py` (dummy data); `render_analysis` runs the same drawing
functions on real encoder output.
`tools/render_analysis.py` replays `decisions.pkl` and materializes the
decoded-preview and per-cell category PNGs on demand. `tools/sim.py` stores the
compact decisions and per-cell category masks but does not generate those PNGs.
The masks can overlap when allocator order places a physical cold-load
attribution on a cell that also has a Near or Flbk quality result.

Every render also writes a machine-readable, one-row-per-frame TSV under
`logs/`. Its unique filename contains local date/time, profile name, a
10-character profile checksum, encoder version, player version, and the
`timeline` kind. It is generated from the same `frame_data()` values used by
the overlay, before PNG rendering begins, so numeric comparisons do not require
OCR. A frame-range render still writes the complete TSV.
`videos/<stem>_analysis.tsv` is a compatibility symlink to the newest matching
log; `ANALYSIS_TSV` changes that symlink path, not the persistent log location.

Keep this file in sync whenever the layout changes (the `/analysis` skill
automates: update layout -> update this file -> notify).

## Analysis TSV sidecar

The TSV starts with one header row and then contains every encoded frame in
ascending order. Integer display fields are written exactly as the overlay
uses them. In particular, frame 0 keeps its `legend_raw` and `legend_same`
classification, while the untimed `status_cold`, `status_pre`,
`status_band_kib_s`, `status_dma`, and `status_run` fields are zero. The
corresponding encoder values remain available in the `stat_*` columns.

| Columns | Definition |
|---|---|
| `schema_version` | TSV schema version, currently `6`. |
| `frame`, `frame_hex`, `time_seconds`, `palette_segment` | Decimal frame, HUD-style hexadecimal frame, exact playback time, and CRAM palette-segment index. |
| `cells`, `active_tiles`, `budget_tiles`, `cold_cap_tiles`, `prefetch_cap_tiles` | Raster and limits repeated on every row for self-contained filtering. `cold_cap_tiles` is the fixed effective profile/base cap over every physical cold source. Physical delivery failure stops sim and does not create a local per-frame cap. |
| `legend_raw`, `legend_same`, `legend_dic`, `legend_prg`, `legend_wr`, `legend_wr0`, `legend_wr1`, `legend_near`, `legend_flbk`, `legend_miss` | Per-frame category counts. `legend_wr` is the displayed Wr0+Wr1 total; the two source banks are also kept separately. |
| `status_req`, `status_miss`, `status_cold`, `status_pre`, `status_band_kib_s`, `status_prg`, `status_wr0`, `status_wr1`, `status_dma`, `status_run` | Numeric values printed in the bottom status bar, including the frame-0 untimed display rule. |
| `body_payload_bytes`, `body_control_bytes`, `body_pad_bytes`, `body_physical_bytes`, `body_useful_bytes`, `body_band_bps` | Exact physical timed-BODY delivery-slot accounting behind the Band display. Slot 0 is zero because frame 0 comes from the untimed BODY arm. |
| `quality_budget_remaining_bytes` | Non-borrowed encoder-only whole-movie quality allowance remaining after the frame. A terminal-drain loan displays as zero until future suffix allowance repays it. This is diagnostic state, not a physical meter. |
| `stat_frame` through the remaining `stat_*` columns | Every column from `stats.npz`, preserved with a `stat_` prefix and in its original order. These raw columns may grow when the simulator gains a new statistic. |

The compatibility alias follows `ANALYSIS_OUT`: changing
`videos/example_analysis.mp4` produces a timestamped `logs/*.tsv` and updates
`videos/example_analysis.tsv` unless `ANALYSIS_TSV` selects another alias.

## Layout map

```
+----------------------------------------------+   +-----------------------------+
| SEGA-CD sim output  <meta>      <PL/Time/Fr> |   | Source  <res/fps/audio>     |
| +------------------------------------------+ |   | +-------------------------+ |
| |                                          | |   | | source frame (4:3)      | |
| |   SEGA-CD OUTPUT (centered on the real   | |   | +-------------------------+ |
| |   screen; letterboxed to the panel)      | |   | LEGEND (2 rows, 9 classes)  |
| |                                          | |   | +-------------------------+ |
| |                                          | |   | | CATEGORY MAP (4:3)      | |
| |                                          | |   | | (tile content + border; | |
| |                                          | |   | |  Miss = red-filled hole)| |
| +------------------------------------------+ |   | +-------------------------+ |
+----------------------------------------------+   | CATEGORY TOTALS (whole clip)|
+----------------------------------------------+   | +-------------------------+ |
| STATUS BAR                                   |   | | AUDIO WAVEFORM          | |
|  [Req][Cold][Pre][Band][Prg][Wr0][Wr1]...      | | | (+/-2s, now = centre)   | |
|  Prev/Current/Next palette strip             |   | +-------------------------+ |
|  3 timelines (Req / three supplies / BODY Band)| +-----------------------------+
+----------------------------------------------+
```

Regions (pixel rectangles in `layout_preview.py`): `MAIN_FRAME` left,
`SRC_FRAME` / `CATLEG_XY` / `CAT_FRAME` / `CATTOT_XY` / `WAVE_FRAME` right
column (top to bottom), and `STATUS_XY` bottom-left. The layout has no
per-metric flow graph or separate palette-totals slot.

## Headings

- **SEGA-CD sim output** (top-left): big label + a small meta line:
  `mode / WxH (cols x rows) / audio / fps / avg N KiB/sec`.
  - `mode` = screen mode (H32 / H40 / mode4). `WxH` = encoded tile grid in
    pixels; `cols x rows` = tile grid (each tile 8x8).
  - `avg N KiB/sec` = average of useful BODY delivery Band over the whole clip
    (see Band below).
- **PL/Time/Frame** (top-right, small): `PL:cur/total Time:MM:SS.ss Frame:XXXX`.
  `PL` = current palette-segment index / highest index (zero-padded to the
  total's digit count, min 2). `Time`, `Frame` = playback position; `Frame` is
  **4-digit hex** (`%04X`), matching the on-hardware debug HUD's F number.
- **Source** (top of right column): big label + a small spec line with the
  *source video* `resolution / fps / audio codec+rate+channels`
  (from `ffprobe`; bitrate intentionally omitted).

## Main panel (left)

The reconstructed SEGA-CD output. It is centered on the *real hardware screen*
(e.g. 256x224 for H32) and letterboxed into the panel at the mode's display
aspect (4:3 for H32/H40, ~14:9 for mode4) - it is **not** stretched to fill.
Low-resolution grids therefore appear at their true on-screen size.

## Right column

- **Source** (top): the source frame after crop, scaled into the panel (4:3
  panel, same footprint as the category map). Its displayed width respects
  `source.sar`. A profile may set `analysis.source_canvas = [width, height]`
  when the raw raster is an intentionally centered sub-aperture; the renderer
  keeps that raster centered at coded size inside a black canvas before fitting
  the complete canvas into the panel.
- **Legend** (between Source and the category map): five entries on the first
  row and three on the second, ordered `Raw Same Near Flbk Miss` then
  `Prg Wrd Dic`. The displayed `Wrd` count combines `Wr0 + Wr1`.
  Numeric fields are text directly on the legend background; there is no level
  fill behind the digits. All zero-padded digits use the normal text colour.
  Swatch styles mirror the map except that borderless `Same` uses the original
  light/dark checker swatch in the legend. `Raw` = black/white dashed frame,
  `Miss` = red fill, and `Near/Flbk` = thin frame. `Dic/Prg/Wrd` use thin
  borders alternating between their category colour and black.
- **Category map** (middle): the tile grid. Each 8x8 tile shows its
  **reconstructed content**; the category (see Tile Categories) is indicated by
  the border: `Raw` = thin black/white dashed frame, `Same` = no border,
  `Near/Flbk` = thin 1px border, and
  `Dic/Prg/Wr0/Wr1` = thin colour-and-black dashed border. Wr0 and Wr1
  share the Wr1 cyan display colour. A `Miss` tile is
  drawn as a **red-filled hole** (its content is not updated this frame).
- **Category totals** (directly below the category map, `CATTOT_XY`): a thin
  stacked horizontal bar of the whole-clip totals per category, with a compact
  swatch+count legend above it (totals only, no unique counts). Static for the
  whole clip.
- **Audio waveform** (bottom, `WAVE_FRAME`): scrolling envelope of the sim's
  playback-model audio (the WAV muxed into the video). For ADPCM22 this is not
  the clean extracted source: it is the exact continuous checkpointed IMA
  encode/decode result after conversion to the RF5C164's 8-bit sign-magnitude
  samples. The original signed-16 WAV remains separate as the packer input.
  Window is +/-2 seconds with
  **now = centre** (white line), scrolling left; the past (left half) is drawn
  bright green, the future (right half) dim green, around a zero-amplitude
  centre line. Heading (outside the frame): `Audio` + the audio spec.
- There is no separate per-metric flow-graph panel.

## Tile Categories (READ THIS CAREFULLY)

The accounting counts place each 8x8 tile in one displayed class describing
**how the tile was filled**, from accurate reuse or a fresh load to a Miss.
The per-cell styling masks can overlap when allocator order attributes a
physical cold load to a cell that also has a Near or Flbk quality result. This
preserves both facts on the category map without changing the accounting
totals. The encoder searches VRAM-resident patterns and picks the best match
under the current byte budget.

### The F3 similarity metric

When comparing a target tile to a candidate resident pattern (both RGB333,
channels 0..7), three per-pixel differences are computed over the 64 pixels:

- **Ym** = mean of `|luma(target) - luma(candidate)|` (average luminance error).
- **Yp** = max  of that same per-pixel luminance error (worst-pixel error;
  this is what catches thin edges / shape changes).
- **C**  = mean of the chroma distance
  `sqrt((Cb_t - Cb_c)^2 + (Cr_t - Cr_c)^2)` (average colour error).

Luma = `0.299R + 0.587G + 0.114B`; `Cb = -0.169R - 0.331G + 0.5B`;
`Cr = 0.5R - 0.419G - 0.081B`. A candidate is accepted into a tier only if it
passes **all three** thresholds (`Ym<=`, `Yp<=`, `C<=`) for that tier. Tiers are
tested tightest-first, so a tile is labelled by the *tightest* tier it fits.

### Tier thresholds (defaults, env-overridable)

| Tier | Ym | Yp | C  | env |
|------|----|----|----|-----|
| Near | 10 | 28 | 24 | `CBRSIM_NEAR_YM/YP/C` |
| Flbk |120 |252 |200 | `CBRSIM_TFLBK_YM/YP/C` |

Smaller thresholds = stricter = better visual match. `Near` is a near-perfect
reuse. A candidate outside Near is not accepted immediately: the encoder first
tries an exact cold load. `Flbk` is considered only when that exact load cannot
fit. Its default improve-only mode accepts the best resident only when it is
closer to the target than the current display. The wide Flbk bounds above are
used by the optional absolute-threshold mode.

### The nine classes

| Class | Colour | Bytes | Meaning |
|-------|--------|-------|---------|
| **Raw**  | black/white dashed border | 34 | An exact pattern delivered for this frame, loaded into VRAM before display, and used immediately. Timed frames are bounded by the per-frame cold cap; frame 0 is boot-loaded from the untimed BODY arm and is exempt. |
| **Same** | light/dark checker in legend; no map border | 0 or 2 (name only) | The target tile's exact pattern is **already resident** in VRAM. This includes a pattern prefetched in an earlier frame and first displayed now. No pattern transfer occurs this frame. |
| **Near** | grey thin border | 2 (name) | No exact match, but a resident pattern passes the **Near** thresholds; the cell points to it. Near-perfect reuse. Also covers "keep the current display" when the currently shown tile is already accurate and still within Near of the new target. |
| **Flbk** | yellow thin border | 2 (name) | **Fallback** (merged Mid+Far). Used when an exact load is unavailable. It remains distinct from the solid-red Miss because it did improve the displayed tile. |
| **Miss** | red (filled) | 0 | The tile was **not updated**; it still shows whatever was there before. A red-filled hole in the category map. |
| **Prg** | violet/black thin dashed border | 34 | An exact cold load funded from saved whole-movie allowance and physically supplied by streamed PrgBuf. |
| **Wr0** | cyan/black thin dashed border | 2 (name) | An exact cold load using a boot-preloaded WordBuf0 pattern. Its legend count is combined into `Wrd`. |
| **Wr1** | cyan/black thin dashed border | 2 (name) | An exact cold load using a boot-preloaded WordBuf1 pattern. Its legend count is combined into `Wrd`. |
| **Dic** | amber/black thin dashed border | 2 (name) | An exact cold load using an entry from persistent DicBuf. |

### Selection order (per changed tile, `commit_unified`)

Frame 0 is a deliberate exception to this list. It has no timed BODY or cold
budget, so every cell is installed as its exact target. The first cell using an
exact pattern is `Raw`; further cells using the same pattern are `Same`.
`Near`, `Flbk`, `Prg`, `Wr0`, `Wr1`, `Dic`, and `Miss` must all be zero
in frame 0's displayed category totals. After those exact display patterns are
placed, unused startup pattern capacity may install future exact patterns into
otherwise-free VRAM slots; these have no displayed-cell category in frame 0.

Selection is one automatic three-phase pass:

1. Commit every free or two-byte choice first. If the **currently displayed**
   tile was exact and remains within `Near`, keep it for 0 bytes. Otherwise use
   an exact resident as `Same`, or the best almost-identical resident as `Near`.
2. Collect the remaining cells in priority order. Try exact cold loads while
   reserving one 2-byte name entry for every cell still deferred. The exact
   source is `Raw`, `Prg`, `Wr0/Wr1`, or `Dic`; the per-frame **cold cap**
   (`cold_cap_for_fps`, `av_config.py`) still applies.
3. Recompute resident candidates after those exact loads. For every cell not
   selected as exact, use a resident that improves the current display as
   `Flbk`; otherwise leave `Miss`. If the target mean-colour bucket has no
   improving result, Flbk also compares the newest eligible resident in each
   of its 26 adjacent mean-colour buckets. The improve-only rule still applies.

The name-entry reservation is internal to this pass, not a setting. It prevents
early exact loads from consuming the whole frame allowance and making the
fallback phase unreachable.

Notes: `Same/Near/Flbk` use a resident 32-byte pattern and require at most
a 2-byte name-table entry. A `Raw` or `Prg` load costs 34 bytes in the
encoder model. A Wr0/Wr1 boot-preloaded load or DicBuf hit already owns its pattern
bytes and therefore costs only the 2-byte name entry during playback. A persistent
approximation (a tile stuck in Near/Flbk for at least 0.2 seconds) is
escalated to Miss severity so it gets an accurate reload when budget allows.
The frame threshold is `floor(0.2 * fps)`, with a minimum of one frame: 6 at
30 fps, 4 at 24 fps, and 3 at 15 fps.

Before the selection cascade, changed tiles are ordered by current visual RGB
error, optional detail weight (off by default), distance-weighted aging, and
the screen-edge discount. Aging pressure accumulates only while the displayed
class is Miss or Flbk; a mean RGB error of 24 adds one pressure unit per
frame, one frame adds at most two, and the multiplier saturates at 7x. Near is
excluded. The TSV `carry` and `age` fields use a separate integer Miss wait
counter and do not affect update or upgrade priority. Approximation upgrades
sort by severity, then aging pressure, then the same base score.

## Status bar (bottom-left)

Left to right: **Req**, **Cold**, **Band**, **DMA**, **Run**, **Prg**,
**Wrd**, and **Pre** meters (each bar is as wide as its own label). Wrd
combines the displayed values of the physically separate Wr0 and Wr1 banks.
Below the meters is the palette strip; to the right are four stacked timelines.
There is no Tank or physical Buf meter.

### Req meter
All categories stacked into one bar (full width = total tile count `C`), with a
yellow vertical **budget line** marking the per-frame update budget. The compact
label is `Req:NNN Miss:NNN`.

### Cold meter
`Cold:NNN` = this frame's **timed new tile loads** (`Raw + Prg + Wr0 + Wr1 + Dic + future raw
prefetch`, i.e. every 32-byte pattern newly written to VRAM from any physical
supply). The bar stacks the corresponding category/source colours and blue
prefetch;
full-scale = `cold_cap_for_fps`
(`av_config.py`: generally `round(5400 / fps)`, with a qualified nominal-30-fps
baseline of 200, unless the profile raises it; display mode and active tile
count do not affect the baseline).
Frame 0 is outside this timing calculation and is displayed as `Cold:000`.
Its Raw/Same category counts remain visible in the legend.
This visualises the value the hardware slip investigations were fought over.

### Pre meter
`Pre:NNN` is the number of future exact patterns written by a timed frame
without being displayed yet. Frame 0's boot preload is deliberately outside
this meter and appears as `Pre:000`; its capacity and realized count remain in
the decision log and report. The meter scale is the runtime per-frame request
cap. If a prefetched pattern is used later, the displayed cell is `Same`, not
`Raw`.

### Band meter (useful BODY delivery) - KiB/sec
`Band` is the non-pad data physically read from `BODY.DAT` in this delivery
slot, divided by that slot's actual CD read time:

`Band = useful BODY bytes / physical BODY bytes * 150 KiB/sec`.

The physical bytes are the slot's whole sectors, including pad. At CD 1x each
sector takes 1/75 second, so a completely useful slot reads `Band:150`, a
half-pad slot reads `Band:075`, and a valid slot never exceeds 150 KiB/sec.

The bar is split left to right into **Raw light grey** for same-frame
Raw-funded pattern payload, **Prg purple** for the remaining quality-budget or
prefetch pattern charge, and **dim blue-grey** for the continuous control
stream (control header, name entries, audio, palette reference, DEBUG data,
and run descriptors). The timeline uses the same stack bottom to top.
Future-frame payload is counted in the slot where it is actually prefetched,
not where the target frame later consumes it.

The physical delivery trace stores exact total payload bytes but not the
Raw/Prg ordering inside one frame. The analysis therefore distributes that
frame's exact Raw count evenly through its exact PrgBuf load count, removes the
HEADER prebuffer prefix, and then maps the remaining attribution onto the exact
physical BODY slots. The input Raw/Prg counts and every slot's total payload
remain exact; the Raw/Prg split across the prebuffer boundary and BODY slots is
a visualization because the discarded sub-frame ordering was not logged.

For on-disc format version 17, the control contribution includes whichever shadow-update
representation was selected for that frame: the bitmap plus name
entries, or the completed offset/entry list. The analysis does not add a
separate meter for this internal representation; its exact byte cost is already
included in the dim control portion of `Band`.

The metric excludes rate-match pad sectors, the zero-filled tail of the final
control/payload sectors, all of `HEADER.DAT`, the complete untimed BODY arm
(frame-0 patterns/control and decoded startup audio), palettes, routing, and
the compatibility `MOVIE.DAT` container. Slot 0 therefore reads `Band:000`.
`avg N KiB/sec` in the top meta and `body_useful_bps` in `report.txt` divide
all useful timed-BODY bytes by the complete timed-BODY read time. This is a
physical-time-weighted average, not a simple mean of the displayed slots.
`codec_work_bps` remains a separate quality-allocation diagnostic.

The bar uses the slot's physical bytes as full-scale. Payload and control fill
their useful fractions; all pad remains blank. A thin yellow line at the right
edge marks CD 1x.

Before making these per-frame choices, the encoder dry-runs the complete
quantized movie through the shared VRAM allocator. When a continuous Main-risk
burst exceeds the complete quality-budget capacity, its unavoidable shortfall
is distributed proportionally from the burst start through its peak instead of
being concentrated in the first frame. A backwards pass over that feasible
risk demand builds the reserve that protects normal updates from future
Flbk/Miss bursts. Optional exact-load upgrades use a separate strict reserve
from complete exact-update demand; their deliberately infeasible all-exact
shortage is not allowed to consume protection for live Main work. Both curves
finish at zero. The Main-risk original demand, balanced planned demand,
unavoidable shortfall, and reserve are saved as separate byte traces in
`buffer_remaining.npz`; none is a physical supply meter.
[`BUEFFERING.md`](BUEFFERING.md) describes how both curves are constructed and
applied.

### Three pattern-supply meters

Each meter is an independent remaining count in 32-byte patterns:

| Meter | Physical object | Behaviour |
|---|---|---|
| `Prg:NNNNN` | usable PRG-RAM `PrgBuf` | End-of-frame occupancy from the exact sector scheduler. It can rise through BODY prefetch and fall through Prg consumption. |
| `Wr0:NNN` | `WordBuf0` in physical Word-RAM bank 0 | Actual boot-loaded total minus patterns consumed by eligible even frames. It only falls. |
| `Wr1:NNN` | `WordBuf1` in physical Word-RAM bank 1 | Actual boot-loaded total minus patterns consumed by eligible odd frames. It only falls. |

The Prg trace includes the `HEADER.DAT` prebuffer, whole-sector payload tails,
per-slot prefetch, and realized Prg consumption. The packer recomputes it from
the built controls and rejects any mismatch. The three preload traces use the
actual loaded totals, so unused fixed capacity is not presented as available
content.

These meters deliberately do not show the offline whole-movie quality budget.
That diagnostic can remain high when physical supplies are low, and it cannot
provide a pattern byte to the player.

### DMA meter
`DMA:NNN` or `DMA:NNNN` = the number of **32-byte pattern tiles** transferred
to VRAM by the timed frame. The numeric field uses the digits required by the
current raster. Frame 0's boot construction is outside this calculation and is
shown as zero. Its full-scale starts from the
mode/fps theoretical VDP byte ceiling, subtracts the fixed full name-table DMA
(`2 * cells` bytes), divides the remainder by 32 bytes/tile, and clamps it to
the raster's tile count. Green fill; if the transfer exceeds that ceiling it
turns orange with a red overflow tail.

### Pattern transfer run meter
`Run:NNNN` = the number of ascending consecutive cold VRAM-slot runs used for
the pattern tiles, exactly matching the packer's cold-run descriptors, the
Main CPU run-table record count, and H40 DEBUG HUD `N` (before its low-byte
display truncation). Reuse entries do not break a run; a slot discontinuity
does, including a wrap from the end of the slot pool to slot zero.
Frame 0 is outside the timed run calculation and is shown as `Run:0000`, even
though its internal boot-transfer trace remains available for packer checks.
Cold payload order follows the allocator's physical slot numbers and is
independent of cell/name-update order. Prg/Wr/Dic source boundaries split
runs. The encoder reports the exact resulting Run trace and does not perform
a movie-wide slot-number optimization.

This is deliberately **not the number of VDP DMA commands**. In the player,
a one- or two-tile run is copied directly by the CPU, while a longer
run uses DMA and may be split into more than one DMA command at a VBlank budget
boundary. Both still remain one `Run` record. The bar therefore measures the
fragmentation seen by the player independent of the current transfer fast
path.

The bar's per-frame full-scale is the current `DMA` tile count: the theoretical
worst case is every transferred tile isolated into its own one-tile run. A tiny
bar therefore means long, efficient runs; a full amber bar means the maximally
fragmented case. The numeric field is fixed at four digits, derived from full
H40's theoretical worst case of 1120 pattern tiles and therefore 1120 runs.

### Palette strip
`Prev` / `Current` / `Next` palette sets (each 4 palettes x 15 colours, drawn
as square tiles in 2 rows of 30 = 2 palettes per row; the `Current` set gets a
border). Heading per set: `Prev PL:NNN Frame:NNNNN` etc. At a segment edge
(no previous or no next palette segment) that slot is **blank** (`Prev -`).

### Four stacked timelines (right of the meters, full remaining width)
Req occupies half the height, Supply one quarter, and Run/Band split the final
quarter. All rows share the whole clip on the x-axis with a white playhead:
1. **Req heatmap** - `Raw / Prg / Wr0 / Wr1 / Dic / Near / Flbk / Miss`
   stacked per frame. `Same` is omitted so the changing load remains visible.
2. **Pattern supply** - `Prg / Wrd` remaining counts stacked per frame.
   Wrd combines the separate Wr0 and Wr1 traces before pixel scaling, so a
   positive combined balance remains visible down to one pixel. The scale is
   the sum of the Prg, Wr0, and Wr1 capacities. The persistent DicBuf has no
   remaining count and is therefore omitted.
3. **Run** - physical source-aware cold-run count scaled to the timed maximum
   actually present in this TSV. Frame 0 does not set the scale.
4. **Band** - useful Raw payload (light grey), Prg charge (purple), and control
   (blue-grey) as a fraction of the physical bytes in each delivery slot. Pad
   remains blank and the row top marks CD 1x (150 KiB/sec).

The detailed whole-movie timeline automatically marks the first frame after
the final Prg payload delivery as the evaluation boundary. Its terminal
no-refill suffix remains visible with red shading but is excluded from
comparison evaluation. This changes reporting only: simulation, packing, and
playback verification still cover the complete movie.

## Colours (RGB)

Raw `(205,205,205)`, Same `(150,150,158)` grey, Near `(128,134,144)` grey,
Flbk `(225,185,25)` yellow, Miss `(220,70,70)` red,
DMA `(70,190,90)` green,
DMA-run `(215,165,65)` amber, Band-control `(95,110,122)` blue-grey.
Physical supply colours: Prg `(165,105,225)`, Wr0 and Wr1 both
`(65,205,195)`, Dic `(220,120,30)`. Dic, Prg, and Wrd alternate these colours
with black on their thin category borders. All analysis renderers take these
semantic colours and border styles from `tools/analysis_style.py`.

---

<a id="jp"></a>

# 解析overlay reference

この文書は、**Sega CD Constraint-Aware Video Codec**用の`tools/render_analysis.py`が生成する
1920x1080解析frameの全要素を定義します。Layoutの正本はdummy dataを使う
`tools/layout_preview.py`で、`render_analysis`も実encoder outputに対して同じ描画関数を
実行します。

`tools/render_analysis.py`は`decisions.pkl`をreplayし、decoded previewとcellごとの
category PNGを必要時に生成します。`tools/sim.py`はcompactなdecisionとcellごとの
category maskを保存しますが、これらのPNGは生成しません。Allocator orderによって、
物理cold-load attributionとNearまたはFlbkの画質結果が同じcellへ置かれる場合、
maskは重複できます。

各renderは、1 frame 1 rowのmachine-readable TSVも`logs/`へ書きます。Filenameには
local date/time、profile名、10文字のprofile checksum、encoder version、player version、
`timeline` kindが入ります。TSVはPNG rendering開始前に、overlayと同じ
`frame_data()`値から生成するため、数値比較にOCRは不要です。
Frame rangeを指定したrenderでも完全なTSVを書きます。
`videos/<stem>_analysis.tsv`は最新の一致logへのcompatibility symlinkです。
`ANALYSIS_TSV`はこのsymlink pathを変えますが、persistent logの場所は変えません。

Layout変更時は、この文書も同時に更新します。`/analysis` skillはlayout更新、本文更新、
通知を一連で行います。

## Analysis TSV sidecar

TSVはheader rowの後に、全encode frameを昇順で格納します。Integer display fieldは
overlayと同じ値です。Frame 0は`legend_raw`と`legend_same`を保持し、timed処理ではない
`status_cold`、`status_pre`、`status_band_kib_s`、`status_dma`、`status_run`は0です。
対応するencoder値は`stat_*` columnに残ります。

| Columns | 定義 |
|---|---|
| `schema_version` | TSV schema version。現在は`6` |
| `frame`, `frame_hex`, `time_seconds`, `palette_segment` | Decimal frame、HUD形式hex frame、正確なplayback time、CRAM palette-segment index |
| `cells`, `active_tiles`, `budget_tiles`, `cold_cap_tiles`, `prefetch_cap_tiles` | Self-contained filter用に各rowへ繰り返すrasterとlimit。`cold_cap_tiles`は全物理cold sourceへ適用するeffective cap。物理配信失敗はsimを停止し、local per-frame capは作らない |
| `legend_raw`, `legend_same`, `legend_dic`, `legend_prg`, `legend_wr`, `legend_wr0`, `legend_wr1`, `legend_near`, `legend_flbk`, `legend_miss` | Frameごとのcategory count。表示`legend_wr`はWr0+Wr1で、source bank別の値も保持 |
| `status_req`, `status_miss`, `status_cold`, `status_pre`, `status_band_kib_s`, `status_prg`, `status_wr0`, `status_wr1`, `status_dma`, `status_run` | Frame-0のuntimed ruleを含むbottom status barの数値 |
| `body_payload_bytes`, `body_control_bytes`, `body_pad_bytes`, `body_physical_bytes`, `body_useful_bytes`, `body_band_bps` | Band表示の元になる正確なphysical timed-BODY delivery-slot会計。Frame 0はuntimed BODY arm由来なのでslot 0は0 |
| `quality_budget_remaining_bytes` | Frame後に残る、借入ではないencoder-only全編画質allowance。Terminal-drain loan中はzeroを表示し、将来suffix allowanceの返済後に増える。Diagnostic stateであり物理meterではない |
| `stat_frame`以降の`stat_*` | `stats.npz`の全columnを元の順序で保存。Simulatorへstatisticが増えると追加される |

Compatibility aliasは`ANALYSIS_OUT`に従います。例えば
`videos/example_analysis.mp4`へ変更するとtimestamp付き`logs/*.tsv`を生成し、
`ANALYSIS_TSV`で別aliasを選ばない限り`videos/example_analysis.tsv`を更新します。

## Layout map

```text
+----------------------------------------------+   +-----------------------------+
| SEGA-CD sim output  <meta>      <PL/Time/Fr> |   | Source  <res/fps/audio>     |
| +------------------------------------------+ |   | +-------------------------+ |
| |                                          | |   | | source frame (4:3)      | |
| |   SEGA-CD OUTPUT (real screen中央、       | |   | +-------------------------+ |
| |   panelにletterbox)                      | |   | LEGEND (2 rows, 9 classes)  |
| |                                          | |   | +-------------------------+ |
| |                                          | |   | | CATEGORY MAP (4:3)      | |
| |                                          | |   | | tile content + border   | |
| |                                          | |   | | Miss = red-filled hole  | |
| +------------------------------------------+ |   | +-------------------------+ |
+----------------------------------------------+   | CATEGORY TOTALS (whole clip)|
+----------------------------------------------+   | +-------------------------+ |
| STATUS BAR                                   |   | | AUDIO WAVEFORM          | |
| [Req][Cold][Pre][Band][Prg][Wr0][Wr1]...       | | | +/-2s, now = centre     | |
| Prev/Current/Next palette strip              |   | +-------------------------+ |
| 4 timelines (Req / Supply / Run / Band)      |   +-----------------------------+
+----------------------------------------------+
```

`layout_preview.py`内のregionは、左が`MAIN_FRAME`、右columnの上から
`SRC_FRAME`、`CATLEG_XY`、`CAT_FRAME`、`CATTOT_XY`、`WAVE_FRAME`、
左下が`STATUS_XY`です。Per-metric flow graphや独立palette-total slotはありません。

## Heading

- **SEGA-CD sim output**（左上）: 大labelと
  `mode / WxH (cols x rows) / audio / fps / avg N KiB/sec`のmeta line。
  - `mode`はH32、H40、mode4。`WxH`はencode tile gridのpixel size、
    `cols x rows`は8x8 tile単位のgridです。
  - `avg N KiB/sec`は全編のuseful BODY delivery Band平均です。
- **PL/Time/Frame**（右上）:
  `PL:cur/total Time:MM:SS.ss Frame:XXXX`。
  `PL`はcurrent palette-segment index / highest indexです。`Frame`はhardware
  DEBUG HUDのFと一致する4-digit hexです。
- **Source**（右column上）: 大labelと、`ffprobe`から得るsource videoの
  `resolution / fps / audio codec+rate+channels`。Bitrateは表示しません。

## Main panel（左）

復元したSEGA-CD outputです。H32なら256x224などの実hardware screen中央へ置き、
modeのdisplay aspect（H32/H40は4:3、mode4は約14:9）でpanelへletterboxします。
Panel全体へstretchしないため、low-resolution gridは実画面上のsizeで表示されます。

## 右column

- **Source**: crop後のsource frameをcategory mapと同じ4:3 panelへscaleします。
  表示幅は`source.sar`を守ります。Raw rasterが中央配置されたsub-apertureの場合、
  profileで`analysis.source_canvas = [width, height]`を指定できます。Rendererは
  coded sizeのrasterをblack canvas中央へ置いてからpanelへfitします。
- **Legend**: Sourceとcategory mapの間に置きます。1 row目は
  `Raw Same Near Flbk Miss`、2 row目は`Prg Wrd Dic`です。表示`Wrd`は
  `Wr0 + Wr1`です。Numeric fieldはlegend background上のtextで、digit背後のlevel
  fillはありません。`Same`はlight/dark checker、`Raw`はblack/white dashed frame、
  `Miss`はred fill、`Near/Flbk`はthin frame、`Dic/Prg/Wrd`はcategory colourとblackを
  交互に使うthin borderです。
- **Category map**: 各8x8 tileへ**reconstructed content**を描き、categoryをborderで
  示します。`Raw`はthin black/white dashed、`Same`はborderなし、`Near/Flbk`は
  thin 1px、`Dic/Prg/Wr0/Wr1`はcolour/black dashedです。Wr0とWr1は同じcyanを
  使います。`Miss`はcontentを更新せず、red-filled holeとして描きます。
- **Category totals**: Category map直下の`CATTOT_XY`です。全編category totalを
  thin stacked barとcompactなswatch+count legendで示します。Unique countは
  表示せず、全編で固定です。
- **Audio waveform**: 下部`WAVE_FRAME`にsim playback-model audioのscrolling
  envelopeを描きます。ADPCM22ではclean sourceではなく、checkpoint付きIMAを
  encode/decodeし、RF5C164の8-bit sign-magnitudeへ変換した信号です。元のsigned-16
  WAVはpacker inputとして別に残ります。Windowは±2秒、white centre lineが現在で、
  左の過去をbright green、右の将来をdim greenで描きます。
- 独立したper-metric flow-graph panelはありません。

## Tile category

会計countは各8x8 tileを、正確な再利用・fresh loadからMissまでの1つの表示classへ
割り当てます。Cellごとのstyle maskは、allocator orderにより物理cold load attributionと
Near/Flbk結果が同じcellへ置かれると重複できます。Category mapはこの両方を保ち、
会計totalは変えません。EncoderはVRAM-resident patternを探索し、現在のbyte budget内で
最適なmatchを選びます。

### F3 similarity metric

Target tileとcandidate resident patternをRGB333（channel 0..7）で比較し、64 pixelに
対して3つの差を計算します。

- **Ym**: `|luma(target) - luma(candidate)|`のmean
- **Yp**: 同じpixel単位luma errorのmax。細いedgeやshape changeを検出
- **C**: `sqrt((Cb_t - Cb_c)^2 + (Cr_t - Cr_c)^2)`のmean

`luma = 0.299R + 0.587G + 0.114B`、
`Cb = -0.169R - 0.331G + 0.5B`、
`Cr = 0.5R - 0.419G - 0.081B`です。Candidateは`Ym`、`Yp`、`C`の3 thresholdを
すべて通る場合だけtierへ入ります。Tightなtierから試すため、最もtightな適合tierを
labelにします。

### Tier threshold（default、envで変更可能）

| Tier | Ym | Yp | C | env |
|---|---:|---:|---:|---|
| Near | 10 | 28 | 24 | `CBRSIM_NEAR_YM/YP/C` |
| Flbk | 120 | 252 | 200 | `CBRSIM_TFLBK_YM/YP/C` |

小さいthresholdほどstrictで、visual matchが良くなります。Near外のcandidateでは、まず
exact cold loadを試します。Exact loadが収まらない場合だけFlbkを検討します。
Defaultのimprove-only modeでは、current displayよりtargetへ近いbest residentだけを
受け入れます。表のwide Flbk boundはoptional absolute-threshold mode用です。

### 9つのclass

| Class | Colour | Bytes | 意味 |
|---|---|---:|---|
| **Raw** | black/white dashed border | 34 | このframe用に配信し、display前にVRAMへloadしてすぐ使うexact pattern。Timed frameはcold cap内。Frame 0は`HEADER.DAT`からboot loadするため対象外 |
| **Same** | legendのchecker、map borderなし | 0または2 | Target exact patternがすでにVRAM resident。前frameでprefetchされ、このframeで初表示するpatternも含む |
| **Near** | grey thin border | 2 | Exact matchはないがresident patternがNear thresholdを通る。現在表示が正確でnew targetのNear内なら0-byte keepも含む |
| **Flbk** | yellow thin border | 2 | Exact loadが使えない場合のfallback。表示を改善するため、Missとは別 |
| **Miss** | red fill | 0 | Tileを更新せず、直前の表示内容を保持 |
| **Prg** | violet/black dashed border | 34 | 全編allowanceでfundし、streamed PrgBufから供給するexact cold load |
| **Wr0** | cyan/black dashed border | 2 | boot-preloaded WordBuf0 pattern。Legendでは`Wrd`へ合算 |
| **Wr1** | cyan/black dashed border | 2 | boot-preloaded WordBuf1 pattern。Legendでは`Wrd`へ合算 |
| **Dic** | amber/black dashed border | 2 | persistent DicBuf entryを使うexact cold load |

### 選択順（changed tileごとの`commit_unified`）

Frame 0は例外で、timed BODY/cold budgetを持たず、全cellをexact targetとしてinstallします。
同じexact patternを最初に使うcellは`Raw`、それ以降は`Same`です。Frame 0の表示totalでは
`Near`、`Flbk`、`Prg`、`Wr0`、`Wr1`、`Dic`、`Miss`は0です。表示pattern配置後、
未使用startup capacityへ将来のexact patternをprefetchできますが、frame 0の
displayed-cell categoryは持ちません。

自動3-phase passで選びます。

1. Freeまたは2-byte choiceを先にcommitします。現在表示がexactでNear内なら0 byteで
   keepし、それ以外はresident exactを`Same`、almost-identical residentを`Near`にします。
2. 残cellをpriority順に集め、まだdefer中の全cellへ2-byte name entryを残しながら
   exact cold loadを試します。Sourceは`Raw`、`Prg`、`Wr0/Wr1`、`Dic`で、effective
   cold capを守ります。
3. Exact load後にresident candidateを再計算します。Exactに選ばれなかったcellは、
   current displayを改善するresidentを`Flbk`として使い、それもなければ`Miss`にします。
   Target mean-colour bucketに改善結果がない場合、26個のadjacent bucketも調べます。

Name-entry reservationは内部処理で、設定値ではありません。Early exact loadがframe
allowanceを使い切り、fallback phaseへ到達できなくなることを防ぎます。

`Same/Near/Flbk`はresident 32-byte patternを使い、最大2-byte name entryだけが必要です。
`Raw/Prg`はencoder model上34 byte、Wr0/Wr1/Dicはpattern byteをすでに持つためplayback中は
2-byte name entryだけです。0.2秒以上Near/Flbkに残るpersistent approximationはMiss
severityへ上がり、budgetが使えるときexact reloadを優先します。Thresholdは
`max(1, floor(0.2 * fps))`です。

Selection前にchanged tileを、current visual RGB error、optional detail weight、
distance-weighted aging、screen-edge discountで並べます。Aging pressureはMissまたは
Flbk中だけ増え、Nearは対象外です。TSVの`carry`と`age`は別のinteger Miss wait counterで、
updateやupgrade priorityへ影響しません。

## Status bar（左下）

左から**Req**、**Cold**、**Band**、**DMA**、**Run**、**Prg**、**Wrd**、**Pre**です。
Wrdは物理的に別のWr0とWr1を合算表示します。下にpalette strip、右に4本のstacked
timelineがあります。Tankまたは物理Buf meterはありません。

### Req meter

全categoryを1 barへstackし、full widthをtile総数`C`とします。Yellow vertical lineが
frameごとのupdate budgetです。Labelは`Req:NNN Miss:NNN`です。

### Cold meter

`Cold:NNN`はこのframeの**timed new tile load**です。
`Raw + Prg + Wr0 + Wr1 + Dic + future raw prefetch`、つまり全物理sourceからVRAMへ
新しく書いた32-byte patternを数えます。Barはcategory/source colourとblue prefetchを
stackし、full-scaleはeffective cold capです。Baselineは一般に
`round(5400 / fps)`で、qualification済みnominal 30 fps baselineは200です。Profileは
これを引き上げられます。Frame 0はtiming外なので`Cold:000`ですが、Raw/Same countは
legendへ表示します。

### Pre meter

`Pre:NNN`はtimed frameが、まだ表示せずに書くfuture exact pattern数です。Frame 0のboot
prefetchはmeter外で`Pre:000`です。Capacityとrealized countはdecision logとreportへ
残ります。Prefetch patternを後で使うcellは`Raw`ではなく`Same`です。

### Band meter（useful BODY delivery、KiB/sec）

`Band`はdelivery slotで物理的に読む`BODY.DAT`のnon-pad dataを、そのslotの実CD read
timeで割った値です。

```text
Band = useful BODY bytes / physical BODY bytes * 150 KiB/sec
```

Physical byteはpadを含むwhole sectorです。CD 1xでは1 sectorが1/75秒なので、fully useful
slotは`Band:150`、half-pad slotは`Band:075`となり、valid slotは150を超えません。

Barは左から、same-frame Raw-funded payloadのlight grey、残りのquality-budgetまたは
prefetch pattern chargeのPrg purple、continuous control streamのdim blue-greyです。
Timelineも同じstackを使います。Future payloadはtarget frameではなく、実際にprefetchした
slotで数えます。

Physical delivery traceはtotal payloadを正確に持ちますが、1 frame内のRaw/Prg順序は
保存しません。解析はRaw countをPrgBuf loadへ均等配置し、HEADER prebuffer prefixを除き、
残りをphysical BODY slotへ対応付けます。Total payloadとinput countは正確ですが、
prebuffer境界・slot間のRaw/Prg splitはvisualizationです。

On-disc format version 17のcontrolには、そのframeで選んだshadow-update表現、つまりbitmap +
name entryまたはcompleted offset/entry listのbyte costを含みます。独立meterは作らず、
dim control部分へ含めます。

Rate-match pad sector、final sectorのzero tail、`HEADER.DAT`全体、untimed BODY arm
全体（frame-0 pattern/controlとdecoded startup audio）、palette、routing、
compatibility `MOVIE.DAT`は除外します。Slot 0は`Band:000`です。Top metaの
`avg N KiB/sec`と`report.txt`の`body_useful_bps`は、全useful timed-BODY byteを
complete timed-BODY read timeで割るphysical-time-weighted averageです。
`codec_work_bps`は別の画質配分diagnosticです。

Barのfull-scaleはslotのphysical byteで、payload/controlがuseful fractionを埋め、
padはblankです。右端のthin yellow lineがCD 1xを示します。

Encoderは選択前にcomplete quantized movieをshared VRAM allocatorでdry-runします。
Continuous Main-risk burstがquality-budget capacityを超える場合、unavoidable shortfallを
burst startからpeakへ比例配分します。Backwards passが将来のFlbk/Miss burstを守る
reserveを作ります。Optional exact-load upgradeはcomplete exact demandから別のstrict
reserveを使います。両curveは0で終了し、各traceは`buffer_remaining.npz`へ保存しますが、
物理supply meterではありません。構築と適用は[`BUEFFERING.md`](BUEFFERING.md)に
記載します。

### 3つのpattern-supply meter

| Meter | 物理object | 動作 |
|---|---|---|
| `Prg:NNNNN` | usable PRG-RAM `PrgBuf` | Exact sector schedulerのend-of-frame occupancy。BODY prefetchで増え、Prg消費で減る |
| `Wr0:NNN` | physical bank 0の`WordBuf0` | actual boot-loaded totalからeven frame消費分を引く。減少のみ |
| `Wr1:NNN` | physical bank 1の`WordBuf1` | actual boot-loaded totalからodd frame消費分を引く。減少のみ |

Prg traceは`HEADER.DAT` prebuffer、whole-sector payload tail、per-slot prefetch、
realized Prg consumptionを含みます。Packerはbuilt controlから再計算し、不一致を拒否します。
Preload traceはactual loaded totalを使うため、未使用fixed capacityをcontentとして
表示しません。Offline quality budgetはpattern byteをplayerへ供給できないため、
これらのmeterへ表示しません。

### DMA meter

`DMA:NNN`または`DMA:NNNN`はtimed frameでVRAMへtransferする**32-byte pattern tile数**です。
Digit数はrasterに合わせます。Frame 0は0です。Full-scaleはmode/fpsの理論VDP byte ceiling
からfull name-table DMAを引き、32 byte/tileで割ってraster tile数へclampします。
通常green、ceiling超過時はorangeとred overflow tailです。

### Pattern transfer run meter

`Run:NNNN`はcold VRAM slotのascending consecutive run数です。Packerのdescriptor、
Main CPU RUN_TABLE record、H40 DEBUG HUD `N`と一致します。Reuse entryはrunを分けず、
slot discontinuity、pool endからslot zeroへのwrap、Prg/Wr/Dic source境界が分割します。
Frame 0はtimed計算外なので`Run:0000`です。Encoderはexact Run traceを報告し、
全編slot-number最適化は行いません。

これはVDP DMA command数ではありません。1・2 tile runはCPU direct copy、長いrunはDMAを
使い、VBlank budget境界で複数DMAに分かれる場合があります。それでもRun recordは1つです。
Bar full-scaleはcurrent DMA tile countで、全tileが1-tile runになる場合がworstです。

### Palette strip

`Prev` / `Current` / `Next`を各4 palette x 15 colourで表示します。Square tileを
2 row x 30に並べ、`Current`へborderを付けます。Headingは
`Prev PL:NNN Frame:NNNNN`形式です。前後segmentがないedge slotはblankです。

### 4本のstacked timeline

Reqが高さの1/2、Supplyが1/4、RunとBandが残り1/4を分けます。全rowが全編x-axisと
white playheadを共有します。

1. **Req heatmap**: `Raw / Prg / Wr0 / Wr1 / Dic / Near / Flbk / Miss`。
   `Same`は省略します。
2. **Pattern supply**: `Prg / Wrd` remaining countをstackします。Wrdは別々のWr0/Wr1
   traceをpixel scale前に合算するため、合算値が正なら最低1pxまで表示されます。
   scaleはPrg、Wr0、Wr1のcapacity合計です。Persistent DicBufにはremaining countが
   ないため省略します。
3. **Run**: このTSVのtimed実測最大を上端にしたphysical source-aware cold-run count。
   Frame 0はscaleに含めません。
4. **Band**: physical slot byteに対するRaw payload、Prg charge、controlの割合。
   Padはblankで、row topがCD 1xです。

Detailed whole-movie timelineはfinal Prg payload delivery直後をevaluation boundaryとして
markします。Terminal no-refill suffixはred shadingで残しますが比較評価から除外します。
Sim、pack、playback verificationは全編を対象にします。

## Colour（RGB）

Raw `(205,205,205)`、Same `(150,150,158)` grey、
Near `(128,134,144)` grey、Flbk `(225,185,25)` yellow、
Miss `(220,70,70)` red、DMA `(70,190,90)` green、
DMA-run `(215,165,65)` amber、Band-control `(95,110,122)` blue-greyです。
Physical supplyはPrg `(165,105,225)`、Wr0/Wr1 `(65,205,195)`、
Dic `(220,120,30)`です。Dic、Prg、Wrdのthin borderはcategory colourとblackを
交互に使います。全rendererは`tools/analysis_style.py`のsemantic colourとborder styleを
使います。
