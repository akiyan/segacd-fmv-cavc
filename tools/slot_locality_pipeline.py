#!/usr/bin/env python3
"""Optional movie-wide physical VRAM slot-locality pipeline.

The logical allocator owns residency, cold/reuse decisions, and eviction.
This module optionally adds one movie-wide logical-to-physical permutation
after those decisions.  Disabling it keeps the identity physical numbering and
therefore needs no seed/map/accounting subprocess pipeline.  Cold-run
descriptors and their exact byte/schedule accounting remain mandatory.
"""
from __future__ import annotations

import os
import pickle
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

import pattern_supply
from tile_alloc import (
    evaluate_slot_locality,
    optimize_slot_locality,
    replay_logical_slots,
    verify_display_equivalence,
)


_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"", "0", "false", "no", "off"}


@dataclass(frozen=True)
class Policy:
    """Fixed slot-locality policy shared by every pass in one invocation."""

    enabled: bool = False
    final_iterations: int = 160
    heavy_run_target: int = 30
    retry_exit: int = 75
    max_accounting_passes: int = 4


def policy_from_env(environ: Mapping[str, str] | None = None) -> Policy:
    """Read the internal switch populated by the public TOML profile."""
    env = os.environ if environ is None else environ
    raw = str(env.get("CBRSIM_SLOT_LOCALITY", "0")).strip().lower()
    if raw in _TRUE:
        enabled = True
    elif raw in _FALSE:
        enabled = False
    else:
        raise ValueError(
            "CBRSIM_SLOT_LOCALITY must be a boolean value, "
            f"got {env.get('CBRSIM_SLOT_LOCALITY')!r}")
    return Policy(enabled=enabled)


def source_run_groups(
        replay, sources_by_frame, *, boot_inline_requests=None):
    """Partition cold slots by the physical source that splits descriptors."""
    if len(sources_by_frame) != len(replay.placements):
        raise ValueError("pattern-source frame count differs")
    result = []
    for frame, (placements, prefetch_slots, raw_sources) in enumerate(zip(
            replay.placements,
            replay.prefetch_cold_slots,
            sources_by_frame)):
        if len(raw_sources) != len(placements):
            raise ValueError(
                f"frame {frame} pattern-source/update count differs")
        prg = []
        word = []
        dic = []
        for update, ((slot, cold), raw_source) in enumerate(zip(
                placements, raw_sources)):
            if not cold:
                continue
            source = int(raw_source)
            if source == pattern_supply.SOURCE_PRG:
                prg.append(int(slot))
            elif source == pattern_supply.SOURCE_WR:
                word.append(int(slot))
            elif source == pattern_supply.SOURCE_DIC:
                dic.append((int(slot),))
            else:
                raise ValueError(
                    f"frame {frame} update {update} has invalid source {source}")
        if frame == 0 and boot_inline_requests is not None:
            # Frame 0 is untimed boot construction. Its staging path already
            # covers worst-case descriptor fragmentation.
            result.append(())
            continue
        groups = []
        if prg:
            groups.append(tuple(prg))
        # Prefetch payload follows visible payload, so it is a separate sorted
        # Prg group rather than an assumed continuation of visible patterns.
        if prefetch_slots:
            groups.append(tuple(int(slot) for slot in prefetch_slots))
        if word:
            groups.append(tuple(word))
        groups.extend(dic)
        result.append(tuple(groups))
    return tuple(result)


def accounted_cold_slots(replay, boot_inline_requests):
    """Exclude untimed frame-0 writes from locality run optimization."""
    cold = list(replay.cold_slots)
    if cold and boot_inline_requests is not None:
        cold[0] = ()
    return tuple(cold)


