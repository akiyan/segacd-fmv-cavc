# Prototype Instructions

This is the browser-only CAVC encoder prototype. Preserve the selected dark
workbench layout with side-by-side source and output previews. Crop is adjusted
on the source with drag handles and source-pixel numeric fields. Pixel aspect
selection belongs to the source (Auto / 1:1 / 32:35 / 8:7 / Custom); output H40 remains 32:35.
Auto currently uses a 1:1 fallback and does not detect source pixel aspect;
state this explicitly rather than suggesting metadata detection is pending.
Preset ratios must reach both preview geometry and encoder metadata.
Output frame rate is selectable. Downloads are a single ZIP package.
Default picture dimensions are 320x224. Default region is North America when
the browser's primary language is English, otherwise Japan; keep manual choice.
Ordinary video inputs support inclusive, zero-based source frame bounds with
numeric fields and a two-handle range slider. Seek the source when a bound is
edited, trim audio to the same source timestamps, reset bounds on replacement,
and preserve the chosen range in download metadata. Normalized comparison
archives retain their fixed full-frame input and show disabled range controls.
Activity log heights are doubled across desktop and compact/mobile layouts.
Browser progress instrumentation is observational: report actual completed
frames, palette candidate/core evaluations and encoder phase boundaries using
structured worker events. Preserve codec results. Display an indeterminate
stage bar and current operation when a percentage is unavailable; never invent
progress by advancing percentages with elapsed time. Overall progress counts
pipeline milestones and is not a time-remaining estimate.
Desktop layout fits a single viewport: one-line header without a tagline,
flexible equal-height Source/Output frames, compact horizontal frame-range
controls, and a compact progress strip with a single-row encoding stage list.
The Output display box is fixed at 4:3; preserve encoded H40 geometry and 32:35
pixel aspect, with contain-fit playback. Allocate its column from available
height and width, and let Source use the remaining width. Source playback and
trim share one timeline: an independent playhead, start/end handles and numeric
frame bounds. Frame steps seek actual source timestamps. Preview playback stops
at the selected end. Keep encoded-output playback separate from source trimming.
During encoding prefix document.title with the overall percent; restore the
normal title on completion, cancellation or error.
Use the lower-right dock for live selected palette sets/color configurations
and hardware scroll/fade intervals. Show Pending until a decision is available,
Planned until packed verification, and Stream verified after successful packing.
Summary extraction observes original arrays only; include encode-summary.json
in the ZIP. Use output frame numbers for effect intervals and map event clicks
back to the selected source interval. Keep the dock at least 140px tall and scroll palette/event lists internally.
On large screens, place the timeline directly below the preview controls;
allocate spare height to the log and summary rather than an empty editor gap.
Keep the expanded log visible. Settings scroll within their own pane when needed
and Generate stays visible. Narrow mobile screens may scroll vertically.
Clearly distinguish framing preview and demonstration progress from real CAVC
encoding. Never put placeholder ISO/CUE files in a downloadable package.
Work only in webenc; other repository changes belong to ongoing work.

Run the local server yourself and open the preview in the browser available to this environment. Do not give the user server-start instructions when you can run it.

Before making substantial visual changes, use the Product Design plugin's `get-context` skill when the visual source is unclear or no longer matches the current goal. When the user gives durable prototype-specific design feedback, preferences, or decisions, record them in `AGENTS.md`.

When implementing from a selected generated mock, treat that image as the source of truth for layout, component anatomy, density, spacing, color, typography, visible content, and hierarchy.

Build app UI in `src/`. Keep `.openai/hosting.json`, `worker/index.js`, `scripts/prepare-sites-build.mjs`, and `tests/sites-worker.test.mjs` intact so the same local prototype can be handed to Sites. Before a Sites handoff, run `npm run build` and `npm run test:sites`; the build must leave `dist/client/index.html`, `dist/server/index.js`, and `dist/.openai/hosting.json`.

