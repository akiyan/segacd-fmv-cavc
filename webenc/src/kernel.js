export async function createKernel(bytes) {
  const module = await WebAssembly.instantiate(
    bytes || (await (await fetch("/wasm/webenc-kernel.wasm")).arrayBuffer()),
    {},
  );
  const wasm = module.instance.exports;
  const alloc = (n) => wasm.alloc(n);
  const view = (ptr, n) => new Uint8Array(wasm.memory.buffer, ptr, n);
  const put = (data) => {
    const ptr = alloc(data.byteLength);
    view(ptr, data.byteLength).set(
      new Uint8Array(data.buffer, data.byteOffset, data.byteLength),
    );
    return ptr;
  };
  const release = (ptr, n) => wasm.release(ptr, n);
  const histogram = alloc(8192);
  view(histogram, 8192).fill(0);
  return {
    accumulate(rgba) {
      const ptr = put(rgba);
      try {
        wasm.accumulate_histogram(ptr, rgba.length / 4, histogram);
      } finally {
        release(ptr, rgba.length);
      }
    },
    trainPalette() {
      const ptr = alloc(180);
      try {
        wasm.train_palette(histogram, ptr);
        return view(ptr, 180).slice();
      } finally {
        release(ptr, 180);
      }
    },
    paletteBytes(palette) {
      const ptr = put(palette),
        out = alloc(128);
      try {
        wasm.palette_bytes(ptr, out);
        return view(out, 128).slice();
      } finally {
        release(ptr, 180);
        release(out, 128);
      }
    },
    quantize(rgba, width, height, palette) {
      if (
        rgba.byteLength !== width * height * 4 ||
        palette.byteLength !== 180 ||
        !width ||
        !height ||
        width % 8 ||
        height % 8
      )
        throw new Error("Invalid tile-aligned raster or palette");
      const ptr = put(rgba),
        pal = put(palette),
        tile = alloc((width * height) / 2),
        map = alloc((width * height) / 64);
      try {
        if (wasm.quantize(ptr, width, height, pal, tile, map))
          throw new Error("Palette quantization failed");
        return {
          rgba: view(ptr, rgba.length).slice(),
          tile: view(tile, (width * height) / 2).slice(),
          pmap: view(map, (width * height) / 64).slice(),
        };
      } finally {
        release(ptr, rgba.length);
        release(pal, 180);
        release(tile, (width * height) / 2);
        release(map, (width * height) / 64);
      }
    },
    adpcmRoundtrip(pcm, initial = [0, 0]) {
      if (!pcm.length || pcm.length % 2)
        throw new Error("ADPCM chunks need a positive even sample count");
      const ptr = put(pcm),
        state = put(new Int32Array(initial)),
        chunk = alloc(4 + pcm.length / 2),
        decoded = alloc(pcm.length * 2);
      try {
        if (wasm.adpcm_roundtrip(ptr, pcm.length, state, chunk, decoded))
          throw new Error("Invalid ADPCM state");
        return {
          chunk: view(chunk, 4 + pcm.length / 2).slice(),
          pcm: new Int16Array(wasm.memory.buffer, decoded, pcm.length).slice(),
          state: Array.from(new Int32Array(wasm.memory.buffer, state, 2)),
        };
      } finally {
        release(ptr, pcm.byteLength);
        release(state, 8);
        release(chunk, 4 + pcm.length / 2);
        release(decoded, pcm.byteLength);
      }
    },
    createResidency(cells, pool) {
      const state = wasm.residency_create(cells, pool);
      if (!state) throw new Error("Invalid residency pool");
      return {
        has(key) {
          if (key.byteLength !== 32) throw new Error("Invalid pattern key");
          const ptr = put(key);
          try { return Boolean(wasm.residency_has(state, ptr)); }
          finally { release(ptr, key.byteLength); }
        },
        placeFrame(cells, keys, frame) {
          if (keys.length !== cells.length * 32) throw new Error("Invalid pattern keys");
          const cp = put(new Uint32Array(cells)), kp = put(keys), op = alloc(cells.length * 8);
          try {
            if (wasm.residency_place_frame(state, cp, kp, cells.length, frame, op))
              throw new Error("Invalid residency cell");
            return cells.length ? new Uint32Array(wasm.memory.buffer, op, cells.length * 2).slice() : new Uint32Array();
          } finally {
            release(cp, cells.length * 4); release(kp, keys.length); release(op, cells.length * 8);
          }
        },
        dispose() { wasm.residency_destroy(state); },
      };
    },
    dispose() {
      release(histogram, 8192);
    },
  };
}
