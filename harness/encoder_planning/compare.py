#!/usr/bin/env python3
"""Compare planner results with a frozen tools directory, without encoding."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import pickle
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
MODULES = (
    "physical_budget", "stream_schedule", "wordbuf_ring",
    "upgrade_planner", "pattern_supply",
)


def recorded(call, *, allow_rejection):
    try:
        return {"result": call()}
    except ValueError as exc:
        if not allow_rejection:
            raise
        return {
            "error": type(exc).__name__, "message": str(exc),
            "kind": getattr(exc, "kind", ""),
            "details": getattr(exc, "details", {}),
        }


def word_inputs(supply, frames, variant):
    """Actual whole-run decisions with early spare capacity and later bursts."""
    per, sources, orders, prefetch, dic_indices = [], [], [], [], []
    prg, wr0, wr1, dic, updates = (np.zeros(frames, np.int64) for _ in range(5))
    for frame in range(frames):
        lengths = (
            (40, 24) if frame < frames // 2
            else ((90, 38, 64) if (frame + variant) % 3 else (40, 24))
        )
        if variant == 1 and frame > frames * 3 // 4:
            lengths = ()
        entries, frame_sources = [], []
        slot = 1
        for run, length in enumerate(lengths):
            entries.extend(range(slot, slot + length))
            source = (
                supply.SOURCE_WR
                if frame >= frames // 2 and run == 0
                else supply.SOURCE_PRG)
            frame_sources.extend([source] * length)
            slot += length + 2
        count = len(entries)
        per.append((tuple(range(count)), tuple(entries), (True,) * count))
        sources.append(tuple(frame_sources))
        orders.append(tuple(range(count)))
        prefetch.append(((slot + 2, True, b"prefetch"),) if frame % 11 == 4 else ())
        dic_indices.append((-1,) * count)
        prg[frame] = frame_sources.count(supply.SOURCE_PRG) + len(prefetch[-1])
        (wr1 if frame & 1 else wr0)[frame] = frame_sources.count(supply.SOURCE_WR)
        updates[frame] = count
    return {
        "per": tuple(per), "prefetch_per": tuple(prefetch),
        "transfer_orders": tuple(orders),
        "current_plan": supply.SupplyPlan(
            sources=tuple(sources), prg_patterns=(), wr0_patterns=(),
            wr1_patterns=(), dic_patterns=(), prg_loads=prg,
            wr0_loads=wr0, wr1_loads=wr1, dic_loads=dic,
            dic_indices=tuple(dic_indices)),
        "n_updates": updates,
        "update_lists": np.ones(frames, bool),
        "fps": 24, "cells": 1120, "audio_frame_bytes": 468,
        "prg_capacity_patterns": 640,
        "word_capacities": (256, 256),
        "baseline_occupancy": np.full(frames, 64, np.int64),
    }


def worker(tools_dir, output, frames):
    sys.path.insert(0, str(tools_dir))
    import physical_budget
    import stream_schedule
    import wordbuf_ring
    import upgrade_planner
    import pattern_supply

    results = {}
    timings = {}

    def run(name, call, *, allow_rejection=False):
        started = time.perf_counter()
        results[name] = recorded(call, allow_rejection=allow_rejection)
        timings[name] = time.perf_counter() - started
        print(f"{tools_dir.parent.name}: {name}: {timings[name]:.3f}s", flush=True)

    rng = np.random.default_rng(122)
    for case in range(96):
        count = (1, 2, 5, 17, 65)[case % 5]
        loads = rng.choice([0, 1, 63, 64, 65, 127, 210], count)
        control = rng.choice([0, 16, 2047, 2048, 2049, 4096], count)
        kwargs = {
            "fps": (15, 20, 24, 30)[case % 4],
            "ring_capacity_patterns": (128, 640, 12448)[case % 3],
            "prebuffer_capacity_patterns": (64, 128, 640)[case % 3],
            "frame_sectors": 5, "fill": case % 7 != 0,
        }
        run(f"schedule-{case:02}", lambda: stream_schedule.schedule_payload_ring(
            loads, control, **kwargs), allow_rejection=True)

    def online(count, fps, ring, fill):
        generator = np.random.default_rng(122 + count)
        wanted = generator.choice([0, 1, 63, 64, 65, 127, 210], count)
        wanted[:count // 4] = 0
        controls = generator.choice([0, 468, 2047, 2048, 2049], count)
        controls[0] = 0
        planner = physical_budget.SharedSectorPlanner(
            count, max_prg_patterns=210, max_cold_patterns=210,
            prebuffer_capacity_patterns=640, frame_sectors=5,
            fps=fps, ring_capacity_patterns=ring,
            maximum_control_block_bytes=controls, fill=fill)
        limits = []
        for frame in range(count):
            limit = planner.begin_frame(frame)
            limits.append(dataclasses.asdict(limit))
            planner.commit_frame(
                frame, prg_patterns=min(int(wanted[frame]), limit.prg_patterns),
                cold_patterns=min(int(wanted[frame]), limit.prg_patterns),
                control_block_bytes=min(
                    int(controls[frame]), limit.control_block_bytes))
        plan = dataclasses.asdict(planner.finish(wanted))
        # The new summary is derived from the unchanged full end-of-pass proof.
        plan.pop("prefix_margin_sectors", None)
        return {"limits": limits, "plan": plan}

    for fps in (15, 20, 24, 30):
        for ring, fill in ((None, True), (640, True), (1280, False)):
            run(f"online-{fps}-{ring}-{fill}",
                lambda: online(129, fps, ring, fill))
    run("online-scale", lambda: online(frames, 24, 640, True))

    for variant in (0, 1):
        for count in (32, 128, frames):
            kwargs = word_inputs(pattern_supply, count, variant)
            run(f"word-{variant}-{count}",
                lambda: dataclasses.asdict(wordbuf_ring.plan(**kwargs)))

    def layout_trials(variant):
        kwargs = word_inputs(pattern_supply, 128, variant)
        kwargs.pop("word_capacities")
        prepared = (
            wordbuf_ring.prepare(**kwargs)
            if hasattr(wordbuf_ring, "prepare") else None)
        # Return to the first capacity after other trials: leaked assignments
        # or counters would alter this final source/route proof.
        return [
            dataclasses.asdict(
                prepared.plan(capacities) if prepared is not None
                else wordbuf_ring.plan(word_capacities=capacities, **kwargs))
            for capacities in ((256, 256), (192, 320), (320, 192), (256, 256))
        ]

    for variant in (0, 1):
        run(f"layout-{variant}", lambda: layout_trials(variant))

    zero_boot = word_inputs(pattern_supply, 128, 0)
    zero_boot["word_capacities"] = (128, 192)
    # The reference rejects a bank consumed entirely by its boot reserve.
    # Preserve and compare that rejection instead of hiding it in reuse tests.
    run("layout-zero-boot", lambda: dataclasses.asdict(
        wordbuf_ring.plan(**zero_boot)), allow_rejection=True)

    for case in range(24):
        count = (5, 31, 129, 513)[case % 4]
        supplied = rng.integers(40, 100, count)
        mandatory = rng.integers(0, 40, count)
        demand = mandatory + rng.integers(0, 200, count)
        demand[::7] = mandatory[::7]
        run(f"reserve-{case:02}", lambda: dataclasses.asdict(
            upgrade_planner.build_balanced_reserve_plan(
                demand, supplied, 150, minimum_demand=mandatory)))

    keys = tuple(index.to_bytes(64, "big") for index in range(2000))
    cold_keys = tuple(
        tuple(keys[index] for index in rng.choice(len(keys), 210, replace=False))
        for _ in range(80))
    prediction = upgrade_planner.DemandPrediction(
        *(np.zeros(80, np.int64) for _ in range(4)),
        cold_keys=cold_keys,
        protected_keys=tuple(frame[::3] for frame in cold_keys),
        cold_slots=())
    run("dictionary", lambda: pattern_supply.select_dic_dictionary(prediction, 512))
    with output.open("wb") as target:
        pickle.dump({"results": results, "timings": timings}, target)


def compare(expected, actual, path):
    if isinstance(expected, np.ndarray):
        if (not isinstance(actual, np.ndarray)
                or expected.dtype != actual.dtype
                or not np.array_equal(expected, actual)):
            raise AssertionError(f"{path}: numeric trace differs")
    elif isinstance(expected, dict):
        if expected.keys() != actual.keys():
            raise AssertionError(f"{path}: result fields differ")
        for key, value in expected.items():
            compare(value, actual[key], f"{path}.{key}")
    elif isinstance(expected, (tuple, list)):
        if type(actual) is not type(expected) or len(expected) != len(actual):
            raise AssertionError(f"{path}: sequence differs")
        for index, (left, right) in enumerate(zip(expected, actual, strict=True)):
            compare(left, right, f"{path}[{index}]")
    elif expected != actual:
        raise AssertionError(f"{path}: {expected!r} != {actual!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-tools", type=Path)
    parser.add_argument("--candidate-tools", type=Path, default=ROOT / "tools")
    parser.add_argument("--frames", type=int, default=512)
    parser.add_argument("--tsv", type=Path, default=ROOT / "logs/planner-reuse.tsv")
    parser.add_argument("--json", type=Path, default=ROOT / "logs/planner-reuse.json")
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.frames < 2:
        parser.error("--frames must be at least two")
    if args.worker:
        worker(args.worker, args.output, args.frames)
        return
    if not args.reference_tools:
        parser.error("--reference-tools is required")
    reference_tools = args.reference_tools.resolve()
    current_tools = args.candidate_tools.resolve()
    with tempfile.TemporaryDirectory(prefix="planner-reuse-") as temporary:
        packets = []
        for index, directory in enumerate((reference_tools, current_tools)):
            output = Path(temporary) / f"{index}.pkl"
            subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 "--worker", str(directory), "--output", str(output),
                 "--frames", str(args.frames)],
                check=True, cwd=ROOT)
            with output.open("rb") as source:
                packets.append(pickle.load(source))
        before, after = packets
    compare(before["results"], after["results"], "planners")
    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv.open("w", encoding="utf-8", newline="\n") as target:
        target.write("case\treference_seconds\tcurrent_seconds\tequal\n")
        for name in before["results"]:
            target.write(
                f"{name}\t{before['timings'][name]:.9f}\t"
                f"{after['timings'][name]:.9f}\t1\n")
    word_plans = [
        result["result"] for name, result in after["results"].items()
        if name.startswith("word-") and "result" in result]
    word_with_refill = sum(
        plan["feasible"] and any(plan["selected_refill_patterns"])
        for plan in word_plans)
    if not word_with_refill:
        raise AssertionError("comparison did not exercise a feasible WordBuf refill")
    receipt = {
        "equal": True, "cases": len(before["results"]),
        "successful_cases": sum(
            "result" in result for result in after["results"].values()),
        "rejected_cases": sum(
            "error" in result for result in after["results"].values()),
        "frames": args.frames, "scope": "synthetic planner replay, no encode",
        "word_feasible": sum(plan["feasible"] for plan in word_plans),
        "word_with_refill": word_with_refill,
        "reference_tools": str(reference_tools),
        "source_sha256": {
            label: {
                name: hashlib.sha256((directory / f"{name}.py").read_bytes()).hexdigest()
                for name in MODULES}
            for label, directory in (
                ("reference", reference_tools), ("current", current_tools))},
    }
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