Preview ownership: encoded-result review uses an MP4 player inside the encoder
SPA. Do not include browser emulator playback, BIOS inputs or an Open emulator
link. ISO/CUE generation and ZIP downloads remain available.

Audio input is the selected video only. Do not add a separate audio picker or
external-audio playback/sync state. Preview mute controls remain available.

Cold cap is automatic from output geometry/fps and existing profile references.
Keep cadence specs intact, select the lowest matching caps, label conservative
fallbacks as unverified, and allow manual override/reset. A geometry/output-rate
change resets the override. Regenerate the reference at dev/build time.

Fallback cold caps must be calibrated to existing profile caps, tile counts and
display-slot time. Prefer same-fps references; preserve 24fps slot-specific caps.
Do not use arbitrary raster fractions or a fixed 100-load ceiling.

Every video input must run the original CAVC pipeline in Python/WebAssembly.
Do not expose the experimental Rust palette/temporal preview as Generate or
Playback. MOSAIC-GM is the only palette algorithm; Bayer dither, original
Near/Flbk decisions, quality accounting, PrgBuf, WordBuf0/WordBuf1, DicBuf,
boot/raw VRAM prefetch and the complete delivery/packing policy stay enabled.
Let the original encoder decide allocations and choose its safe scheduling
fallbacks; do not lower target geometry/fps/cold cap to make an encode pass.

Playback must be materialized by the canonical display portion of
render_analysis.py on the actual decisions and active CRAM, including scroll.
Use stats.npz's audio_playback_file (the ADPCM/RF5C164 PCM model), never clean
source audio. The playback MP4 uses nearest-neighbour H40 aspect correction.
Downloads must contain real ISO/CUE and HEADER/BODY/MOVIE plus MP4, playback WAV,
settings and stage/replay TSV hashes. Compile the unchanged player for each
stream contract with GNU m68k assembler/linker in WebAssembly. Keep security
code distinct from external BIOS: boot code uses the existing regional security
assets; the app does not supply an emulator BIOS.

Use one-minute traces and actual one-minute A/V inputs for delivery scheduling
verification. The short bundled source is only an immediate interaction sample.
Cover sustained high demand, quiet intervals, abrupt changes and startup, and
check every deadline/buffer balance, not only whole-stream averages.

MP4 preview audio uses explicit AAC-LC (mp4a.40.2), 96 kbps, mono, 22050 Hz.
Probe those exact parameters before selecting native audio encoding. A generic
AAC probe uses different defaults and can incorrectly bypass the Wasm fallback.
Keep fallback priming correction tied to the actual selected encoder.

Normalized-input comparisons must prove native/Wasm equality with independent
palette/quantization/decision calculation; no native video-specific results
are supplied to the browser. Compare every byte of HEADER/BODY/MOVIE, every
canonical RGB replay frame, and the reconstructed PCM WAV. MP4/ZIP container
bytes are distinct from the CAVC stream target. Use the first half of Sonic Jam
OP (1,357 frames / 45.233333 s) for iteration, then verify complete 2,714-frame
processing. Do not call half-only coverage completion of a full-profile goal.

