#!/usr/bin/env python3
"""Verify byte preservation while an open append-only writer stays active."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
with tempfile.TemporaryDirectory(prefix="gpgx-stream-test-") as directory:
    path = Path(directory) / "retroarch_test.log"
    original = (b"[libretro ERROR] [224(224)][100(100)] VRAM 0x100 write -> 0x1 (200)\n\n"
                * 600000)
    path.write_bytes(original)
    with path.open("ab", buffering=0) as writer:
        process = subprocess.Popen([
            str(ROOT / "tools/python.sh"),
            str(ROOT / "harness/gpgx_logvdp/stream_log.py"), str(path),
            "--pid", str(os.getpid()),
        ])
        try:
            deadline = time.monotonic() + 20
            while path.stat().st_blocks * 512 > 20 * 1024 * 1024:
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise AssertionError("archiver did not release fixture pages")
                time.sleep(0.1)
            suffix = (
                b"[libretro ERROR] unexpected test failure retained\n"
                b"[INFO] [Runtime] Content ran for a total of: test\n"
                b"[INFO] [Core] Unloading core...\n"
            )
            writer.write(suffix)
            original += suffix
            assert path.stat().st_size == len(original)
            assert b"Unloading core" in path.read_bytes()[-4096:]
            full = Path(directory) / "full.gz"
            subprocess.run([
                "bash", str(ROOT / "harness/gpgx_logvdp/compact_log.sh"),
                str(path), str(full),
            ], check=True)
            process.wait(timeout=10)
            assert gzip.decompress(full.read_bytes()) == original
            receipt = json.loads(Path(str(path) + ".stream.done.json").read_text())
            assert receipt["raw_bytes"] == len(original)
            assert receipt["sha256"] == hashlib.sha256(original).hexdigest()
            compact = path.read_bytes()
            assert b"Unloading core" in compact
            assert b"unexpected test failure retained" in compact
            assert b"VRAM 0x100" not in compact
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
print("GPGX streaming archive: byte equivalence, append offsets, tail and errors PASS")
