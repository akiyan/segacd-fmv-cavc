# Browser CAVC verification

The selected workbench keeps source/crop and encoded playback side by side.
Generate uses the original CAVC implementation; Playback accepts its generated
result only. Source framing remains a separate, explicitly labelled mode.

## Editing desk and live summary QA

- Visual source: `/dev/shm/segacd-fmv-cavc/artifacts/webenc-qa-frame-range-24frames-fc2bbbe0a9ce/data/compact-funnel-1366x768.png`, with the user's requested 4:3 Output box and integrated timeline as intentional layout changes.
- Implementation: matching `monitor-1366x768.png` in that directory.
- Combined comparison: matching `editor-design-comparison.png` (2732x768).
- Viewport/state: 1366x768 CSS pixels, density 1, bundled source at frame 0, complete source crop, 320x224 framing, North America. Both individual captures are 1366x768 pixels. No density normalization.
- The combined full-view comparison preserves the dark workbench, one-line header, persistent Generate control and a log at least 140px tall. Source uses remaining width and the Output box is exactly 4:3. Playback and trim share a single compact timeline. The lower dock uses the existing download space for selected decisions.
- Desktop 1280x720, 1366x768, 1024x768 and 1920x1080 fit without page scrolling. Mobile 390x844 has no horizontal overflow and scrolls vertically.
- Primary interactions: numeric and mouse/keyboard range edits; independent frame playhead; selected-end preview stop; source seek; cancellation; title percent prefix and restoration; generated playback; ZIP extraction and summary tabs.
- Original stream bytes, canonical RGB hashes and PCM match the pre-instrumentation 24-frame reference. The real Funnel encode produces a verified summary and preserves real ISO/CUE/stream files.
- Focused data comparison: `summary-fixture/palette-overview.png` and `effect-events.png` in the completed Lunar Wasm job. Nine palette sets, 252 actual scroll controls in two intervals and all 22 fade writes reproduce its own decisions. This verifies the summary reader on the completed independent Lunar encode; it does not represent an additional full Lunar re-encode.
- Console errors: none in the complete SPA encode/layout checks.

### Comparison history

- [P1, fixed] RGB333 palette channels (0-7) initially appeared nearly black when rendered directly as browser RGB. Swatches use the canonical `channel * 36` display conversion; the browser test checks the computed color and the post-fix palette capture.
- [P1, fixed] Fade summary omitted four controls in the held black tail. The reader includes `right_black_end`; exact original decision arrays and the Events view now show all 22 controls.
- No actionable P0/P1/P2 visual or interaction findings remain. Native output-video controls remain separate from the source trim timeline so reviewing a result does not change its input selection.

final result: passed

## Verified processing

- A shared 1,357-frame normalized Sonic Jam input passes native/Wasm byte
  comparison for HEADER.DAT, BODY.DAT and MOVIE.DAT after playback/disc integration.
- Every RGB pixel of all 1,357 browser replay frames matches the canonical
  native render_analysis.py display implementation. The reconstructed playback
  WAV is byte-identical to the native sim WAV.
- The original Sub extension (1,108 bytes) and complete boot image (32,768 bytes)
  assembled/linked in WebAssembly match native GNU m68k Binutils byte for byte.
- A 90.466667-second / 2,714-frame MP4 input completes Generate, in-panel playback
  and ZIP download through the public Funnel build, with 288×200 / 30fps,
  source aspect 32:35 and cold cap 210. Every ISO stream extraction matches the
  packaged HEADER/BODY; MOVIE is the exact concatenation and CUE names the ISO.
- The exported 90-second MP4 fully decodes, contains all 2,714 frames, and its
  AAC-LC audio has zero measured sample lag and 0.99866 correlation with the
  canonical PCM model after sample-rate conversion.
- A browser-built ISO boots and displays changing movie images in Genesis Plus
  GX. Input data is kept private in the managed tmpfs comparison workspace.

The full MP4 browser test is an ordinary WebCodecs/Canvas normalization path;
its pixels/PCM are not asserted identical to native FFmpeg preprocessing.
Normalized-input comparison and ordinary-input functional coverage are separate.

## Interaction checks

The current UI tests cover crop drag/resize, bounds/reset, input aspect validation,
fps/fit, cold-cap auto/manual/reset, cancellation/retry, progress, local video
play/seek/mute, ZIP invalidation, desktop layout, mobile overflow and page errors.
Generated MP4 playback pauses in Framing mode and resumes in Playback. The
emulator opens in its own tab and receives the generated ISO. Production contains
no BIOS; development auto-load is restricted to loopback Vite middleware.

