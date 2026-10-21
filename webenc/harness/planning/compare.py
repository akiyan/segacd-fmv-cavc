"""Compare full encoder decisions, streams, replay pixels and stage timings."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def compare_saved(baseline, candidate, tsv, *, cross_runtime):
    script = ROOT / "harness/runtime_storage/compare.py"
    arguments = [str(script), str(baseline), str(candidate), "--tsv", str(tsv)]
    if not cross_runtime:
        subprocess.run([sys.executable, *arguments], check=True)
        return []
    # Native NumPy and wasm32 use different default integer widths. Compare
    # exact integer values across runtimes; keep all other checks unchanged.
    import numpy as np
    spec = importlib.util.spec_from_file_location("saved_comparison", script)
    comparison = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(comparison)
    strict_equal = comparison.equal
    widths = []

    def equal(left, right, where):
        if isinstance(left, np.ndarray) and isinstance(right, np.ndarray):
            if (left.dtype != right.dtype and left.dtype.kind in "iu"
                    and right.dtype.kind == left.dtype.kind
                    and {left.dtype.itemsize, right.dtype.itemsize} == {4, 8}
                    and left.dtype.byteorder == right.dtype.byteorder):
                if left.shape != right.shape or not np.array_equal(left, right):
                    raise AssertionError(f"{where}: integer values differ")
                widths.append({
                    "field": where, "baseline": str(left.dtype),
                    "candidate": str(right.dtype), "values_equal": True})
                return
        strict_equal(left, right, where)

    comparison.equal = equal
    previous_arguments = sys.argv
    try:
        sys.argv = arguments
        comparison.main()
    finally:
        sys.argv = previous_arguments
    return widths


def compare_runs(args):
    prefix = ROOT / "logs" / f"encoder-reuse-sonic-{args.baseline}-vs-{args.candidate}"
    baseline = args.job / "runs" / args.baseline
    candidate = args.job / "runs" / args.candidate
    receipts = [
        json.loads((directory / "benchmark.json").read_text())
        for directory in (baseline, candidate)]
    for receipt in receipts:
        if not receipt["completed"]:
            raise ValueError("Run has no authenticated completion")
    for key in ("frames", "source_sha256", "profile_sha256"):
        if receipts[0][key] != receipts[1][key]:
            raise ValueError(f"Mismatching input: {key}")
    cross_runtime = receipts[0]["runtime"] != receipts[1]["runtime"]
    integer_widths = compare_saved(
        baseline, candidate, str(prefix) + "-decisions.tsv",
        cross_runtime=cross_runtime)
    hashes = {}
    for name in (
            "packed/HEADER.DAT", "packed/BODY.DAT", "packed/MOVIE.DAT",
            "stage-sha256.tsv", "playback-frames.tsv"):
        left, right = sha(baseline / name), sha(candidate / name)
        if left != right:
            raise AssertionError(f"{name}: outputs differ")
        hashes[name] = left
    if len((baseline / "playback-frames.tsv").read_text().splitlines()) - 1 != receipts[0]["frames"]:
        raise AssertionError("Canonical replay does not cover the complete source")
    stage_rows = []
    timings = []
    for name in (args.baseline, args.candidate):
        text = (ROOT / "logs" / f"encoder-reuse-sonic-{name}.log").read_text()
        timing = {
            key: float(value) for key, value in re.findall(
                r"^\s*(Extract|Palette|Quantize|Forecast|Decide|Finalize|Total)\s+"
                r"([0-9.]+)s\s+\(", text, re.MULTILINE)}
        if len(timing) != 7:
            raise ValueError(f"Missing completed stage timing: {name}")
        timings.append(timing)
    for stage in timings[0]:
        before, after = timings[0][stage], timings[1][stage]
        stage_rows.append(
            f"{stage}\t{before:.1f}\t{after:.1f}\t"
            f"{(100 * (1 - after / before)) if before else 0:.2f}")
    Path(str(prefix) + "-timing.tsv").write_text(
        "stage\tbaseline_seconds\tcandidate_seconds\treduction_percent\n"
        + "\n".join(stage_rows) + "\n", encoding="utf-8")
    result = {
        "equal": True, "baseline": receipts[0], "candidate": receipts[1],
        "output_sha256": hashes,
        "integer_width_differences": integer_widths,
        "encode_reduction_percent": None if cross_runtime else 100 * (
            1 - receipts[1]["encode_seconds"] / receipts[0]["encode_seconds"]),
        "single_run_per_revision": True,
        "excludes": ["input normalization", "runtime download", "MP4", "ISO", "ZIP"],
    }
    Path(str(prefix) + ".json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("baseline")
    parser.add_argument("candidate")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "tools"))
    from tmpfs_workspace import lease_managed_path
    lease = lease_managed_path(args.job)
    if lease is None:
        raise SystemExit("Use the matching managed workspace root")
    try:
        compare_runs(args)
    finally:
        lease.release()


if __name__ == "__main__":
    main()