Ordinary source decode/crop/resize, output cadence and 22.05 kHz mono conversion
use self-hosted single-thread FFmpeg Wasm in the encoder Worker. Match the
no-denoise Lanczos geometry in tools/video_geometry.py after the explicit source
crop. FFmpeg fps rounding chooses output frames; 60/59.94 still become 30 fps.
Stream PNGs through a device into Pyodide instead of retaining all frames in
FFmpeg's filesystem. Read source Blobs through WORKERFS. Decode/resample audio
from its head, then trim/pad to the generated frame count. Show real download,
frame and sample progress; cancellation must terminate FFmpeg with its owning
worker. Split the Wasm runtime into checksum-verified assets below 25 MiB for
Pages. Precache all encoding executables, Python packages/adapters, codec/player
data, AAC fallback, app/worker bundles and license notices on page opening.
Require verified completion and a controlling service worker before enabling
Generate. Show real byte progress and per-file download/cache/verification/error
messages in Activity log. After Offline ready, a fresh Worker must encode through
MP4 and ISO/CUE ZIP without network access, including after an offline reload.
Prefix preparation log entries with [current file/total files] and show the same
counter before the Activity log heading while loading. Derive counts from the
actual asset list; include cache reuse and retries, and clear the heading prefix
on completion or failure.
Place offline readiness/download progress and retry controls in the title
header's right-hand area; never allocate a separate status row below the header.
Keep the no-network explanation in its tooltip to preserve vertical space.
Use content hashes to reuse unchanged assets across releases. Dev-server mode
is exempt; it must not claim Offline ready. Retain upstream
source/build archives, dependency source references and licenses.
Native preprocessing byte proofs require the recorded command options,
including -cpuflags 0 to disable CPU-specific optimized routines. Do not claim
equality with default native FFmpeg or arbitrary untested media/version pairs.
No arbitrary FFmpeg audio/image filters are exposed. Optional profile filters
can be applied offline to a shared normalized comparison archive. Freeze
normalized-archive settings so that replay and stream proofs retain their input.
For completed normalized inputs, explicitly set both master/raw filters to
no-op `setsar=1` before importing sim so its reuse path never probes an absent
source with FFmpeg. The archive's recorded applied filters remain provenance.

The native BLAS RGB333 comparison values are frozen source-independent tables
for 512 hardware colours. The numerical adapter changes no video-specific
palettes/decisions. The prebuffer_trace adapter corrects only the diagnostic
cursor for an entirely boot-loaded Prg stream whose last sector contains unused
padding; require zero timed pattern payload and exact 64-pattern rounding. It
must not change decisions, physical schedules, packed bytes or target quality.

The pack_validation adapter corrects only the optional-list speed predicate.
Scroll controls require a shadow list to carry their position item, including
dense or zero-update frames whose list is not faster than a bitmap. Keep the
speed-gain requirement for FRAME_NORMAL, frozen cycle equality, required-scroll
lists, forbidden fade lists and all physical delivery/buffer checks intact.
Never drop scroll, lower cold cap or change decisions to bypass this check.
Display a concise root-cause error banner; preserve the complete traceback in
Activity log so diagnostics do not consume the editor viewport.

Use managed tmpfs leases for generated media and long browser test inputs;
comparison receipts and project-owned per-frame series use persistent logs/
and UTF-8, LF, headered TSV. Keep browser test diagnostics under webenc/harness/.

On user video selection, choose an exact supported raster if present, otherwise
the closest visible H40 aspect ratio. Start with no source selected and Picture dimensions at 320x224.
Allow manual changes after selection. Remove 256x192 from normal
choices. Expose 288x200 only for a source of exactly 288x200 (Sonic OP).

Keep Download ZIP as a large button to the right of the progress area, spanning
its height. Enable it only for an available completed package and use a warm
accent color when ready. Do not duplicate it in the summary dock.

Do not fetch or load a bundled video on startup. Show empty source/output
previews and keep Generate disabled until the user selects a valid video.
The public sample file remains a test fixture only.

Ordinary video output is restricted to 15, 24 and 30 fps. Auto chooses the
closest supported rate; 60 and 59.94 inputs must use 30 fps. Sample video at
output timestamps, preserve duration/audio speed and keep the original source
fps/frame timestamps for trimming. Reset output to Auto on replacement.

Show ISO · CUE · MP4 within the Download ZIP button so the package contents are
visible before download. Keep the accessible button name Download ZIP.

When Source is empty, its preview area is a keyboard-accessible file picker and
video drop target. Keep empty preview overlays contained within their panels.
Sort Picture dimensions by descending pixel count, including the conditional
288x200 option. Do not expose a palette-algorithm selector; use MOSAIC-GM.

