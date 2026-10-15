# SEGA-CD FMV Encoder for CAVC

A browser-only SPA with source/crop and encoded-output previews side by side.
Generate CAVC runs the original Python codec in WebAssembly. MOSAIC-GM palette
training, Bayer dither, Near/Flbk decisions, quality accounting, PrgBuf,
WordBuf0/WordBuf1, DicBuf, boot/raw VRAM prefetch, scroll, delivery planning and
HEADER/BODY packing use the project implementations. The original encoder
chooses allocations and safe scheduling fallbacks for each input.
The desktop workbench fits the viewport with a one-line header, a flexible Source
beside a fixed 4:3 Output display box, an integrated playback/trim timeline,
a compact progress strip and the expanded Activity log. Settings scroll inside their pane while Generate
stays visible. Narrow mobile screens use a vertically scrolling layout.

## Input and settings

Select a local H.264/AAC-LC MP4, supported WebM or MOV. Audio comes from the video.
The app starts with no video selected. Source fps is detected after selection;
output fps, crop, source pixel aspect, raster, fit, region and cold cap are
selectable. Auto source aspect currently uses a 1:1 fallback; custom ratios are
available. Output uses the H40 320×224 aperture with 32:35 pixel aspect. Cold cap
is derived from existing geometry/fps profiles, with manual override and reset.
The default raster is 320×224. Region defaults to North America for an English
browser language and Japan otherwise, and can be changed manually.

Choose an inclusive, zero-based source frame range using Start/End fields or
the two-handle slider. Editing a bound seeks the source preview. Video and audio
are trimmed to the same source timestamps; output fps determines the number of
encoded frames. Full video restores the complete range, and replacing the input
resets the selection. Normalized comparison archives retain fixed full bounds.
The timeline's independent playhead scrubs source frames; its end handles select
the encode interval. Source preview playback stops at the selected end. Encoded
H40 geometry and 32:35 pixel aspect are preserved inside the 4:3 display box.

FFmpeg Wasm normalizes frames with Lanczos resize and converts audio to 22.05 kHz
mono signed-16 PCM inside the encoder worker. It applies source crop/aspect,
padding or center crop, and the selected output cadence. Audio is resampled from
the head before trimming, then padded to the generated video duration. Arbitrary
FFmpeg audio/image filters are not exposed. `.cavc-input.zip` also accepts
shared offline-normalized RGB/PCM and fixed profile settings for comparisons.
All processing happens in browser memory; source media is not uploaded.

The GUI receives actual palette-feature, MOSAIC-GM candidate, quantization,
demand/prefetch, decision, replay and MP4 progress. Long operations without a
known total show an indeterminate stage bar and operation name. Overall progress
tracks pipeline milestones rather than predicted processing time. The expanded
Activity log retains the original encoder's detailed messages.
The browser tab title includes overall percent while processing. The lower-right
summary shows the codec timeline first, compact wrapping palette cards with all
four color banks, scroll/fade interval tracks, and chronological event rows. Palettes and effects are marked Planned
until packed-stream verification succeeds. Events link back to the matching
source position. Palette and event lists scroll inside the lower dock. On large screens, spare
height expands the log and summary; the trim timeline stays directly below the
preview controls.

## Playback and downloads

Playback reconstructs the actual CAVC decisions with the canonical display
portion of `tools/render_analysis.py`, including retained patterns, active CRAM
and scrolling. Audio comes from the sim's checkpointed IMA ADPCM/RF5C164 playback
model. A nearest-neighbour, square-pixel 1024×784 H.264/AAC-LC MP4 presents the H40
aperture. It is the sim's ideal display, with no analysis overlay or BIOS startup.
AAC uses an exact 22.05 kHz mono AAC-LC configuration and a Wasm encoder fallback.
The ZIP includes the original reconstructed PCM WAV before AAC compression.

Download ZIP contains a bootable regional `.iso`/`.cue` pair, `preview.mp4`,
`playback.wav`, `HEADER.DAT`, `BODY.DAT`, `MOVIE.DAT`, settings/hashes,
`stage-sha256.tsv`, `playback-frames.tsv`, `analysis-timeline.tsv` and
`encode-summary.json`. The ISO embeds the original player,
assembled and linked in browser-side GNU m68k Binutils for the generated stream's
contract. Files are stored in a single MODE1/2048 ISO9660 track.

