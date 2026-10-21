"""Run independent native/browser encodes serially with persistent receipts."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools"))
from encode_config import load_profile
from resource_tokens import acquire_stem, acquire_tokens
from tmpfs_workspace import lease_managed_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("runs", nargs="+")
    args = parser.parse_args()
    job = args.job.resolve()
    manifest = json.loads((job / "manifest.json").read_text())
    profile = load_profile(ROOT / "profiles" / manifest["profile"])
    lease = lease_managed_path(job, required_bytes=8 * 1024**3)
    if lease is None:
        raise SystemExit("Use the matching managed workspace root")
    try:
        for run in args.runs:
            runtime, revision = run.split("-", 1)
            if runtime not in ("native", "wasm") or not revision.isalnum():
                raise ValueError(f"Invalid run: {run}")
            log = ROOT / "logs" / f"encoder-reuse-sonic-{run}.log"
            status = log.with_suffix(".json")
            if log.exists() or status.exists():
                raise SystemExit(f"Previous run evidence exists: {log}")
            if runtime == "native":
                command = [sys.executable, str(Path(__file__).with_name("native.py")),
                           str(job), revision]
            else:
                command = ["node", str(Path(__file__).with_name("browser.mjs")),
                           str(job), revision]
            receipt = {
                "run": run, "command": command, "log": str(log),
                "started": time.time(), "pid": None, "exit_code": None,
            }
            print(f"START {run}: {log}", flush=True)
            # Native sim owns its phase tokens; browser has one host CPU token.
            stem = cpu = None
            try:
                if runtime == "wasm":
                    stem = acquire_stem(profile.sim_stem)
                    cpu = acquire_tokens("cpu", count=1)
                with log.open("w") as stream:
                    process = subprocess.Popen(
                        command, stdout=stream, stderr=subprocess.STDOUT,
                        cwd=ROOT, env={**os.environ, "PYTHONUNBUFFERED": "1"})
                    receipt["pid"] = process.pid
                    status.write_text(json.dumps(receipt, indent=2) + "\n")
                    receipt["exit_code"] = process.wait()
                receipt["finished"] = time.time()
                status.write_text(json.dumps(receipt, indent=2) + "\n")
                if receipt["exit_code"]:
                    raise SystemExit(f"FAIL {run}: inspect {log}")
                result = json.loads(
                    (job / "runs" / run / "benchmark.json").read_text())
                if not result["completed"] or result["frames"] != manifest["frames"]:
                    raise SystemExit(f"Incomplete full-profile result: {run}")
                receipt["result"] = result
                status.write_text(json.dumps(receipt, indent=2) + "\n")
                print(f"PASS {run}: {result['encode_seconds']:.3f}s", flush=True)
            finally:
                if cpu:
                    cpu.release()
                if stem:
                    stem.release()
    finally:
        lease.release()


if __name__ == "__main__":
    main()