Display live confirmed canonical replay PNGs in Output during processing and
automatically switch to Playback when the first is available. Until completion,
show a still frame and its output frame number without playback controls. At
completion, replace it with the canonical sim MP4 and reconstructed audio.
Only emit these PNGs after packed verification, from the unchanged canonical
renderer. Throttle GUI messages, never alter codec decisions or replay pixels.
Follow explicit processing frame indexes on Source, translating output times
through the selected source interval. Never treat candidate counts as frames.
Normalized RGB/PCM archives keep their fixed first-frame source display.

Framing Canvas uses non-square H40 pixels. Fit its CSS aperture at 64:49 within
the 4:3 Output monitor and use object-fit:fill so the intrinsic 320x224 image
ratio is not applied again. Keep this correction consistent on desktop/mobile;
never change encoder geometry to fix a CSS display mismatch.

Encode summary has one continuously scrolling view: canonical codec timeline
first, compact wrapping palette cards, HW scroll/Palette fade overview tracks,
then chronological Events. Do not restore Overview/Palettes/Events tabs or the
palette-set dropdown. Derive timeline rows from the exact render_analysis.py
calculations and analysis_style.py colors, without importing the video UI.
Keep canonical scales, the cold-cap guide and physical Supply/Band semantics;
quality-budget accounting is not a physical supply meter. Fit only averages
drawing columns; exact values remain available on hover and in Detail at two
pixels per frame. Include full canonical analysis-timeline.tsv in the ZIP.

Read palette frame features must also report explicit processing frame indexes
from the actual input-path/index mapping in FrameFeatureCache. Follow those
frames on Source; preserve progress throttling and report the first/final frame.
Do not infer indexes from palette candidate or core evaluation counts.

The title badge reads exactly "simplified ver".

On successful encoding completion, show one browser alert after React commits
the completed UI and enabled download button. No completion alert on cancel or
error. Cancel a pending notification on state replacement or unmount.

Register a native beforeunload confirmation while encoding or while a completed
result remains available, including after ZIP download. Remove it on cancel,
error or result invalidation. Leave idle/source-only sessions unguarded. Browser
confirmation wording is controlled by the browser.

Keep a compact footer below the lower dock with horizontal links to akiyan.com,
the project GitHub repository, @akiyan on X, and the owner's YouTube channel
UC6CTbKtzPPydO8lLwLzkF8w. Open these external links in a new tab. Preserve the
single-viewport desktop layout; mobile may wrap the link row if necessary.

Footer credit reads "by akiyan.com" as text. Follow it with a globe icon
linking to https://www.akiyan.com/.
Show globe, X, GitHub and YouTube as muted icons with accessible names and
tooltips; X links to https://x.com/akiyan. Keep Licenses as text.

Keep a Licenses button in the footer. Open notices in a keyboard-accessible
modal with internal scrolling, Escape/Close dismissal and focus restoration.
Load installed-version notices only when opened. Include project MIT
terms, third-party copyright/license texts and component-specific source links.
A project GitHub link does not replace sources for dependencies absent there;
do not describe the notices UI as proof of complete GPL/LGPL compliance.
Left-align footer items in this order: by akiyan.com, globe, X, GitHub, YouTube,
Licenses. Display © 2026 at the right edge. Keep the label plural: Licenses.

Production hosting is Cloudflare Pages at
https://segacd-fmv-cavc-encoder.akiyan.com/. Use globally installed cf CLI for
project, deployment, domain and DNS operations. Run npm run deploy:pages for
repeat deployment. The static asset upload gap in cf beta is handled by the
official Pages assets API, using a short-lived upload JWT and the existing cf
session. Do not log credentials or put them in public artifacts. Preserve the
reproducible dist/pages build and Cloudflare _headers. Exclude development test
media/runners while retaining the complete Wasm runtime and Binutils sources.
Set Speculation-Rules to the cached empty offline-speculation.json so Cloudflare
does not inject a network-only speculation endpoint into this single-page app.
User authorization persists: deploy webapp changes after successful validation
without requesting confirmation for each deployment.