Review encoded output with the in-app playback MP4. To use a separate emulator
or real hardware, download the ISO/CUE pair.
Stages, frame progress, elapsed time, logs and cancellation remain available
throughout processing. Changing settings invalidates generated results.

## Build

Run `npm install`, then `npm run dev`; build static files with `npm run build`.
The app is in `dist/client/`; Sites server/hosting artifacts are also generated.
The first build prepares Emscripten 6.0.12 and GNU Binutils 2.40 if their local
cache is missing. It needs a native compiler/build environment, Python and the
project's locked NumPy 2.3.5 environment. Subsequent builds reuse compiled tools.
Pyodide 314.0.7, NumPy 2.4.6, Pillow 12.2.0, m68k tools and encoder/player code
are self-hosted assets. GNU Binutils source, its build script and GPL license
are available under `m68k-runtime/`. Generated libraries live in ignored paths.
FFmpeg core 0.12.10 (FFmpeg 5.1.4) is self-hosted under `ffmpeg-runtime/`, alongside
source archives, licenses and pinned build/dependency source references. Its
30.7 MiB Wasm is split into four checksum-verified chunks for the Pages asset
limit. On page opening, a service worker downloads and SHA-256-verifies the
complete encoding runtime (about 57 MiB), including Python/packages, FFmpeg,
AAC fallback, player sources, m68k tools and app/worker bundles. Generate remains
disabled until **Offline ready**. Activity log shows each download, verification,
cached asset and failure; interrupted preparation can be retried. Identical
assets are shared across releases in a content-addressed browser cache.
After readiness, encoding, playback MP4, ISO/CUE and ZIP creation work without
a network connection, including after an offline page reload. Keep this page's
site data; clearing browser storage removes the offline files. Dev mode uses
the Vite server; use a production build on HTTPS or localhost for offline use.
WORKERFS reads the selected Blob without copying the complete source into the
FFmpeg heap; an image pipe transfers each completed PNG directly into Pyodide.
Cancel terminates the owning worker, including FFmpeg.

The original project code is licensed under MIT; see the repository
root `LICENSE`. Third-party code and assets retain their respective terms.
The footer's Licenses modal loads installed-version copyright/license notices
and component-specific source links on demand. `npm run prepare:licenses`
regenerates `public/licenses/`; dev and build preparation run it automatically.
The notices are not a complete-source compliance audit: FFmpeg's bundled
dependency sources and the AAC fallback's corresponding-source/rebuild materials
still require verification. A link to this project's GitHub repository covers
only the sources actually present there.

## Verification scope

`harness/equivalence/README.md` documents normalized-input reference checks.
The Sonic Jam profile's half and complete sources have passed HEADER/BODY/MOVIE
byte comparison between native Python and Python/Wasm. The FFmpeg preprocessing
harness compares every RGB pixel and PCM sample against native FFmpeg using
the recorded filter and command options. Native `-cpuflags 0` disables
CPU-specific optimized routines whose rounding can differ from Wasm. The
qualified synthetic cases include 60/59.94 to 30 fps, trimming, padding, center
crop, custom crop/aspect, silence, stereo audio and a complete one-minute source. They pass byte
comparison against FFmpeg 8.0.1 with that option; default native FFmpeg and
arbitrary media/version pairs are not qualified. CAVC output and lossy MP4
container bytes are separate comparisons.
RGB replay hashes and the pre-AAC reconstructed WAV expose playback fidelity.

`npm run test:ui` checks the SPA controls, cancel/retry, playback, ZIP and viewport.
`node scripts/verify-encode.mjs` performs actual browser encoding, playback and
ISO/CUE/stream extraction checks. `WEBENC_INPUT`, `WEBENC_URL`,
`WEBENC_TEST_DIMENSIONS`, `WEBENC_TEST_FPS`, `WEBENC_TEST_SAR`, `WEBENC_TEST_CAP`,
`WEBENC_TEST_TIMEOUT` and `WEBENC_TEST_OUTPUT` select its input, settings and paths.
`WEBENC_TEST_START_FRAME` and `WEBENC_TEST_END_FRAME` exercise trimmed encoding.
`node scripts/verify-frame-range.mjs` checks language defaults, numeric and slider
controls, mobile layout, exact selected frame pixels and matching trimmed PCM.
`npm run test:sites`, `test:audio` and `test:cold-cap` cover static hosting,
audio configuration and cap selection.
`WEBENC_TEST_LONG=1 node harness/ffmpeg/verify.mjs` runs preprocessing comparisons,
including all 1,440 frames of a one-minute source; set `WEBENC_URL` to a local
development server and `WEBENC_TEST_OUTPUT` to a managed tmpfs fixture directory.
Diagnostic hashes and comparison receipts are retained under `logs/`.

