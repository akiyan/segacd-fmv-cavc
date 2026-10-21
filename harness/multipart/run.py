#!/usr/bin/env python3
"""Run an existing multipart DEBUG ISO and verify full-cycle VDP output."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import encode_config
import resource_tokens
import tmpfs_workspace
from multipart import digest, run_logged, stem_lock, write_json
from verify_trace import verify


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--max-frames", type=int, default=10000)
    args = parser.parse_args()
    os.chdir(ROOT)
    manifest = json.loads(args.manifest.read_text())
    if not manifest["debug"]:
        parser.error("use a DEBUG multipart manifest for VDP/HUD verification")
    profile = encode_config.load_profile(manifest["profile"])
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    tag = "multipart-" + run_id
    receipt_path = ROOT / "logs" / f"{tag}.json"
    receipt = {"result": "RUNNING", "manifest": str(args.manifest.resolve()),
               "manifest_sha256": digest(args.manifest), "iso_sha256": manifest["iso_sha256"]}
    write_json(receipt_path, receipt)
    with stem_lock(f"multipart-{profile.artifact_stem}-{manifest['parts']}"):
        lease = tmpfs_workspace.activate_directory(kind="multipart-playback", key=tag,
                                                   required_bytes=2*1024**3)
        try:
            output = lease.entry / "data"
            if digest(manifest["iso"]) != manifest["iso_sha256"]:
                raise ValueError("ISO changed since its manifest was built")
            shutil.copyfile(manifest["iso"], output / "multipart.iso")
            cue = output / "multipart.cue"
            cue.write_text('FILE "multipart.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n')
            write_json(output / "manifest.json", manifest)
            env = dict(os.environ, OUTDIR=str(output), BIOS_REGION=manifest["region"])
            run, _ = run_logged([ROOT / "tools/run_headless.sh", cue, "--tag", tag,
                                 "--max-frames", str(args.max_frames), "--boot-wait", "0.2",
                                 "--presses", "100", "--press-gap", "0.05", "--shots", "0"], tag, env=env)
            trace = output / f"gpgx_logvdp_{tag}.log.gz"
            receipt.update(run=run, trace=str(trace), trace_sha256=digest(trace))
            with resource_tokens.acquire_tokens("cpu", count=1):
                receipt.update(verify(manifest, trace, ROOT / "logs" / f"{tag}.tsv"))
            tmpfs_workspace.mark_directory_complete(lease, reuse_token=manifest["iso_sha256"])
        except BaseException as error:
            receipt.update(result="FAIL", error=str(error))
            raise
        finally:
            write_json(receipt_path, receipt)
            lease.release()
            print(receipt_path, flush=True)
    print(f"PASS: {receipt['displayed_frames']} exact displayed frames across {len(receipt['visits'])} visits")


if __name__ == "__main__":
    main()