Ten processing stages include normalization, MOSAIC-GM, quantization, planning,
encoding, packing verification, canonical reconstruction, MP4, ISO/CUE and ZIP.
The minimal progress strip names the active stage; long diagnostic words wrap inside the log pane.

## Reproduction

- `npm run test:ui`
- `node scripts/verify-encode.mjs` (WEBENC_INPUT/URL/settings/output env supported)
- `node scripts/verify-playback.mjs`
- `npm run test:audio`, `test:cold-cap`, `test:sites`, `test:emulator`
- `node harness/equivalence/compiler.mjs COMPILER_INPUT.zip`
- `node harness/equivalence/replay.mjs NORMALIZED_JOB`
- `tools/python.sh --gpu scripts/verify-preview-media.py`

Screenshots and downloaded media are disposable tmpfs artifacts. Persistent
comparison receipts belong in logs/; renderer/frame diagnostics use TSV.

## Adaptive desktop height

- Checked sequential resizing at 1920x1440, 3420x1822, 1366x768, 1024x768, 1280x720, 1920x1800 and 390x844 with Playwright. Desktop has no page overflow; mobile retains vertical scrolling.
- Timeline remains about 8px below the preview controls. Output stays 4:3 and Source shares its height. The lower dock expands once the monitor reaches its width limit, while compact desktop sizes retain the 140px minimum log.
- Inspected managed captures `adaptive-dock-1920x1440.png` and `adaptive-dock-1366x768.png`. No browser script errors occurred during resizing.

## Automatic dimensions and compact encoding stages

- Uploaded square-pixel test MP4s at 288x200, 320x224, 640x360 and 640x480: selected 288x200, 320x224, 320x168 and 320x224 respectively. Replacing the Sonic raster hides 288x200; 256x192 is absent. Manual selection survives after loading. Initial sample remains 320x224.
- All ten stages fit a compact horizontal row. Desktop 1366x768 and 1920x1440 retain a single viewport; mobile 390x844 has no horizontal page overflow. No browser script errors. Inspected managed capture `dimensions-stage-list-1366x768.png`.

## Prominent package download

- Download ZIP appears once, to the right of the progress area, with 18px desktop text and a 25px icon. It fills the progress area's height and turns amber when a completed package is available.
- A real 24-frame encode passed stream verification, playback and ZIP content checks through the moved button. Inspected `cavc-complete.png`.
- Checked 1366x768, 1024x768, 1920x1440 and 390x844. Desktop remains within one viewport; narrow mobile retains vertical scrolling without horizontal page overflow.

## Empty startup, aspect presets and supported cadence

- Startup makes no sample video request, shows empty source/output previews, and disables Generate. Picture dimensions initially remain 320x224.
- Source pixel aspect offers Auto, 1:1, 32:35, 8:7 and Custom. Auto explicitly states its 1:1 fallback; no source pixel-aspect detection is implied. A real 24-frame 32:35 preset encode passed verification and its downloaded input settings retained [32,35].
- Imported 120-frame 60 and 59.94 fps fixtures. Both auto-select 30 fps; fixed output choices are 15, 24 and 30 only. Timestamp normalization verifies every output PNG against every second source PNG for exact 60fps. Audio remains 22050 samples/second and duration differs by less than one output frame.
- ZIP button visibly lists ISO · CUE · MP4. Tested 1366x768, 1024x768 and 390x844 without horizontal page overflow.

- Published Funnel smoke check confirms no initial sample request and visible ISO · CUE · MP4 label (`empty-startup-zip-label.png`). A real encode of source frames 0–47 from a 60fps input auto-produced 24 output frames at 30fps; downloaded stream, ISO/CUE, MP4 and source/output fps metadata checks passed.

## Live confirmed replay and source follow