A narrowly bounded diagnostic adapter handles unused whole-sector padding when
the entire Prg stream fits in the boot prebuffer. It changes no encoding choices
or physical schedule; existing stream checks remain active.
A separate pack-validation adapter distinguishes mandatory scroll lists from
optional normal-frame list optimizations. Scroll controls retain their required
position/list format regardless of nominal bitmap speed; optional lists must
still be faster. Frozen costs and every delivery/buffer check remain active.
Error banners show the concise cause, with the full traceback in Activity log.

User-selected video files automatically choose matching picture dimensions,
or the closest visible aspect ratio after H40 pixel aspect correction. Manual
selection remains available. The app starts with no video selected and picture dimensions at 320x224. Normal
choices exclude 256x192; 288x200 appears only for a 288x200 source. A compact
encoding stage row marks completed and current work above the progress bars.

Download ZIP sits to the right of progress and spans the progress area's height.
The button visibly lists ISO · CUE · MP4, is disabled during processing, and
gains a warm accent when the completed package is available.

Source pixel aspect choices are Auto, 1:1, 32:35 (H40), 8:7 (H32 material),
and Custom. Auto currently uses 1:1 and does not detect the source's pixel
aspect. These presets affect source framing and normalization; output stays H40.

Ordinary video output supports 15, 24 and 30 fps. Auto chooses the closest
supported output rate; 60 and 59.94 fps sources use 30 fps. FFmpeg's fps filter
selects frames for the output cadence, preserving audio speed and rounding
duration to the output frame interval. Source fps remains
separate for source-frame trimming.

The empty Source preview supports click-to-browse and video drag-and-drop.
Picture dimensions are ordered by descending pixel count; MOSAIC-GM is fixed.
During frame-specific processing, Source follows the matching original frame
within the selected interval. Once packed verification produces confirmed
canonical replay frames, Output switches to Playback and displays those stills
with their frame numbers. Completed output uses MP4 video controls and the
reconstructed sim audio.

The codec timeline uses the canonical analysis TSV calculations and category
colors: Req, physical Supply (Wrd then Prg), RUN, R2V, DIC and useful BODY Band
as a percentage of each physical slot. The yellow Req guide is the cold cap.
Fit mode averages drawing columns to show the complete movie; Detail preserves
each frame at two pixels. Hover reads exact frame values, and a click seeks
the matching source frame. The timeline appears after stream verification;
analysis-timeline.tsv in the ZIP retains every canonical row and column.

Source also follows the actual frame being read during palette feature
extraction. A browser alert announces successful completion once the package
and playback are ready. The title badge reads "simplified ver".

## Cloudflare Pages

Production: https://segacd-fmv-cavc-encoder.akiyan.com/

Install the Cloudflare CLI globally with `npm install --global cf`, then
authenticate with `cf auth login`. Run `npm run deploy:pages` from webenc.
Target project, production branch and domain are in cloudflare-pages.json.
The deploy script resolves the zone's account, uploads static assets and
creates the production deployment through `cf pages deployments create`.
The beta CLI does not implement the static Pages upload command, so file
transfer uses the official Pages assets API with the existing cf default OAuth
session (or CLOUDFLARE_API_TOKEN). Credentials never enter build output or
deployment receipts.

Pages publishes dist/pages, containing the self-hosted browser runtimes and
Binutils source/license, excluding bundled test footage and the development
comparison runner. The deployment uploads _headers for origin isolation,
Wasm/module MIME enforcement and immutable hashed frontend assets.
The custom domain is associated with the Pages project and uses a proxied
CNAME to segacd-fmv-cavc-encoder.pages.dev. Subsequent deployments retain this
domain association.