def select_initial_plan(
        policy: Policy,
        cold_slots_by_frame,
        pool: int,
        *,
        cold_cap: int,
        packed_execution: bool,
        loaded_map: str | os.PathLike[str] | None = None,
):
    """Choose the map used while the main decision pass is running."""
    identity = np.arange(int(pool), dtype=np.int64)
    map_path = str(loaded_map or "").strip()
    if not policy.enabled:
        return (
            evaluate_slot_locality(
                cold_slots_by_frame, pool, identity, cold_cap=cold_cap),
            "identity-off",
        )
    if map_path:
        return (
            evaluate_slot_locality(
                cold_slots_by_frame, pool, np.load(map_path),
                cold_cap=cold_cap),
            "loaded",
        )
    if not packed_execution:
        return (
            evaluate_slot_locality(
                cold_slots_by_frame, pool, identity, cold_cap=cold_cap),
            "identity-player",
        )
    return (
        optimize_slot_locality(
            cold_slots_by_frame,
            pool,
            cold_cap=cold_cap,
            target_heavy_runs=policy.heavy_run_target,
        ),
        "predicted",
    )


def select_completed_plan(
        policy: Policy,
        cold_slots_by_frame,
        pool: int,
        *,
        cold_cap: int,
        packed_execution: bool,
        run_groups_by_frame,
):
    """Choose a delivered map from frozen completed decisions."""
    if policy.enabled and packed_execution:
        return optimize_slot_locality(
            cold_slots_by_frame,
            pool,
            cold_cap=cold_cap,
            iterations=policy.final_iterations,
            target_heavy_runs=policy.heavy_run_target,
            run_groups_by_frame=run_groups_by_frame,
        )
    return evaluate_slot_locality(
        cold_slots_by_frame,
        pool,
        np.arange(int(pool), dtype=np.int64),
        cold_cap=cold_cap,
        run_groups_by_frame=run_groups_by_frame,
    )


def decision_record(
        policy: Policy,
        *,
        stage: str,
        player_execution: str,
        physical_by_logical,
        baseline_runs,
        optimized_runs,
        risk_frames,
) -> dict:
    """Build the frozen decision-log record without storing an OFF map."""
    if not policy.enabled:
        return {
            "schema_version": 2,
            "enabled": False,
            "trace": "identity",
            "player_execution": str(player_execution),
        }
    return {
        "schema_version": 2,
        "enabled": True,
        "trace": (
            "final_decisions" if stage == "final"
            else "predictive_exact_target"
        ),
        "physical_by_logical": np.asarray(
            physical_by_logical, np.uint16),
        "baseline_runs": np.asarray(baseline_runs, np.uint16),
        "optimized_runs": np.asarray(optimized_runs, np.uint16),
        "risk_frames": np.asarray(risk_frames, np.bool_),
        "player_execution": str(player_execution),
    }


def requires_multi_pass(
        policy: Policy,
        *,
        stage: str,
        emit_decisions: str,
        loaded_map: str,
) -> bool:
    """Return whether seed/map/accounting subprocesses are needed."""
    return bool(
        policy.enabled
        and not str(stage).strip()
        and str(emit_decisions).strip()
        and not str(loaded_map).strip()
    )