- Removed the browser emulator entry, UI handoff, BIOS middleware, dependencies and public vendor bundle. ZIP ISO/CUE generation remains verified. Fixed empty Output positioning so its placeholder cannot cover the page.
- Source preview click opens the native file picker; dropping a video selects it. Confirmed both on the published Funnel page. Advanced settings contains no Palette selector. Resolution options descend by pixel count.
- A real 60fps input, source frames 0–47, produces 24 output frames at 30fps. Live frames 0 and 23 are emitted after packing and their decoded RGB hashes exactly match the canonical replay TSV. The running GUI shows Playback, a confirmed frame canvas and no video controls; completion replaces it with playable sim MP4/audio. Source follows output frame 23 to source time 0.766667 seconds, accounting for 60→30 sampling.
- HEADER/BODY/MOVIE bytes, reconstructed PCM WAV and every canonical replay-frame hash match the preceding encode exactly. All encoder phases still reach the GUI; ZIP content and playback tests pass.

- Final running-state capture `live-sim-frame.png` shows confirmed output frame 0 with matching Source frame 0. Later GUI observations confirm output frame 23 maps to Source frame 46 from the 60fps input. No MP4 controls are present during processing; completion playback/ZIP checks pass. Source seeking compensates for microsecond-truncated container boundaries.

## Framing H40 aspect correction

- The framing canvas used object-fit:contain, which preserved its intrinsic square-pixel 320x224 image ratio inside a corrected CSS aperture. Use object-fit:fill and size the canvas at 64:49 within the unchanged 4:3 monitor.
- Tested the real full preprocessed Lunar MP4 at source frame 355 with 32:35 input aspect and 320x224 Preserve aspect. Source and Output content both measure 64:49 at 1920x1080, 1366x768, 1024x768 and 390x844; monitor remains 4:3, with no horizontal page overflow. Inspected `lunar-framing-aspect-corrected.png`; the title and globe retain matching proportions. Encoder bytes/settings are unaffected by this CSS change.

## Unified summary with canonical timeline

- One view replaces the three tabs: codec timeline, wrapping palette cards, effect tracks and chronological events. Cards retain all four banks, unique-line counts and output spans.
- Qualified full Lunar fixture shows all 9 palette sets, 2 scroll windows and 22 fade controls. Verified responsive card wrapping, no horizontal page overflow, overview/detail timeline click mapping, and exact event seeks. Inspected full `summary-fixture/combined-summary.png`.
- Canonical exporter matches every column and all 2535 rows from the actual render_analysis.py TSV (`logs/20261014T175442_webenc_lunar_canonical_timeline.tsv`). The timeline uses canonical colors/scales and physical Wrd/Prg supply; Fit averaging affects drawing only, and Detail retains each frame.
- Actual browser 24-frame encode passes with timeline metadata and analysis-timeline.tsv in the ZIP. Existing live-frame playback, ISO/CUE, reconstructed audio, stream verification and package checks pass.

## Palette-feature source follow and completion notification

- The palette feature reader reports actual FrameFeatureCache path/index mappings, including the first and final frame, with existing progress throttling. Real 24-frame encoding verifies feature frame 0 and frame 23 and corresponding Source seeks (60fps source mapped to 30fps output).
- Published badge reads exactly simplified ver. Successful encode emits exactly one completion alert; cancellation emits none. ZIP/playback/stream checks pass, and streams, reconstructed PCM and replay hashes remain unchanged.

## Compact author/project footer

- Added four external links below the dock: akiyan.com, project GitHub, @akiyan on X and the owner channel from verified upload metadata. All open a new tab with noopener/noreferrer.
- Published-page checks at 1366x768, 1024x768 and 1920x1440 retain a single viewport. Footer occupies 29px. Mobile 390x844 keeps vertical scrolling without horizontal overflow. Inspected `footer-1366x768.png`; Sites checks pass.

## Cloudflare Pages production publication

- Published Pages project segacd-fmv-cavc-encoder with an active custom domain and proxied CNAME: https://segacd-fmv-cavc-encoder.akiyan.com/. cf CLI manages resources and deployment; the official Pages assets API fills the beta CLI's missing file-transfer command.
- Static build contains 35 assets (50.3 MiB total, largest 24.1 MiB), excluding development media/runner and retaining required Wasm packages and Binutils source/license. Origin isolation and MIME headers are verified on the custom domain.
- Actual 24-frame browser encode on both Pages and the custom domain passes confirmed-frame/source-follow checks, completion alert, timeline metadata, MP4 playback, ZIP extraction and ISO/CUE embedded stream checks. HEADER/BODY/MOVIE, PCM and replay hashes remain identical.
- Footer akiyan.com links to www.akiyan.com, and X displays @akiyan. Active deployment receipt is under logs/*_webenc_cloudflare_pages_deployment.json.
