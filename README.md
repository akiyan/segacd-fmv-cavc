EN / [JP](#jp)

# Sega CD Constraint-Aware Video Codec — a SEGA-CD / Genesis FMV codec

Sega CD Constraint-Aware Video Codec is a full-motion-video codec designed for
Sega CD hardware. It targets the Genesis VDP tile and CRAM model, continuous CD
1x delivery, Sub-CPU PRG RAM, 1M/1M Word RAM, and the RF5C164 PCM chip. The
same stream runs on physical hardware and Genesis Plus GX.

The on-disc stream contains an explicit version. Generic repository filenames
keep the implementation independent from the displayed codec name.

## Core idea

The core of this project is to **maximize FMV quality within the constraints of
the retro architecture split between the SEGA-CD and Genesis**. CD 1x delivery,
separated memory, multiple CPUs, VBlank, and CRAM palettes are treated as one
whole-movie resource-allocation problem rather than as unrelated limits.

The encoder decides which frames receive quality allowance, which memory domain
holds each pattern, and when the Main or Sub CPU moves it. These decisions are
made inside physical limits before downstream stages begin. Reusing resident
8x8 patterns is one effective technique within this design. Exact, Near, and
Flbk reuse save CD delivery and VBlank transfer work, leaving more capacity for
frames that need new patterns.

## Hardware-shaped design

- **Use every separated memory domain.** PrgBuf in PRG-RAM continuously streams
  future patterns. WordBuf0 and WordBuf1 are boot-preloaded rings in the two
  physical Word-RAM banks for their respective frame parities, refilled during
  streaming by leading BODY payload sectors where delivery has spare room.
  DicBuf in Main RAM keeps 512 frequently reused exact patterns available
  throughout the movie.
- **Coordinate multiple CPUs.** The Sub CPU routes CD sectors, manages PrgBuf,
  decodes ADPCM, and expands the next frame into Word RAM. The Main CPU consumes
  resolved runs for the current frame, transfers patterns to VRAM, updates
  CRAM, and DMAs one statically trimmed band into the single name table;
  during an adopted scroll window it instead stages the full 64-column
  rolling-plane band and republishes the Plane A/B scroll pair in the same
  VBlank. The 1M/1M Word-RAM handoff connects them once per frame,
  and a pending handoff takes priority over future-data prefetch.
- **Reuse VRAM residents.** Tiles 1–1,743 form one persistent pool ending just
  below the fixed HUD font at VRAM `0xDA00`. An exact
  resident needs only a name-table entry. Near uses a
  visually close resident, and Flbk uses a resident that improves the current
  display. A new 32-byte pattern is cold-loaded only when needed.
- **Move the whole picture in hardware.** The encoder automatically detects
  sustained axis-only camera scrolls, adopts only the windows that are
  measurably cheaper than the fixed grid, and streams scroll controls. The
  player rolls a 64x32 Plane A with absolute HScroll/VScroll values, so cells
  the scroll carries need no pattern or name-table update at all (Scrl).
- **Time-slice the CRAM constraint.** The encoder trains 60 colours within the
  VDP's four palette lines of 15 usable colours each. The movie is segmented at
  safe transitions, every segment palette is preloaded into Main RAM, and
  timed playback switches palettes using only a small reference. It also
  automatically detects static shots that fade in and out through black,
  freezes each shot's indexed image, and reproduces the brightness steps with
  exact inline CRAM replacements. No source-time range is configured.
- **Allocate quality backwards from the movie end.** A dry run predicts future
  exact and Miss-risk demand, then works backwards to reserve quality allowance
  and boot-preload credits for difficult frames. Control, run descriptors,
  CRAM switches, audio, Prg payload, and pad share one physical-sector plan,
  while quality funding remains separate from the physical pattern source.
- **Keep VBlank and audio on dedicated paths.** Screen geometry and cold work
  stay inside the Main-CPU transfer budget. A custom IMA ADPCM
  decoder on the Sub CPU converts 22.05 kHz mono audio into RF5C164 samples,
  preserving CD bandwidth for video.

## Configurable within Sega CD limits

Each source has a strict TOML profile.

- **Display:** tile-aligned output geometry inside the H40 320x224 aperture,
  with aspect-aware pad/crop conversion.
- **Frame rate:** the source's native rate; 24 fps uses a qualified repeating
  two/three-VBlank cadence at 24000/1001 fps.
- **Audio:** checkpointed 22.05 kHz mono IMA ADPCM.
- **Cold cap:** a required per-source profile value, changed and qualified
  through that profile.
- **Palette algorithm:** `stl4` or `mosaic-gm`.
- **Analysis canvas:** optional and never changes the encoded stream.
- **Disc region:** Japan or North America, and both are NTSC.

**The discs are NTSC only.** The player displays H40 V28 and paces every frame,
the audio sync, and the CD delivery deadlines against a 60 Hz field rate. A
50 Hz PAL console is not a target: it would need the whole timing model
re-derived, not a different security code.

H40 is the only display mode, and every profile here uses it. H32's wider dots
make the dither this codec relies on read as coarse texture rather than tone,
and its narrower VBlank transfer budget forces a lower cold cap, so the smaller
tile grid it needs is more than cancelled by the fewer tiles it can deliver.
One raster also keeps a mode branch out of the player, the encoder, and the
analysis renderer. See [`REMOVED.md`](REMOVED.md) for what an H32
reimplementation would need.

See [`CONFIG.md`](CONFIG.md) for the complete schema and limits.

## Simulation pipeline

`tools/sim.py` uses six stages to cover source decoding, palette training,
future-demand prediction, decisions inside physical limits, and complete
schedule verification.

```text
Extract -> Palette -> Quantize -> Forecast -> Decide -> Finalize
```

[`ENCODE.md`](ENCODE.md) defines each stage's responsibility, inputs, outputs,
and current measured time. Disc packing follows simulation; optional analysis
rendering is a separate step.

## Analysis

The optional 1920x1080 analysis video shows decoded Sega CD output, source,
per-cell categories, audio, physical delivery, pattern supplies, DMA, and
whole-movie timelines; a movie with an adopted scroll window also shows the
hardware-scroll indicator and the Scrl category. Frame 0 is omitted from
timed-work values and graph maxima.

The authoritative panel, meter, category, timeline, audio-window, and TSV
specifications live beside their implementation in `tools/layout_preview.py`,
`tools/analysis_style.py`, and `tools/render_analysis.py`. [`HUD.md`](HUD.md)
defines the values-only hardware/emulator DEBUG HUD.

## Documentation

- [`README.md`](README.md): project overview, design principles, setup, build,
  recording, and repository entry point.
- [`ENCODE.md`](ENCODE.md): the six simulation stages, their inputs and
  outputs, and a versioned full-encode timing example.
- [`CONFIG.md`](CONFIG.md): profile schema, encoder settings, throttles,
  capacities, physical limits, and DEBUG gate thresholds.
- [`MOVIE.md`](MOVIE.md): the exact `HEADER.DAT` and `BODY.DAT`
  on-disc binary format.
- [`BUEFFERING.md`](BUEFFERING.md): PrgBuf, WordBuf0, WordBuf1, and DicBuf
  assignment plus whole-movie quality planning.
- [`PLAYER.md`](PLAYER.md): Main/Sub player memory maps with named ranges,
  unallocated space, the startup sequence, and the per-frame CPU handoff.
- [`HUD.md`](HUD.md): the on-screen DEBUG HUD fields, units, limits, rendering,
  OCR, and upload gate.
- [`ADPCM.md`](ADPCM.md): the 22.05 kHz mono IMA ADPCM format, Sub-CPU decoder,
  buffering, and audio qualification.
- [`BUDGETS.md`](BUDGETS.md): first-order tile, DMA, CD, control, and audio
  budgets for planning a profile.
- [`REMOVED.md`](REMOVED.md): implementation notes for absent features that
  may support a clean reimplementation.
- [`AGENTS.md`](AGENTS.md): repository maintenance, terminology,
  documentation, validation, recording, and attribution rules.
- [`CLAUDE.md`](CLAUDE.md): compatibility entry point that delegates
  repository guidance to `AGENTS.md`.

## Implementation

- `tools/sim.py`: offline encoder. It writes the frozen decision log,
  `buffer_remaining.npz`, analysis data, and the completed artifact marker.
- `tools/pack_stream.py`: verifies decisions and writes `HEADER.DAT`,
  `BODY.DAT`, off-disc `MOVIE.DAT`, and `palettes.bin`.
- `tools/render_analysis.py`: materializes analysis PNGs, TSV, and video from a
  completed sim result.
- `tools/parallel_run.py`: runs independent profile pipelines concurrently
  through verified disc, lossless recording, and the local HUD gate.
- `tools/layout_preview.py`: shared analysis layout and graph rendering.
- `tools/physical_budget.py`: per-frame control/Prg ceilings and prefix ledger.
- `tools/stream_schedule.py`: exact BODY routing and physical slot schedule.
- `boot/movieplay_sp.s`: Sub-CPU disc, PrgBuf, Word-RAM, ADPCM, and handoff
  runtime.
- `boot/movieplay_ip.s`: Main-CPU VRAM, CRAM, name-table, DMA, and DEBUG HUD
  runtime.

Completed sim artifacts are reusable only when source bytes, effective
settings, and the output-affecting encoder fingerprint match. Sim work and
all generated media, including native lossless emulator captures, use direct
managed tmpfs paths. Per-frame codec timeline and playback HUD TSVs plus their
gate/layout/Gist metadata remain under `logs/`, with encoder and player
versions in every TSV filename.

Heavy stages share CPU, GPU, and emulator tokens. Different profile stems may
overlap, while the same stem is rejected immediately. Xvfb displays, RetroArch
system directories, build intermediates, and tmpfs leases are isolated per
run.

## Build targets

| Target | Purpose |
|---|---|
| `movieplay` / `disc` | Codec player disc. |
| `cdcbench` | Continuous and restarted CD-read measurement. |
| `dmabench` | Maximum VRAM DMA per VBlank. |
| `cpuvrambench` | CPU-to-VRAM data-port write throughput during VBlank. |
| `fontbench` | Gate-array font bit vs CPU LUT 1bpp-to-4bpp expansion benchmark. |
| `still256` | Static display bring-up. |
| `streamtest` | Minimal continuous stream test. |
| `pcmtest` | RF5C164 register and wave-RAM test. |
| `adpcmtest` | ADPCM decode and PCM playback test. |
| `test1m` | 1M/1M Word-RAM swap test. |
| `prgtest` | PRG-RAM and streaming interaction test. |
| `asictest` / `upscaletest` | Graphics ASIC and CPU-upscale experiments. |

## Workstation setup

Ubuntu host packages:

```sh
sudo apt update
sudo apt install \
  ffmpeg fonts-ipafont-gothic genisoimage imagemagick \
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
make check-tools CONFIG=profiles/PROFILE.toml
```

The Japanese Mega-CD BIOS is user-supplied and git-ignored:

```sh
test -f original/jp_mcd2_9212.bin
```

Build the managed Genesis Plus GX diagnostic core once:

```sh
harness/gpgx_logvdp/build.sh
harness/gpgx_logvdp/build.sh --check
```

The recording harness defaults to the pinned `LOGVDP` core at
`vendor/gpgx-logvdp/genesis_plus_gx_logvdp_libretro.so`. Generated source,
binary, build log, and manifest stay git-ignored below that directory. There is
no fallback to a distribution-installed core. `CORE` remains an explicit A/B
override; `BIOS_IMAGE` and `SYSTEM_DIR` override the other host-specific
layouts. Normally the harness copies the BIOS into a private per-run system
directory. The normal `retroarch_<tag>.log` retains the DMA trace and unexpected
core errors. The complete upstream trace is kept beside it as
`gpgx_logvdp_<tag>.log.gz`.

## Build

Run a full encode and DEBUG disc build:

```sh
tools/python.sh --gpu tools/sim.py profiles/PROFILE.toml
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
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
`tmp/PROFILE/`. `HEADER.DAT` contains static boot state, boot VRAM prefetch,
and the PrgBuf prebuffer. `BODY.DAT` begins with an untimed audio/frame-0 arm,
then carries the continuously read timed frame-1+ slots.

Run every prepared profile through the protected local pipeline, even when
only one profile is being processed:

```sh
tools/python.sh tools/parallel_run.py --jobs 1 --through hud \
  profiles/PROFILE.toml
```

Pass multiple profiles together when one invocation owns the batch:

```sh
tools/python.sh tools/parallel_run.py --jobs 2 --through hud \
  profiles/PROFILE_A.toml profiles/PROFILE_B.toml
```

Independent invocations use the same cross-process locks, so separate sessions
need no shared job list. Use `--sequential` for an A/B timing or determinism
baseline. Public timeline, Gist, and upload stages remain interactive.

## Disc images for distribution

`SECURITY_REGION` selects the release region. It picks the security code the
console validates, the disc-header fields that name the region, and the disc's
own name; Japan keeps the unsuffixed paths every other tool already uses.

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=0
make disc CONFIG=profiles/PROFILE.toml DEBUG=0 SECURITY_REGION=us
```

```text
out/PROFILE_release.iso     + .cue   Japan
out/PROFILE_us_release.iso  + .cue   North America
```

A region is a boot-area difference and nothing else: `HEADER.DAT` and
`BODY.DAT` are byte-identical across regions, so both discs play the same
encode. Regions of one profile share an output-stem lock, so build them one
after another.

Package and publish the discs. `--config` is repeatable, and every profile
named goes on one release:

```sh
tools/python.sh tools/region_release.py build \
  --config profiles/A.toml --config profiles/B.toml
tools/python.sh harness/regions/verify_release.py out/releases/*.zip
tools/python.sh tools/region_release.py publish \
  --config profiles/A.toml --config profiles/B.toml \
  --zip out/releases/A_MEGA-CD_JP_DATE.eN.pM.zip \
  --zip out/releases/A_SEGA-CD_US_DATE.eN.pM.zip \
  --zip out/releases/B_MEGA-CD_JP_DATE.eN.pM.zip \
  --zip out/releases/B_SEGA-CD_US_DATE.eN.pM.zip
```

`build` writes `out/releases/<profile>_<CONSOLE>_<REGION>_<date>.e<N>.p<M>.zip`,
each holding that region's `.iso`, its `.cue`, and a README naming the region,
the encode, the source, and how to burn it. The console is named because Sega
sold the same machine as the Mega-CD and as the Sega CD: `MEGA-CD` for Japan,
`SEGA-CD` for North America. `publish` creates one draft GitHub
release tagged `disc-<date>.e<N>.p<M>` with every zip attached and one section
per title, and replaces an existing asset only when `--clobber` is passed. The
release body is English; the README inside each zip carries the same
information in English and Japanese.
[`harness/regions/README.md`](harness/regions/README.md) states what the
verification proves and what it does not.

## Recording

Use emulator-synchronized A/V:

```sh
tools/record_movie.sh --config profiles/PROFILE.toml \
  --seconds 180 --tag STEM_emu
```

The recorder defaults to fixed-Replay, faster-than-realtime, native-size
FFV1/FLAC; the bounded lossless MKV is the artifact. Add `--preview` (with
optional `--out NAME`) for an opt-in lossy H.264 verification preview.
`--realtime-lossless`
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
profiles/    per-source TOML profiles
harness/     reproducible diagnostics and their local documentation
tools/       encoder, packer, analysis, build, and recording tools
vendor/      third-party references and ignored local tool builds
```

Generated output and copyrighted source media are not part of the public
repository.

<a id="jp"></a>

# Sega CD Constraint-Aware Video Codec — SEGA-CD / Genesis FMV codec

Sega CD Constraint-Aware Video CodecはSega CD hardware専用に設計した
full-motion-video codecです。Genesis VDPのtile/CRAM model、連続CD 1x delivery、
Sub-CPU PRG RAM、1M/1M Word RAM、RF5C164 PCM chipを直接対象にします。同じstreamを
実機とGenesis Plus GXで再生します。

ディスク上のstreamは明示的なversionを持ちます。repository内のgeneric filenameに
より、実装pathは表示上のcodec名から独立しています。

## 中心となる考え方

このprojectの中心は、**SEGA-CDとGenesisに分割されたretro architectureの制約内で、
FMVの画質を最大化すること**です。CD 1x、分離したmemory、複数CPU、VBlank、CRAM
paletteを別々の問題にせず、movie全体で1つのresource allocationとして扱います。

Encoderは、どのframeへqualityを使うか、patternをどのmemory domainに置くか、Main/Subの
どちらがいつ運ぶかを、後工程で物理上限を破れない形で先に決めます。8x8 resident pattern
の再利用はそのための有効な手段の1つです。Exact、Near、Flbk再利用によってCD deliveryと
VBlank transferを節約し、その余裕を新しいpatternが必要なframeへ回します。

## Hardwareに合わせた設計

- **分割memoryを使い切る。** PRG-RAMのPrgBufは将来patternを連続streamingします。
  2つのphysical Word-RAM bankには、frame parity別のWordBuf0 / WordBuf1 ringを
  起動時にpreloadし、配送に余裕がある場所ではstream中に先頭BODY payload sectorで
  補充します。Main RAMのDicBufは、頻出exact patternを512-entry dictionaryとして
  全編で再利用します。
- **複数CPUを協調させる。** Sub CPUはCD sectorのroute、PrgBuf、ADPCM decode、次frameの
  Word RAM展開を担当します。Main CPUはcurrent frameの解決済みrunを消費し、VRAM
  transfer、CRAM update、単一name tableへの静的trim済みband DMAを担当します。
  採用scroll window中は代わりに64列rolling plane bandをstageし、同じVBlank内で
  Plane A/Bのscroll値も更新します。
  1M/1M Word RAM handoffで両者をframe単位に接続し、
  pending handoffを将来dataの先読みより優先します。
- **VRAM residentを再利用する。** tile 1〜1,743を1つのpersistent poolとして
  使います（固定HUD font `0xDA00`の直前まで）。Exact residentはname-table entryだけ、
  Nearは見た目が近いresident、Flbkは
  現在表示を改善するresidentを参照します。新しい32-byte patternは必要なときだけ
  cold loadします。
- **画面全体はhardwareで動かす。** Encoderは持続する単一軸のcamera scrollを自動検出し、
  固定gridより実測で安くなるwindowだけを採用してscroll controlをstreamします。
  Playerは64x32 Plane Aを絶対HScroll/VScroll値で環状に使うため、scrollが運ぶcellは
  patternもname-table更新も一切不要です（Scrl）。
- **CRAM制約を時分割する。** VDPの4 palette lines、各15 usable coloursの範囲で60色を
  学習します。安全なtransitionでmovieをsegment化し、全segment paletteをMain RAMへ
  preloadして、再生中は小さな参照だけで時限切替します。また、黒の間で
  brightnessが上下する静止shotを自動検出し、各shotのindexed imageを固定して、
  正確なinline CRAM総入替で明るさの段階を再現します。sourceのtime range設定はありません。
- **Movie後方からqualityを配分する。** dry runで将来のexact demandとMiss-risk demandを
  予測し、重いframeのためのquality allowanceとboot-preload creditを逆算します。
  control、run descriptor、CRAM switch、audio、Prg payload、padを同じphysical-sector
  planへ入れ、quality fundingと物理pattern sourceを分離します。
- **VBlankとaudioを専用pathへ収める。** Screen geometryとcold workをMain-CPU
  transfer budget内に制限します。Sub CPU上の自前IMA ADPCM decoderが22.05 kHz mono
  audioをRF5C164 sampleへ変換し、映像用のCD帯域を確保します。

## Sega CD limit内で設定できるもの

sourceごとにstrict TOML profileを使います。

- **Display:** H40 320x224 aperture内のtile-aligned output geometryと、
  aspect-awareなpad/crop。
- **Frame rate:** source native rate。24 fpsは認定済みの2/3 VBlank反復cadenceを
  使い、実効24000/1001 fpsで再生。
- **Audio:** checkpointed 22.05 kHz mono IMA ADPCM。
- **Cold cap:** source profileごとの必須値。変更とqualificationもprofile経由。
- **Palette algorithm:** `stl4` または `mosaic-gm`。
- **Analysis canvas:** optionalで、encoded streamは変えない。
- **Disc region:** 日本または北米。どちらもNTSC。

**ディスクはNTSC専用です。** playerはH40 V28で表示し、frame進行・音声同期・CDの配送
期限をすべて60 Hzのfield rateに合わせています。50 HzのPAL実機は対象外で、必要なのは
別のsecurity codeではなくtiming model全体の再導出です。

display modeはH40だけで、ここにある全profileがH40です。H32はドットが大きいため、
このcodecが前提とするditherが階調ではなく粗いテクスチャとして見えます。さらに
VBlankのtransfer budgetが狭くcold capも下がるので、必要なtile gridが小さくなっても、
1コマで転送できるtile数の減少がそれを上回ります。rasterを1つにしておくことで、
player・encoder・analysis rendererからmode分岐も無くせます。H32を再実装する場合に
必要なものは [`REMOVED.md`](REMOVED.md) を参照してください。

schemaとlimitの全体は [`CONFIG.md`](CONFIG.md) を参照してください。

## Simulation pipeline

`tools/sim.py` は6つのstageで、source decodeからpalette学習、将来予測、物理制約内の
decision確定、全schedule検証までを実行します。

```text
Extract -> Palette -> Quantize -> Forecast -> Decide -> Finalize
```

各stageの責務、入出力、現在の実測時間は [`ENCODE.md`](ENCODE.md) にまとめています。
Disc packはsimulation後、optional analysis renderは別工程です。

## Analysis

optional 1920x1080 analysis videoはdecoded Sega CD output、source、cell別category、
audio、物理delivery、pattern供給、DMA、movie全体timelineを表示します。採用scroll
windowがあるmovieではhardware-scroll indicatorとScrl categoryも表示します。frame 0は
timed-work valueとgraph maximumから除外します。

全panel、meter、category、timeline、audio window、TSV fieldの正は、実装と同じ
`tools/layout_preview.py`、`tools/analysis_style.py`、
`tools/render_analysis.py`にあります。実機/emulatorのvalues-only DEBUG HUDは
[`HUD.md`](HUD.md) にあります。

## Documentation

- [`README.md`](README.md): project概要、設計方針、setup、build、recording、
  repositoryの入口。
- [`ENCODE.md`](ENCODE.md): simulationの6 stage、各stageの入出力、
  version付き全編encode実測例。
- [`CONFIG.md`](CONFIG.md): profile schema、encoder設定、throttle、容量、
  物理limit、DEBUG gate threshold。
- [`MOVIE.md`](MOVIE.md): 正確なon-disc `HEADER.DAT` / `BODY.DAT`
  binary format。
- [`BUEFFERING.md`](BUEFFERING.md): PrgBuf、WordBuf0、WordBuf1、DicBufの
  割り当てとmovie全体quality planning。
- [`PLAYER.md`](PLAYER.md): 名前付きrangeによるMain/Sub playerのmemory map、
  未割当領域、startup sequence、frameごとのCPU handoff。
- [`HUD.md`](HUD.md): 画面上のDEBUG HUD field、unit、limit、rendering、OCR、
  upload gate。
- [`ADPCM.md`](ADPCM.md): 22.05 kHz mono IMA ADPCM format、Sub-CPU decoder、
  buffering、audio qualification。
- [`BUDGETS.md`](BUDGETS.md): profile計画に使うtile、DMA、CD、control、audioの
  一次budget。
- [`REMOVED.md`](REMOVED.md): cleanな再実装の参考になる、現在存在しないfeatureの
  実装情報。
- [`AGENTS.md`](AGENTS.md): repository maintenance、用語、documentation、
  validation、recording、attribution rule。
- [`CLAUDE.md`](CLAUDE.md): repository guidanceを `AGENTS.md` へ委譲する
  compatibility entry point。

## Implementation

- `tools/sim.py`: offline encoder。固定済みdecision log、`buffer_remaining.npz`、
  analysis data、completed artifact markerを書きます。
- `tools/pack_stream.py`: decisionを検証し、`HEADER.DAT`、`BODY.DAT`、ディスク外の
  `MOVIE.DAT`、`palettes.bin` を書きます。
- `tools/render_analysis.py`: completed sim resultからanalysis PNG、TSV、videoを生成します。
- `tools/parallel_run.py`: 独立profileをverified disc、lossless recording、local HUD
  gateまで並列実行します。
- `tools/layout_preview.py`: 共通analysis layoutとgraph rendering。
- `tools/physical_budget.py`: frame別control/Prg ceilingとprefix ledger。
- `tools/stream_schedule.py`: 正確なBODY routingと物理slot schedule。
- `boot/movieplay_sp.s`: Sub-CPUのdisc、PrgBuf、Word-RAM、ADPCM、handoff runtime。
- `boot/movieplay_ip.s`: Main-CPUのVRAM、CRAM、name table、DMA、DEBUG HUD runtime。

completed sim artifactはsource byte、effective setting、outputに影響するencoder fingerprintが
一致するときだけ再利用します。sim workとnative lossless emulator captureを含む全生成mediaは
managed tmpfs実体pathを直接使います。Frame別codec timeline TSVとplayback HUD TSV、
およびgate/layout/Gist metadataは`logs/`へ保持し、TSV filenameにはencoder/player
versionを入れます。

heavy stageはCPU、GPU、emulator tokenを共有します。異なるprofile stemは重ねられますが、
同じstemは即時拒否します。Xvfb display、RetroArch system directory、
build intermediate、tmpfs leaseはrunごとに分離します。

## Build target

| Target | 用途 |
|---|---|
| `movieplay` / `disc` | Codec player disc。 |
| `cdcbench` | continuous/restarted CD read計測。 |
| `dmabench` | VBlank当たり最大VRAM DMA。 |
| `cpuvrambench` | VBlank中のCPU→VRAM data port書き込みthroughput実測。 |
| `fontbench` | gate-array Font bit vs CPU LUTの1bpp→4bpp展開benchmark。 |
| `still256` | static display bring-up。 |
| `streamtest` | minimal continuous stream test。 |
| `pcmtest` | RF5C164 register/wave-RAM test。 |
| `adpcmtest` | ADPCM decodeとPCM playback test。 |
| `test1m` | 1M/1M Word-RAM swap test。 |
| `prgtest` | PRG-RAMとstreaming interaction test。 |
| `asictest` / `upscaletest` | graphics ASICとCPU upscale experiment。 |

## Workstation setup

Ubuntu host package:

```sh
sudo apt update
sudo apt install \
  ffmpeg fonts-ipafont-gothic genisoimage imagemagick \
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
make check-tools CONFIG=profiles/PROFILE.toml
```

Japanese Mega-CD BIOSはuser suppliedかつgit-ignoredです。

```sh
test -f original/jp_mcd2_9212.bin
```

managed Genesis Plus GX diagnostic coreを一度buildします。

```sh
harness/gpgx_logvdp/build.sh
harness/gpgx_logvdp/build.sh --check
```

recording harnessのdefaultは、固定された
`vendor/gpgx-logvdp/genesis_plus_gx_logvdp_libretro.so` の`LOGVDP` coreです。
generated source、binary、build log、manifestはこのdirectory以下でgit-ignoredです。
distribution-installed coreへのfallbackはありません。`CORE`は明示的なA/B overrideとして
残し、`BIOS_IMAGE`と`SYSTEM_DIR`でその他のhost固有layoutを上書きします。通常はharnessが
BIOSをrunごとのprivate system directoryへcopyします。通常の
`retroarch_<tag>.log`にはDMA traceと想定外のcore errorを残し、上流trace全体は隣の
`gpgx_logvdp_<tag>.log.gz`へ保存します。

## Build

full encodeとDEBUG disc build:

```sh
tools/python.sh --gpu tools/sim.py profiles/PROFILE.toml
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
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
`HEADER.DAT` はstatic boot state、boot VRAM prefetch、PrgBuf prebufferを持ちます。
`BODY.DAT` はuntimedなaudio/frame-0 armから始まり、その後に連続readするtimed
frame-1+ slotを持ちます。

準備済みprofileが1つだけでも、保護されたlocal pipelineを使います。

```sh
tools/python.sh tools/parallel_run.py --jobs 1 --through hud \
  profiles/PROFILE.toml
```

1つのinvocationが複数profileを扱う場合はまとめて渡します。

```sh
tools/python.sh tools/parallel_run.py --jobs 2 --through hud \
  profiles/PROFILE_A.toml profiles/PROFILE_B.toml
```

独立したinvocationも同じprocess間lockを使うため、別session間でjob listを共有する必要は
ありません。A/B timingまたはdeterminism baselineには `--sequential` を使います。
public timeline、Gist、upload stageは対話的に実行します。

## 配布用disc image

`SECURITY_REGION` がrelease regionを選びます。本体が検証するsecurity code、region名を
書くdisc headerのfield、そしてdisc自身の名前がこれで決まります。日本は他のtoolが既に
使っているsuffix無しのpathをそのまま使います。

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=0
make disc CONFIG=profiles/PROFILE.toml DEBUG=0 SECURITY_REGION=us
```

```text
out/PROFILE_release.iso     + .cue   日本
out/PROFILE_us_release.iso  + .cue   北米
```

regionの差はboot領域だけです。`HEADER.DAT` と `BODY.DAT` はregion間でbyte一致するので、
どちらのdiscも同じencodeを再生します。同一profileのregionはoutput stem lockを共有する
ため、直列にbuildします。

discをpackageして公開します。`--config` は繰り返し渡せて、渡したprofileはすべて
1つのreleaseに載ります。

```sh
tools/python.sh tools/region_release.py build \
  --config profiles/A.toml --config profiles/B.toml
tools/python.sh harness/regions/verify_release.py out/releases/*.zip
tools/python.sh tools/region_release.py publish \
  --config profiles/A.toml --config profiles/B.toml \
  --zip out/releases/A_MEGA-CD_JP_DATE.eN.pM.zip \
  --zip out/releases/A_SEGA-CD_US_DATE.eN.pM.zip \
  --zip out/releases/B_MEGA-CD_JP_DATE.eN.pM.zip \
  --zip out/releases/B_SEGA-CD_US_DATE.eN.pM.zip
```

`build` は `out/releases/<profile>_<CONSOLE>_<REGION>_<date>.e<N>.p<M>.zip` を書きます。
各zipにはそのregionの `.iso`、`.cue`、そしてregion・encode・出典・焼き方を書いたREADMEが
入ります。同じ機械がメガCDとSega CDの2つの名前で売られたので、ファイル名にconsole名を
入れます。日本は `MEGA-CD`、北米は `SEGA-CD` です。
`publish` は `disc-<date>.e<N>.p<M>` をtagとする draft GitHub releaseを1つ作り、すべての
zipを添付して、titleごとのsectionを書きます。既存のassetを置き換えるのは `--clobber` を
渡したときだけです。release本文は英語で、同じ内容の英日はzip内のREADMEにあります。
検証が何を証明し、何を証明しないかは
[`harness/regions/README.md`](harness/regions/README.md) にあります。

## Recording

emulator-synchronized A/Vを使います。

```sh
tools/record_movie.sh --config profiles/PROFILE.toml \
  --seconds 180 --tag STEM_emu
```

recorderのdefaultはfixed-Replay、faster-than-realtime、native-size FFV1/FLACです。
成果物はbounded lossless MKVです。lossy H.264 verification previewはopt-inで、
`--preview`（必要なら`--out NAME`も）を付けたときだけ作ります。
`--realtime-lossless` はpaced FFV1/FLAC diagnostic
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
profiles/    per-source TOML profiles
harness/     reproducible diagnostics and their local documentation
tools/       encoder, packer, analysis, build, and recording tools
vendor/      third-party references and ignored local tool builds
```

generated outputとcopyrighted source mediaはpublic repositoryに含めません。
