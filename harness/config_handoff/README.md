# TOML-to-decision-log handoff regression

This harness proves the configuration boundary used by the encoder and packer:

1. A per-source TOML profile overwrites inherited per-source `CBRSIM_*` values.
2. `sim.py` freezes the resolved geometry, timing, audio, hardware and pack
   settings in `decisions.pkl`.
3. `pack_stream.py` reads those values from the decision log and produces the
   same `HEADER.DAT`, `BODY.DAT`, `MOVIE.DAT` and `palettes.bin` even when its
   process receives deliberately wrong H40/15fps/ADPCM environment values.

Run it against an existing full decision log:

```sh
tools/python.sh harness/config_handoff/verify.py \
  videos/SonicJamOp_H40_288x200_adpcm22_cold210/tmp/decisions.pkl \
  --sp-extension tmp/sonic-jam-op/build/movieplay_sp_ext.bin
```

The test uses temporary output directories and does not modify `out/movieplay`.
