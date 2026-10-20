# TOML-to-decision-log handoff regression

The unit suite in `tools/test_encode_config.py` owns TOML parsing and
inherited-environment replacement. This integration harness uses an existing
frozen decision log to prove that `pack_stream.py` produces identical
HEADER.DAT, BODY.DAT, MOVIE.DAT, paltab.bin and palidx.bin under clean and
deliberately polluted per-source environments. It does not re-encode a source.

Run it against an existing full decision log:

```sh
SIM_OUT="$(tools/python.sh tools/encode_config.py \
  profiles/sonic-jam-op.toml --print-sim-output)"
tools/python.sh harness/config_handoff/verify.py \
  "$SIM_OUT/decisions.pkl" \
  --sp-extension tmp/sonic-jam-op/build/movieplay_sp_ext.bin
```

The test uses temporary output directories and does not modify `out/movieplay`.