def derive_completed_map(
        decision_log,
        output_path,
        *,
        policy: Policy,
        packed_execution: bool,
) -> None:
    """Derive and prove the physical map used by an accounting pass."""
    with Path(decision_log).open("rb") as source:
        log = pickle.load(source)
    frames = [
        [(int(cell), key) for cell, _palette, key in sorted(frame)]
        for frame in log["frames"]
    ]
    prefetch_requests = (log.get("raw_prefetch") or {}).get("requests")
    replay = replay_logical_slots(
        frames,
        int(log["geom"][2]),
        int(log["vram_tiles"]),
        prefetch_requests=prefetch_requests,
    )
    if replay.tearing:
        raise AssertionError(
            f"seed slot-locality replay tore {replay.tearing} patterns")
    boot_inline_requests = int(
        (log.get("raw_prefetch") or {}).get("boot_inline_requests", 0))
    cold_trace = accounted_cold_slots(replay, boot_inline_requests)
    run_groups = source_run_groups(
        replay,
        (log.get("pattern_supply") or {}).get("sources", ()),
        boot_inline_requests=boot_inline_requests,
    )
    plan = select_completed_plan(
        policy,
        cold_trace,
        int(log["vram_tiles"]),
        cold_cap=int(log.get("max_cold", 0)),
        packed_execution=packed_execution,
        run_groups_by_frame=run_groups,
    )
    proof = verify_display_equivalence(
        frames,
        int(log["geom"][2]),
        int(log["vram_tiles"]),
        plan.physical_by_logical,
        prefetch_requests=prefetch_requests,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    np.save(output, np.asarray(plan.physical_by_logical, np.uint16))
    risk = np.asarray(plan.risk_frames, bool)
    print(
        "slot locality seed proof: "
        f"execution="
        f"{'packed-suffix' if packed_execution else 'legacy-entry-order'}; "
        f"display={proof['frames']}/{len(frames)} exact "
        f"cold={proof['cold']} tearing={proof['tearing']}; "
        f"deadline-heavy source-aware runs "
        f"{int(plan.baseline_runs[risk].max(initial=0))}"
        f"->{int(plan.optimized_runs[risk].max(initial=0))}",
        flush=True,
    )


def run_accounting_passes(
        command: Sequence[str],
        common_env: Mapping[str, str],
        *,
        policy: Policy,
        decision_log,
        map_path,
        retry_path,
        packed_execution: bool,
) -> None:
    """Run the expensive ON-only seed/map/accounting subprocess sequence."""
    if not policy.enabled:
        raise ValueError("disabled slot locality does not use accounting passes")
    map_path = Path(map_path)
    retry_path = Path(retry_path)

    seed_env = dict(common_env)
    seed_env["CBRSIM_SLOT_LOCALITY_STAGE"] = "seed"
    seed_env["CBRSIM_NOPANELS"] = "1"
    seed_env.pop("CBRSIM_SLOT_LOCALITY_MAP", None)
    seed_env.pop("CBRSIM_SLOT_LOCALITY_REUSE", None)
    print("slot locality seed pass: logical decisions", flush=True)
    subprocess.run(command, env=seed_env, check=True)

    # Physical delivery is a proof, not an automatic cold-cap tuning loop.
    derive_completed_map(
        decision_log,
        map_path,
        policy=policy,
        packed_execution=packed_execution,
    )
    accounting_pass = 1
    while accounting_pass <= policy.max_accounting_passes:
        retry_path.unlink(missing_ok=True)
        final_env = dict(common_env)
        final_env["CBRSIM_SLOT_LOCALITY_STAGE"] = "final"
        final_env["CBRSIM_SLOT_LOCALITY_MAP"] = str(map_path.resolve())
        final_env["CBRSIM_SLOT_LOCALITY_RETRY_MAP"] = str(
            retry_path.resolve())
        final_env["CBRSIM_SLOT_LOCALITY_RETRY_ALLOWED"] = (
            "1" if accounting_pass < policy.max_accounting_passes else "0")
        final_env["CBRSIM_SLOT_LOCALITY_REUSE"] = "1"
        print(
            "slot locality accounting pass "
            f"{accounting_pass}/{policy.max_accounting_passes}: "
            "pay frozen map, then validate completed decisions",
            flush=True,
        )
        result = subprocess.run(command, env=final_env, check=False)
        if result.returncode == 0:
            return
        if result.returncode != policy.retry_exit:
            result.check_returncode()
        if not retry_path.is_file():
            raise SystemExit(
                "slot-locality accounting requested a retry without a map")
        current = np.load(map_path)
        retry = np.load(retry_path)
        if np.array_equal(current, retry):
            raise SystemExit(
                "slot-locality accounting cannot progress: retry map "
                "equals the current map")
        retry_path.replace(map_path)
        accounting_pass += 1
    raise SystemExit(
        "slot-locality accounting did not converge within "
        f"{policy.max_accounting_passes} passes")
