# Shared codec and player synchronization

The browser bundles the current shared Python encoder/packer and original
assembly/linker sources. It does not maintain a second implementation of the
delivery model or DMA player. `npm run build` regenerates these bundles and
runs `npm run verify:runtime` before creating the offline cache. The download's
runtime metadata and Activity log retain the build version.

`check_bundle.py` compares every bundled Python source, the version file,
player/linker sources and the production Python adapter with this checkout.
This catches an old generated archive left behind after a native codec change.
It also authenticates the encoder fingerprint and explicit build version:

```sh
tools/python.sh webenc/harness/runtime_sync/check_bundle.py webenc/dist/client \
  --json logs/webenc-built-runtime.json
```

`player_fixture.py` compiles a native release-player reference using an existing
packed stream's constants and palette tables. It never runs the encoder or
changes the packed stream. The existing browser compiler harness then requires
byte equality for the 1,108-byte Sub extension and the complete 32,768-byte
boot system area. This catches assembler, linker, source-bundle and per-stream
specialization differences; it is not a playback-timing or encoder-equivalence
test.

With the local Vite server running on port 4173:

```sh
tools/python.sh --workspace-root /path/to/workspace \
  webenc/harness/runtime_sync/player_fixture.py out/sonic-jam-op \
  /path/to/workspace/compiler-sonic
node webenc/harness/equivalence/compiler.mjs \
  /path/to/workspace/compiler-sonic/compiler-input.zip Japan
```

Use `--region us` for fixture preparation and `North America` for the browser
compiler to check that region. Keep fixture media/binaries in the selected
workspace and command output/receipts in `logs/`.

The e202/p176 compilation matrix covers Sonic OP, Lunar, Machi OP, Machi ED,
Big Buck Bunny and TIPSY in Japan, plus Sonic OP in North America. All seven
cases match completely. It includes 15/24/30fps cadence, scroll, WordBuf refill
and the long BBB routing/audio configuration. This confirms that the browser
includes the current EAT/LAT transfers, LVB pattern reclamation, publication
guards and Main run-loop implementation. Native playback qualifications do not
imply that every browser-generated movie has uniform cadence.

The production adapter calls the shared incremental fade planner once. Planning
errors remain errors; it never automatically restarts with demoted fade shots.
Historical frozen native comparison runners retain their legacy behavior and
are not the production browser entry point.

The full 2,535-frame e202 Lunar decisions also pass the browser packer's complete
verification, including 22 fade-out controls. HEADER.DAT (638,976 bytes),
BODY.DAT (16,304,128 bytes) and MOVIE.DAT (16,943,104 bytes) exactly match the
native pack. This reuses frozen decisions and does not claim independent
browser palette/decision equality for e202. Evidence is retained in
`logs/webenc-catchup-lunar-repack.log` and
`logs/webenc_scroll_pack_browser_repack.tsv`.

The fixed production build passes the offline harness: an interrupted runtime
download is retried, then two fresh Workers encode the short fixture through
MP4 and ISO/CUE ZIP after networking is disabled and the page is reloaded.
Required runtime requests all come from the service worker. Optional GA4
failures remain recorded separately. The complete receipt is
`logs/webenc_offline_verification.json`.

A 60-second, 1,440-frame 320x224/24fps production-build encode with moving
test imagery, fades and a black interval passes the full ordinary-input path
at cold cap `2:180,3:230`. It uses one physical planning pass, has no fade retry,
and produces verified stream files, MP4 and ISO/CUE ZIP. The detector selects
normal controls for this fixture; the Lunar repack above covers hardware fade
controls. MP4 verification measures zero AAC sample lag against reconstructed
PCM. Receipts are `logs/webenc-catchup-production.log` and
`logs/webenc-catchup-production-media.log`. An earlier development-server trial
was invalidated by a source-edit reload; its failed log is retained separately.
