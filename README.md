EN / [JP](#jp)

# Tile Texture Reuse Codec — a SEGA-CD / Genesis FMV codec

Tile Texture Reuse Codec is a full-motion-video codec designed for Sega CD
hardware. It targets the Genesis VDP tile and CRAM model, continuous CD 1x
delivery, Sub-CPU PRG RAM, 1M/1M Word RAM, and the RF5C164 PCM chip. The same
stream runs on physical hardware and Genesis Plus GX.

The on-disc stream contains an explicit version. Generic repository filenames
keep the implementation independent from the displayed codec name.

## Core idea

The Genesis screen is built from 8x8 patterns in VRAM and a name table that
chooses one pattern for each cell. Reusing a resident pattern costs a two-byte
name-table entry; loading a fresh pattern costs 32 bytes plus its name entry.

The encoder therefore asks, for every changed cell:

> Is a suitable pattern already resident, so this cell can point to it?

Exact resident reuse, visually close reuse, and improving fallback reuse save
CD bandwidth and VBlank transfer time. New patterns are loaded only when the
available resident choices are not good enough.

## Hardware-shaped design

- **CRAM palettes.** The VDP exposes four palette lines with 15 usable colours
  each. The encoder trains 60 colours, creates local segments at safe
  transitions, and preloads every segment palette into Main RAM. A timed
  switch carries only a palette reference. The darkest and brightest existing
  colours are moved to fixed DEBUG HUD positions without changing the colour
  set.
- **Resident VRAM pool.** Tiles 1–1,535 form one persistent pattern pool shared
  by H32 and H40. Each name-table update points into this pool.
- **Near and Flbk reuse.** Near accepts a visually close resident. Flbk accepts
  a resident only when it improves the displayed cell. Exact work reserves the
  name bytes needed by fallback work before spending the physical allowance.
- **Four pattern supplies.** PrgBuf is streamed through Sub-CPU PRG RAM.
  WordBuf0 and WordBuf1 are different boot-preloaded sequences selected by
  frame parity. DicBuf is a persistent 256-entry Main-RAM dictionary.
- **Whole-movie quality planning.** A dry run predicts future exact and
  Miss-risk demand. The encoder reserves enough offline allowance for hard
  bursts, assigns boot-preload credits, and keeps quality funding separate from
  the physical pattern source.
- **Sector-aware scheduling.** Control bytes, run descriptors, CRAM switches,
  audio, Prg payload, and pad share one physical-sector plan before per-frame
  decisions are frozen. The packer replays the same proof.
- **VBlank-limited transfer.** Screen geometry and cold work must fit the
  mode-specific Main-CPU transfer budget.
- **Checkpointed audio.** The only TTRC v16 audio format is 22.05 kHz mono IMA
  ADPCM. Sub decodes it to RF5C164 samples while continuously servicing CD
  delivery.

## Configurable within Sega CD limits

Each source has a strict TOML profile.

- **Display:** H32, H40, or mode4; tile-aligned output geometry and
  aspect-aware pad/crop conversion.
- **Frame rate:** the source's native rate, including delivery-paced rates
  such as 24 fps.
- **Audio:** checkpointed 22.05 kHz mono IMA ADPCM.
- **Cold cap:** an fps-derived baseline, optionally raised by a fully qualified
  source profile.
- **Palette algorithm:** `stl4` or `mosaic-gm`.
- **Analysis canvas:** optional and never changes the encoded stream.

See [`CONFIG.md`](CONFIG.md) for the complete schema and limits.

## Simulation pipeline

`tools/sim.py` uses six named stages:

```text
Extract -> Palette -> Quantize -> Forecast -> Decide -> Finalize
```

1. **Extract** decodes encoder frames, comparison frames, and mono audio.
2. **Palette** finds segment boundaries and trains Genesis CRAM palettes.
3. **Quantize** produces palette assignments and indexed 8x8 patterns.
4. **Forecast** calculates future demand, physical limits, quality reserves,
   and boot-preload use.
5. **Decide** chooses exact or reused patterns, allocates physical VRAM slots,
   assigns Prg/WordBuf/DicBuf sources, and commits the physical budget.
6. **Finalize** verifies the complete schedule and writes numeric traces and
   the decision log.

Disc packing follows simulation. Analysis rendering is optional and separate;
preview and category PNGs are generated only by `tools/render_analysis.py`.
See [`ENCODE.md`](ENCODE.md) for current measured stage times.

## Analysis

The optional 1920x1080 analysis video shows decoded Sega CD output, source,
per-cell categories, audio, physical delivery, pattern supplies, DMA, and
whole-movie timelines. Frame 0 is omitted from timed-work values and graph
maxima.

[`ANALYSIS.md`](ANALYSIS.md) defines every panel, meter, category, and TSV
field. [`HUD.md`](HUD.md) defines the values-only hardware/emulator DEBUG HUD.

## Documentation

- [`ENCODE.md`](ENCODE.md): simulation stages and measured processing time.
- [`CONFIG.md`](CONFIG.md): profile schema, shared settings, throttles, and
  capacities.
- [`MOVIE.md`](MOVIE.md): exact TTRC v16 `HEADER.DAT` / `BODY.DAT` format.
- [`BUEFFERING.md`](BUEFFERING.md): physical pattern supplies and whole-movie
  quality planning.
- [`STREAMING.md`](STREAMING.md): live Main/Sub memory maps and headroom.
- [`ANALYSIS.md`](ANALYSIS.md): analysis video and TSV reference.
- [`HUD.md`](HUD.md): DEBUG HUD layout, units, gate, and OCR workflow.
- [`ADPCM.md`](ADPCM.md): supported audio format and Sub-CPU decoder.
- [`BUDGETS.md`](BUDGETS.md): tile, DMA, and CD first-order budgets.
- [`REMOVED.md`](REMOVED.md): implementation notes for removed features that
  may inform a clean reimplementation.
- [`AGENTS.md`](AGENTS.md): maintenance, recording, and agent guidance.
- [`CLAUDE.md`](CLAUDE.md): compatibility entry point for the shared guidance.

## Implementation

- `tools/sim.py`: offline encoder. It writes the frozen decision log,
  `buffer_remaining.npz`, analysis data, and the completed artifact marker.
- `tools/pack_stream.py`: verifies decisions and writes `HEADER.DAT`,
  `BODY.DAT`, off-disc `MOVIE.DAT`, and `palettes.bin`.
- `tools/render_analysis.py`: materializes analysis PNGs, TSV, and video from a
  completed sim result.
- `tools/layout_preview.py`: shared analysis layout and graph rendering.
- `tools/physical_budget.py`: per-frame control/Prg ceilings and prefix ledger.
- `tools/stream_schedule.py`: exact BODY routing and physical slot schedule.
- `boot/movieplay_sp.s`: Sub-CPU disc, PrgBuf, Word-RAM, ADPCM, and handoff
  runtime.
- `boot/movieplay_ip.s`: Main-CPU VRAM, CRAM, name-table, DMA, and DEBUG HUD
  runtime.

Completed sim artifacts are reusable only when source bytes, effective
settings, and the output-affecting encoder fingerprint match. Sim work and
derived videos use the managed tmpfs workspace behind `videos/`; native
lossless emulator captures remain ordinary files. Per-frame TSVs remain under
`logs/`.

## Build targets

| Target | Purpose |
|---|---|
| `movieplay` / `disc` | TTRC player disc. |
| `cdcbench` | Continuous and restarted CD-read measurement. |
| `dmabench` | Maximum VRAM DMA per VBlank and screen mode. |
| `still256` | Static H32 display bring-up. |
| `streamtest` | Minimal continuous stream test. |
| `pcmtest` | RF5C164 register and wave-RAM test. |
| `test1m` | 1M/1M Word-RAM swap test. |
| `prgtest` | PRG-RAM and streaming interaction test. |
| `asictest` / `upscaletest` | Graphics ASIC and CPU-upscale experiments. |

## Workstation setup

Ubuntu host packages:

```sh
sudo apt update
sudo apt install \
  ffmpeg fonts-ipafont-gothic genisoimage imagemagick \
  libretro-genesisplusgx \
  pipx \
  retroarch rsync xdotool xvfb
```

Install the pinned `uv` and isolated CPU environment:

```sh
pipx install 'uv==0.11.29'
tools/bootstrap_python.sh --cpu
tools/python.sh -c \
  'import sys, numpy, PIL; print(sys.base_prefix, numpy.__version__, PIL.__version__)'
```

For NVIDIA GPU acceleration:

```sh
tools/bootstrap_python.sh --gpu
tools/python.sh --gpu -c \
  'import cupy as cp; assert int(cp.arange(16).sum()) == 120'
```

`tools/python.sh` selects `.venv`; `tools/python.sh --gpu` selects
`.venv-gpu`. Neither falls back to system Python or distribution packages.
The lock uses managed CPython 3.14.4 for CPU, CPython 3.13.14 for GPU, NumPy
2.3.5, Pillow 12.1.1, and CuPy 14.1.1.

Install a Marsdev `m68k-elf` toolchain at `~/toolchains/mars`, or set
`MARSDEV` / `M68K_PREFIX` to another installation. The Makefile expects:

```text
m68k-elf-as
m68k-elf-gcc
m68k-elf-ld
m68k-elf-objcopy
```

Check the toolchain and ISO writer:

```sh
make check-tools CONFIG=configs/PROFILE.toml
```

The Japanese Mega-CD BIOS is user-supplied and git-ignored:

```sh
install -d -m 700 ~/.config/retroarch/system
install -m 600 original/jp_mcd2_9212.bin \
  ~/.config/retroarch/system/bios_CD_J.bin
```

The recording harness defaults to
`/usr/lib/x86_64-linux-gnu/libretro/genesis_plus_gx_libretro.so`. `CORE`,
`BIOS_IMAGE`, and `SYSTEM_DIR` override host-specific layouts.

## Build

Run a full encode and DEBUG disc build:

```sh
tools/python.sh --gpu tools/sim.py configs/PROFILE.toml
make disc CONFIG=configs/PROFILE.toml DEBUG=1
```

`make disc` cleans the selected profile's packed stream, verifies the
profile-authenticated `decisions.pkl`, specializes the player, and writes:

```text
out/PROFILE/HEADER.DAT
out/PROFILE/BODY.DAT
out/PROFILE/MOVIE.DAT
out/PROFILE/palettes.bin
out/PROFILE.iso
out/PROFILE.cue
```

Transient objects, disc staging, and direct-emulator scratch files live under
`tmp/PROFILE/`. `HEADER.DAT` contains startup state, exact frame 0, boot VRAM
prefetch, and the PrgBuf prebuffer. `BODY.DAT` starts at frame 1 and is read
continuously.

## Recording

Use emulator-synchronized A/V:

```sh
tools/record_movie.sh --config configs/PROFILE.toml \
  --seconds 180 --tag STEM_emu --out videos/STEM_emu_preview.mp4
```

The recorder defaults to fixed-Replay, faster-than-realtime, native-size
FFV1/FLAC. The MP4 is a quick verification preview. `--realtime-lossless`
creates a paced FFV1/FLAC diagnostic baseline. `--preset realtime` is 4:2:0
and is not an upload master. Recordings retain Mega-CD startup unless an
explicit movie-only trim is requested.

Every full DEBUG recording requires complete HUD extraction, gate evaluation,
and a public hudline. Analysis/playback publishing continues only after PASS
or WARNING.

## YouTube upload setup

OAuth credentials and their Python environment stay outside the repository:

```text
~/.claude/skills/youtube/youtube.py
~/.claude/skills/youtube/client_secret.json
~/.config/youtube/youtube_token.json
~/.config/youtube/venv/
```

Create the local environment:

```sh
uv venv --managed-python --python 3.14.4 ~/.config/youtube/venv
uv pip install --python ~/.config/youtube/venv/bin/python \
  google-api-python-client google-auth-oauthlib google-auth-httplib2
chmod 600 ~/.claude/skills/youtube/client_secret.json \
  ~/.config/youtube/youtube_token.json
```

The token needs the complete `youtube` scope and a valid refresh token. Never
commit client secrets, tokens, BIOS files, source media, generated videos, or
upload sidecars.

## Repository layout

```text
boot/        68000 Main/Sub player and hardware tests
cfg/         linker scripts
configs/     per-source TOML profiles
harness/     reproducible diagnostics and their local documentation
tools/       encoder, packer, analysis, build, and recording tools
vendor/      third-party reference code
```

Generated output and copyrighted source media are not part of the public
repository.

<a id="jp"></a>

# Tile Texture Reuse Codec — SEGA-CD / Genesis FMV codec

Tile Texture Reuse CodecはSega CD hardware専用に設計したfull-motion-video
codecです。Genesis VDPのtile/CRAM model、連続CD 1x delivery、Sub-CPU PRG RAM、
1M/1M Word RAM、RF5C164 PCM chipを直接対象にします。同じstreamを実機と
Genesis Plus GXで再生します。

ディスク上のstreamは明示的なversionを持ちます。repository内のgeneric filenameに
より、実装pathは表示上のcodec名から独立しています。

## 中心となる考え方

Genesisの画面は、VRAM内の8x8 patternと、各cellで使うpatternを選ぶname tableから
できています。resident patternの再利用は2-byte name-table entryだけで済みます。
fresh patternのloadには32 byteとname entryが必要です。

そのためencoderは変更cellごとに次を判断します。

> 適切なpatternがすでにresidentで、そのpatternを参照するだけで済むか？

正確なresident再利用、見た目が近い再利用、表示を改善するfallback再利用は、CD帯域と
VBlank transfer時間を節約します。利用可能なresident候補が十分でないときだけ新しい
patternをloadします。

## Hardwareに合わせた設計

- **CRAM palette。** VDPは使用可能な15色を持つpalette lineを4本表示します。encoderは
  60色を学習し、安全なtransitionでlocal segmentを作り、全segment paletteをMain RAM
  へpreloadします。timed switchはpalette参照だけを持ちます。色集合を変えず、既存の
  最暗色と最明色をDEBUG HUDの固定位置へ移します。
- **Resident VRAM pool。** tile 1〜1,535をH32/H40共通のpersistent pattern poolとして
  使います。各name-table updateがこのpoolを参照します。
- **NearとFlbk再利用。** Nearは見た目が近いresidentを採用します。Flbkは表示cellを
  改善するときだけresidentを採用します。exact workは物理allowanceを使う前に
  fallback workに必要なname byteを予約します。
- **4つのpattern供給。** PrgBufはSub-CPU PRG RAMへstreamします。WordBuf0とWordBuf1は
  frame parityで選ぶ異なるboot-preload sequenceです。DicBufはpersistent 256-entry
  Main-RAM dictionaryです。
- **Movie全体quality planning。** dry runが将来のexact demandとMiss-risk demandを
  予測します。encoderは難しいburstに必要なoffline allowanceを予約し、boot-preload
  creditを割り当て、quality fundingと物理pattern sourceを分離します。
- **Sector-aware scheduling。** per-frame decision確定前に、control byte、run descriptor、
  CRAM switch、audio、Prg payload、padを1つの物理sector planへ入れます。packerが同じ
  proofを再生します。
- **VBlank-limited transfer。** screen geometryとcold workはmode別Main-CPU transfer
  budgetへ収めます。
- **Checkpointed audio。** TTRC v16のaudioは22.05 kHz mono IMA ADPCMだけです。Subは
  連続CD deliveryを処理しながらRF5C164 sampleへdecodeします。

## Sega CD limit内で設定できるもの

sourceごとにstrict TOML profileを使います。

- **Display:** H32、H40、mode4。tile-aligned output geometryとaspect-awareなpad/crop。
- **Frame rate:** 24 fpsのようなdelivery-paced rateも含むsource native rate。
- **Audio:** checkpointed 22.05 kHz mono IMA ADPCM。
- **Cold cap:** fps由来baseline。完全に認定したsource profileだけ引き上げ可能。
- **Palette algorithm:** `stl4` または `mosaic-gm`。
- **Analysis canvas:** optionalで、encoded streamは変えない。

schemaとlimitの全体は [`CONFIG.md`](CONFIG.md) を参照してください。

## Simulation pipeline

`tools/sim.py` は6つの名前付きstageを使います。

```text
Extract -> Palette -> Quantize -> Forecast -> Decide -> Finalize
```

1. **Extract** はencoder frame、comparison frame、mono audioをdecodeします。
2. **Palette** はsegment boundaryを見つけ、Genesis CRAM paletteを学習します。
3. **Quantize** はpalette assignmentとindexed 8x8 patternを生成します。
4. **Forecast** は将来demand、物理limit、quality reserve、boot-preload利用を計算します。
5. **Decide** はexact/reused patternを選び、物理VRAM slotを割り当て、
   Prg/WordBuf/DicBuf sourceを決め、物理budgetを確定します。
6. **Finalize** は全scheduleを検証し、数値traceとdecision logを書きます。

disc packはsimulationの後に行います。analysis renderはoptionalかつ別工程です。
preview/category PNGは `tools/render_analysis.py` だけが生成します。現在のstage別実測時間は
[`ENCODE.md`](ENCODE.md) を参照してください。

## Analysis

optional 1920x1080 analysis videoはdecoded Sega CD output、source、cell別category、
audio、物理delivery、pattern供給、DMA、movie全体timelineを表示します。frame 0は
timed-work valueとgraph maximumから除外します。

全panel、meter、category、TSV fieldは [`ANALYSIS.md`](ANALYSIS.md)、
実機/emulatorのvalues-only DEBUG HUDは [`HUD.md`](HUD.md) にあります。

## Documentation

- [`ENCODE.md`](ENCODE.md): simulation stageと実測処理時間。
- [`CONFIG.md`](CONFIG.md): profile schema、共通設定、throttle、容量。
- [`MOVIE.md`](MOVIE.md): 正確なTTRC v16 `HEADER.DAT` / `BODY.DAT` format。
- [`BUEFFERING.md`](BUEFFERING.md): 物理pattern供給とmovie全体quality planning。
- [`STREAMING.md`](STREAMING.md): live Main/Sub memory mapとheadroom。
- [`ANALYSIS.md`](ANALYSIS.md): analysis videoとTSVのreference。
- [`HUD.md`](HUD.md): DEBUG HUD layout、unit、gate、OCR workflow。
- [`ADPCM.md`](ADPCM.md): 対応audio formatとSub-CPU decoder。
- [`BUDGETS.md`](BUDGETS.md): tile、DMA、CDの一次budget。
- [`REMOVED.md`](REMOVED.md): cleanな再実装の参考になるremoved featureの実装記録。
- [`AGENTS.md`](AGENTS.md): maintenance、recording、agent guidance。
- [`CLAUDE.md`](CLAUDE.md): shared guidanceへのcompatibility entry point。

## Implementation

- `tools/sim.py`: offline encoder。固定済みdecision log、`buffer_remaining.npz`、
  analysis data、completed artifact markerを書きます。
- `tools/pack_stream.py`: decisionを検証し、`HEADER.DAT`、`BODY.DAT`、ディスク外の
  `MOVIE.DAT`、`palettes.bin` を書きます。
- `tools/render_analysis.py`: completed sim resultからanalysis PNG、TSV、videoを生成します。
- `tools/layout_preview.py`: 共通analysis layoutとgraph rendering。
- `tools/physical_budget.py`: frame別control/Prg ceilingとprefix ledger。
- `tools/stream_schedule.py`: 正確なBODY routingと物理slot schedule。
- `boot/movieplay_sp.s`: Sub-CPUのdisc、PrgBuf、Word-RAM、ADPCM、handoff runtime。
- `boot/movieplay_ip.s`: Main-CPUのVRAM、CRAM、name table、DMA、DEBUG HUD runtime。

completed sim artifactはsource byte、effective setting、outputに影響するencoder fingerprintが
一致するときだけ再利用します。sim workとderived videoは `videos/` の背後にあるmanaged
tmpfs workspaceを使い、native lossless emulator captureは通常fileとして保持します。
frame別TSVは `logs/` に保持します。

## Build target

| Target | 用途 |
|---|---|
| `movieplay` / `disc` | TTRC player disc。 |
| `cdcbench` | continuous/restarted CD read計測。 |
| `dmabench` | screen mode別のVBlank当たり最大VRAM DMA。 |
| `still256` | static H32 display bring-up。 |
| `streamtest` | minimal continuous stream test。 |
| `pcmtest` | RF5C164 register/wave-RAM test。 |
| `test1m` | 1M/1M Word-RAM swap test。 |
| `prgtest` | PRG-RAMとstreaming interaction test。 |
| `asictest` / `upscaletest` | graphics ASICとCPU upscale experiment。 |

## Workstation setup

Ubuntu host package:

```sh
sudo apt update
sudo apt install \
  ffmpeg fonts-ipafont-gothic genisoimage imagemagick \
  libretro-genesisplusgx \
  pipx \
  retroarch rsync xdotool xvfb
```

pinned `uv` とisolated CPU environmentをinstallします。

```sh
pipx install 'uv==0.11.29'
tools/bootstrap_python.sh --cpu
tools/python.sh -c \
  'import sys, numpy, PIL; print(sys.base_prefix, numpy.__version__, PIL.__version__)'
```

NVIDIA GPU acceleration:

```sh
tools/bootstrap_python.sh --gpu
tools/python.sh --gpu -c \
  'import cupy as cp; assert int(cp.arange(16).sum()) == 120'
```

`tools/python.sh` は `.venv`、`tools/python.sh --gpu` は `.venv-gpu` を選びます。
system Pythonやdistribution packageへfallbackしません。lockはCPUにmanaged CPython
3.14.4、GPUにCPython 3.13.14、NumPy 2.3.5、Pillow 12.1.1、CuPy 14.1.1を使います。

Marsdev `m68k-elf` toolchainを `~/toolchains/mars` にinstallするか、別installationを
`MARSDEV` / `M68K_PREFIX` で指定します。Makefileは次を使います。

```text
m68k-elf-as
m68k-elf-gcc
m68k-elf-ld
m68k-elf-objcopy
```

toolchainとISO writerを確認します。

```sh
make check-tools CONFIG=configs/PROFILE.toml
```

Japanese Mega-CD BIOSはuser suppliedかつgit-ignoredです。

```sh
install -d -m 700 ~/.config/retroarch/system
install -m 600 original/jp_mcd2_9212.bin \
  ~/.config/retroarch/system/bios_CD_J.bin
```

recording harnessのdefault coreは
`/usr/lib/x86_64-linux-gnu/libretro/genesis_plus_gx_libretro.so` です。
host固有layoutは `CORE`、`BIOS_IMAGE`、`SYSTEM_DIR` で上書きします。

## Build

full encodeとDEBUG disc build:

```sh
tools/python.sh --gpu tools/sim.py configs/PROFILE.toml
make disc CONFIG=configs/PROFILE.toml DEBUG=1
```

`make disc` は選択profileのpacked streamをcleanし、profile-authenticated
`decisions.pkl` を検証し、playerをspecializeして次を書きます。

```text
out/PROFILE/HEADER.DAT
out/PROFILE/BODY.DAT
out/PROFILE/MOVIE.DAT
out/PROFILE/palettes.bin
out/PROFILE.iso
out/PROFILE.cue
```

transient object、disc staging、direct-emulator scratch fileは `tmp/PROFILE/` に置きます。
`HEADER.DAT` はstartup state、正確なframe 0、boot VRAM prefetch、PrgBuf prebufferを
持ちます。`BODY.DAT` はframe 1から始まり、連続して読みます。

## Recording

emulator-synchronized A/Vを使います。

```sh
tools/record_movie.sh --config configs/PROFILE.toml \
  --seconds 180 --tag STEM_emu --out videos/STEM_emu_preview.mp4
```

recorderのdefaultはfixed-Replay、faster-than-realtime、native-size FFV1/FLACです。
MP4は短時間確認用previewです。`--realtime-lossless` はpaced FFV1/FLAC diagnostic
baselineを作ります。`--preset realtime` は4:2:0でupload masterには使いません。
明示的なmovie-only trimを要求しない限りMega-CD startupを保持します。

full DEBUG recordingごとに、完全なHUD抽出、gate評価、public hudlineが必要です。PASS
またはWARNINGの後だけanalysis/playback publishへ進みます。

## YouTube upload setup

OAuth credentialとPython environmentはrepository外に置きます。

```text
~/.claude/skills/youtube/youtube.py
~/.claude/skills/youtube/client_secret.json
~/.config/youtube/youtube_token.json
~/.config/youtube/venv/
```

local environmentを作ります。

```sh
uv venv --managed-python --python 3.14.4 ~/.config/youtube/venv
uv pip install --python ~/.config/youtube/venv/bin/python \
  google-api-python-client google-auth-oauthlib google-auth-httplib2
chmod 600 ~/.claude/skills/youtube/client_secret.json \
  ~/.config/youtube/youtube_token.json
```

tokenには完全な `youtube` scopeと有効なrefresh tokenが必要です。client secret、token、
BIOS file、source media、generated video、upload sidecarをcommitしてはいけません。

## Repository layout

```text
boot/        68000 Main/Sub player and hardware tests
cfg/         linker scripts
configs/     per-source TOML profiles
harness/     reproducible diagnostics and their local documentation
tools/       encoder, packer, analysis, build, and recording tools
vendor/      third-party reference code
```

generated outputとcopyrighted source mediaはpublic repositoryに含めません。
