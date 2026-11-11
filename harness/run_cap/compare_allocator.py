#!/usr/bin/env python3
"""Replay existing normal-frame decisions through a frozen and current allocator."""
import argparse
import importlib.util
import json
import pickle
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from tile_alloc import TileAllocator
from run_budget import clone_allocator
from tmpfs_workspace import lease_managed_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decisions", type=Path)
    parser.add_argument("reference", type=Path)
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    lease = lease_managed_path(args.decisions)
    try:
        with args.decisions.open("rb") as source:
            log = pickle.load(source)
        if any((log.get("scroll") or {}).get("active", ())):
            raise SystemExit("This replay requires a normal-frame source")
        if len(log["frames"]) < 202:
            raise SystemExit("This replay requires at least 202 frames")
        spec = importlib.util.spec_from_file_location("reference_alloc", args.reference)
        reference = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(reference)
        cells = int(log["geom"][0]) * int(log["geom"][1])
        pool = int(log["vram_tiles"])
        allocators = [reference.TileAllocator(cells, pool), TileAllocator(cells, pool)]
        seconds = [0.0] * len(allocators)
        snapshots = None
        for frame, updates in enumerate(log["frames"]):
            results = []
            for index, alloc in enumerate(allocators):
                started = time.perf_counter()
                placed = alloc.place_frame([(c, k) for c, _, k in updates], frame)
                prefetched = []
                for request in log["raw_prefetch"]["requests"][frame]:
                    key, deadline, slot, mandatory, relocate, _forced = request
                    prefetched.append(alloc.prefetch(
                        key, frame, deadline, forced_slot=slot,
                        mandatory=mandatory, relocate=relocate))
                seconds[index] += time.perf_counter() - started
                results.append((placed, prefetched, alloc.state_digest(),
                                alloc.tearing, alloc.final_reclaims,
                                alloc.prefetch_evictions,
                                alloc.mandatory_prefetch_evictions))
            if any(result != results[0] for result in results[1:]):
                raise AssertionError(f"allocator divergence at frame {frame}")
            if frame == 200:
                snapshots = [clone_allocator(a) for a in allocators]
        # Repeated admissions on an actually populated Sonic cache. Trials do
        # not mutate their baseline; these are allocation queries, not encodes.
        trial_seconds = []
        trial_results = []
        updates = [(c, k) for c, _, k in log["frames"][201]]
        for baseline in snapshots:
            started = time.perf_counter()
            values = []
            for _ in range(50):
                trial = clone_allocator(baseline)
                values.append(trial.place_frame(updates, 201))
            trial_seconds.append(time.perf_counter() - started)
            trial_results.append(values)
        assert all(result == trial_results[0] for result in trial_results[1:])
        result = dict(
            decisions=str(args.decisions.resolve()), reference=str(args.reference.resolve()),
            frames=len(log["frames"]), identical=True,
            implementations=["original_scalar", "vectorized_scan"],
            replay_seconds=seconds, repeated_trial_seconds=trial_seconds,
            repeated_trial_speedup=trial_seconds[0] / trial_seconds[-1])
        args.json.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))
    finally:
        if lease:
            lease.release()


if __name__ == "__main__":
    main()
