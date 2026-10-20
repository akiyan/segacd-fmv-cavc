# Frame count compiler equivalence

Prepare the current Python and player runtime assets with the normal web build.
Build packed fixtures using `harness/palette_capacity/build_fixture.py` from
the repository root, then run:

```sh
node webenc/harness/frame_capacity/verify.mjs \
  tmp/frame65535/24fps-16384 \
  tmp/frame65535/30fps-32768-clock \
  tmp/frame65535/24fps-65535-clock
```

The verifier starts its own local Vite server and headless browser, compiles
each actual stream contract with the bundled WebAssembly GNU tools, and
requires all 32,768 boot bytes to match independent native GNU compilation.
It checks the u16 count boundary and the long-index/PCM constants without
decoding or encoding source media. Files remain under each fixture's
`wasm-proof/` directory. No web deployment is performed.
