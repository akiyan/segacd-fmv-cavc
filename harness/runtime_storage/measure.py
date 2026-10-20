#!/usr/bin/env python3
"""Run one command; record process-tree RSS and selected filesystem use as TSV."""

import argparse
import csv
import json
import os
from pathlib import Path
import resource
import signal
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from runtime_paths import scratch_root, workspace_root
from tmpfs_workspace import filesystem_type


def tree_rss(pid):
    # ps exposes KiB on both Linux and macOS. Shared pages may be counted twice
    # between processes; this is a sampled tree sum, not a physical-RAM total.
    result = subprocess.check_output(
        ["ps", "-axo", "pid=,ppid=,rss="], text=True)
    rows = [tuple(map(int, line.split())) for line in result.splitlines()]
    members = {pid}
    while True:
        children = {child for child, parent, _rss in rows if parent in members}
        expanded = members | children
        if expanded == members:
            break
        members = expanded
    return sum(rss * 1024 for child, _parent, rss in rows if child in members)


def linux_memory():
    path = Path("/proc/meminfo")
    if not path.exists():
        return {}
    return {line.split()[0].rstrip(":"): int(line.split()[1]) * 1024
            for line in path.read_text().splitlines() if len(line.split()) >= 2}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tsv", type=Path, required=True)
    parser.add_argument("--interval", type=float, default=5)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.interval <= 0:
        parser.error("command and a positive interval are required")
    roots = {"workspace": workspace_root(), "scratch": scratch_root()}
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    peak = 0
    with args.tsv.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow(["elapsed_seconds", "tree_rss_bytes", "system_shmem_bytes",
                         "system_mem_available_bytes", "system_swap_used_bytes",
                         "workspace_fs_used_bytes", "scratch_fs_used_bytes"])
        process = subprocess.Popen(command, start_new_session=True)
        try:
            while True:
                rss = tree_rss(process.pid)
                peak = max(peak, rss)
                memory = linux_memory()
                swap = (memory["SwapTotal"] - memory["SwapFree"]
                        if "SwapTotal" in memory else "")
                writer.writerow([f"{time.monotonic() - started:.3f}", rss,
                                 memory.get("Shmem", ""), memory.get("MemAvailable", ""),
                                 swap, *(shutil.disk_usage(p).used for p in roots.values())])
                stream.flush()
                try:
                    status = process.wait(timeout=args.interval)
                    break
                except subprocess.TimeoutExpired:
                    pass
        except BaseException:
            # The command may be a wrapper (for example /usr/bin/time). Stop
            # its whole process group so an interrupted monitor leaves no encode.
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            raise
    # This is the OS high-water RSS for the largest single child, not the tree sum.
    peak_child = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    peak_child *= 1 if sys.platform == "darwin" else 1024
    report = {
        "command": command, "exit_status": status,
        "elapsed_seconds": time.monotonic() - started,
        "sampled_tree_rss_peak_bytes": peak,
        "child_rss_high_water_bytes": peak_child,
        "sample_interval_seconds": args.interval,
        "roots": {key: {"path": str(path), "filesystem": filesystem_type(path)}
                  for key, path in roots.items()},
    }
    args.tsv.with_suffix(".json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report), flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
