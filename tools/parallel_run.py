#!/usr/bin/env python3
"""Run independent profile pipelines concurrently under shared resource tokens.

The local pipeline stops at the playback HUD gate. Public timeline/Gist and
upload stages remain owned by the interactive ``run`` workflow because they
require visual inspection and publication authorization.
"""

from __future__ import annotations

import argparse
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
import math
import os
from pathlib import Path
import pickle
import subprocess
import sys
import threading
import time
from typing import TextIO


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from encode_config import EncodeProfile, load_profile  # noqa: E402
import resource_tokens  # noqa: E402
import tmpfs_workspace  # noqa: E402


STAGES = ("sim", "disc", "record", "hud")
_PRINT_LOCK = threading.Lock()


class ParallelRunError(RuntimeError):
    pass


@dataclass(frozen=True)
class JobOptions:
    through: str
    workers: int
    use_gpu: bool
    force_reencode: bool
    record_seconds: int | None
    stagger_seconds: float
    run_dir: Path


@dataclass(frozen=True)
class JobResult:
    profile: Path
    stem: str
    status: str
    failed_stage: str
    elapsed_seconds: float
    log: Path
    message: str


def validate_distinct_stems(profiles: list[EncodeProfile]) -> None:
    stems: dict[str, Path] = {}
    for profile in profiles:
        if profile.sim_stem in stems:
            raise ParallelRunError(
                "profiles share one videos stem and cannot run together: "
                f"{stems[profile.sim_stem]} / {profile.path} -> "
                f"{profile.sim_stem}")
        stems[profile.sim_stem] = profile.path


def _profile_output_dir(profile: EncodeProfile) -> Path:
    path = profile.output_dir
    return path if path.is_absolute() else ROOT / path


def _say(message: str) -> None:
    with _PRINT_LOCK:
        print(message, flush=True)


def _record_seconds(profile: EncodeProfile, override: int | None) -> int:
    if override is not None:
        return override
    return math.ceil(float(profile.data["source"]["duration"])) + 30


def _native_record_size(profile: EncodeProfile) -> str:
    mode = str(profile.data["video"]["mode"]).upper()
    if mode == "H32":
        return "256x224"
    if mode == "H40":
        return "320x224"
    raise ParallelRunError(
        f"{profile.path}: recording is unsupported for mode {mode}")


def stage_commands(
    profile: EncodeProfile,
    *,
    through: str,
    use_gpu: bool,
    record_seconds: int | None,
) -> list[tuple[str, list[str]]]:
    """Return fixed commands; the HUD frame count is filled after simulation."""

    through_index = STAGES.index(through)
    commands: list[tuple[str, list[str]]] = []
    python = str(ROOT / "tools" / "python.sh")
    if through_index >= STAGES.index("sim"):
        sim_command = [python]
        if use_gpu:
            sim_command.append("--gpu")
        sim_command.extend([
            str(ROOT / "tools" / "sim.py"),
            str(profile.path),
        ])
        commands.append(("sim", sim_command))
    if through_index >= STAGES.index("disc"):
        commands.append(("disc", [
            "make", "disc", f"CONFIG={profile.path}", "DEBUG=1",
            f"PYTHON={python}",
        ]))
    stem = profile.sim_stem
    if through_index >= STAGES.index("record"):
        commands.append(("record", [
            str(ROOT / "tools" / "record_movie.sh"),
            "--config", str(profile.path),
            "--no-build",
            "--seconds", str(_record_seconds(profile, record_seconds)),
            "--tag", f"{stem}_emu",
            "--record-size", _native_record_size(profile),
            "--out", str(ROOT / "videos" / f"{stem}_emu_preview.mp4"),
        ]))
    if through_index >= STAGES.index("hud"):
        commands.append(("hud", []))
    return commands


def _expected_frames(profile: EncodeProfile) -> int:
    decision_log = profile.decision_log
    if not decision_log.is_absolute():
        decision_log = ROOT / decision_log
    with decision_log.open("rb") as handle:
        decisions = pickle.load(handle)
    frames = decisions.get("frames")
    if not isinstance(frames, list) or not frames:
        raise ParallelRunError(
            f"{decision_log}: completed decision frames are missing")
    return len(frames)


def _hud_command(profile: EncodeProfile) -> list[str]:
    stem = profile.sim_stem
    video = ROOT / "videos" / f"{stem}_emu_lossless.mkv"
    hud_tsv = ROOT / "videos" / f"{stem}_emu_hud.tsv"
    gate = ROOT / "videos" / f"{stem}_emu_hud_gate.json"
    return [
        str(ROOT / "tools" / "python.sh"),
        str(ROOT / "harness" / "startup_resync" / "analyze.py"),
        str(video),
        str(profile.path),
        "--tsv", str(hud_tsv),
        "--gate-json", str(gate),
        "--expected-frames", str(_expected_frames(profile)),
    ]


def _run_logged(
    command: list[str],
    *,
    env: dict[str, str],
    log: TextIO,
) -> int:
    log.write(f"$ {' '.join(command)}\n")
    log.flush()
    return subprocess.run(
        command,
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        check=False,
    ).returncode


def _run_sim_with_handoff(
    command: list[str],
    *,
    profile: EncodeProfile,
    env: dict[str, str],
    log: TextIO,
    handoff: Path,
) -> tuple[int, tmpfs_workspace.Lease | None]:
    handoff.mkdir(parents=True, exist_ok=False)
    sim_env = dict(env)
    sim_env["SEGACD_TMPFS_HANDOFF"] = str(handoff)
    log.write(f"$ {' '.join(command)}\n")
    log.flush()
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        env=sim_env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    lease = None
    acknowledged = False
    ready = handoff / "ready.json"
    while process.poll() is None:
        if ready.is_file() and not acknowledged:
            output_dir = _profile_output_dir(profile)
            lease = tmpfs_workspace.lease_managed_alias(output_dir)
            if lease is None:
                process.terminate()
                process.wait()
                raise ParallelRunError(
                    f"sim tmpfs handoff did not resolve {output_dir}")
            (handoff / "ack").write_text("pinned\n", encoding="utf-8")
            acknowledged = True
        time.sleep(0.05)
    status = process.wait()
    if ready.is_file() and not acknowledged and status == 0:
        output_dir = _profile_output_dir(profile)
        lease = tmpfs_workspace.lease_managed_alias(output_dir)
        if lease is None:
            raise ParallelRunError(
                f"sim tmpfs handoff did not resolve {output_dir}")
        (handoff / "ack").write_text("pinned\n", encoding="utf-8")
    return status, lease


def _run_job(
    index: int,
    profile: EncodeProfile,
    options: JobOptions,
) -> JobResult:
    if options.stagger_seconds > 0 and index > 0:
        time.sleep(options.stagger_seconds * index)
    started = time.monotonic()
    log_path = options.run_dir / f"{index:02d}-{profile.artifact_stem}.log"
    failed_stage = ""
    message = ""
    sim_lease = None
    try:
        stem_lease = resource_tokens.acquire_stem(profile.sim_stem)
    except resource_tokens.ResourceBusyError as exc:
        return JobResult(
            profile.path, profile.sim_stem, "FAIL", "lock",
            time.monotonic() - started, log_path, str(exc))

    env = resource_tokens.held_stem_environment(profile.sim_stem)
    env["CBRSIM_WORKERS"] = str(options.workers)
    if not options.use_gpu:
        env["CBRSIM_GPU"] = "0"
    if options.force_reencode:
        env["CBRSIM_FORCE_REENCODE"] = "1"

    try:
        with log_path.open("w", encoding="utf-8") as log:
            for stage, fixed_command in stage_commands(
                profile,
                through=options.through,
                use_gpu=options.use_gpu,
                record_seconds=options.record_seconds,
            ):
                failed_stage = stage
                command = (
                    _hud_command(profile)
                    if stage == "hud" else fixed_command
                )
                _say(f"[{profile.artifact_stem}] {stage} start")
                stage_started = time.monotonic()
                if stage == "sim":
                    status, sim_lease = _run_sim_with_handoff(
                        command,
                        profile=profile,
                        env=env,
                        log=log,
                        handoff=options.run_dir / (
                            f"{index:02d}-{profile.artifact_stem}-handoff"),
                    )
                else:
                    status = _run_logged(command, env=env, log=log)
                stage_elapsed = time.monotonic() - stage_started
                log.write(
                    f"# stage={stage} status={status} "
                    f"elapsed_seconds={stage_elapsed:.3f}\n")
                log.flush()
                _say(
                    f"[{profile.artifact_stem}] {stage} "
                    f"{'done' if status == 0 else 'FAIL'} "
                    f"({stage_elapsed:.1f}s)")
                if status != 0:
                    message = f"{stage} exited with status {status}"
                    break
            else:
                failed_stage = ""
    except Exception as exc:  # keep other profiles running and report the cause
        message = f"{type(exc).__name__}: {exc}"
    finally:
        if sim_lease is not None:
            sim_lease.release()
        stem_lease.release()

    status = "PASS" if not failed_stage and not message else "FAIL"
    return JobResult(
        profile.path,
        profile.sim_stem,
        status,
        failed_stage,
        time.monotonic() - started,
        log_path,
        message,
    )


def _write_summary(path: Path, results: list[JobResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow([
            "profile", "stem", "status", "failed_stage",
            "elapsed_seconds", "log", "message",
        ])
        for result in results:
            writer.writerow([
                str(result.profile),
                result.stem,
                result.status,
                result.failed_stage,
                f"{result.elapsed_seconds:.3f}",
                str(result.log),
                result.message,
            ])
    os.replace(temporary, path)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="+", type=Path)
    parser.add_argument("--through", choices=STAGES, default="hud")
    parser.add_argument("--jobs", type=int)
    parser.add_argument("--sequential", action="store_true")
    parser.add_argument("--workers-per-job", type=int)
    parser.add_argument("--cpu", action="store_true", help="disable GPU sim")
    parser.add_argument("--force-reencode", action="store_true")
    parser.add_argument("--record-seconds", type=int)
    parser.add_argument("--stagger-seconds", type=float, default=0.0)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    if args.jobs is not None and args.jobs <= 0:
        parser.error("--jobs must be positive")
    if args.workers_per_job is not None and args.workers_per_job <= 0:
        parser.error("--workers-per-job must be positive")
    if args.record_seconds is not None and args.record_seconds <= 0:
        parser.error("--record-seconds must be positive")
    if args.stagger_seconds < 0:
        parser.error("--stagger-seconds must be non-negative")
    return args


def main() -> int:
    args = _parse_args()
    try:
        profiles = [load_profile(path) for path in args.profiles]
    except (OSError, ValueError) as exc:
        raise SystemExit(f"invalid profile: {exc}") from exc

    try:
        validate_distinct_stems(profiles)
    except ParallelRunError as exc:
        raise SystemExit(str(exc)) from exc

    requested_jobs = args.jobs or len(profiles)
    max_workers = 1 if args.sequential else min(requested_jobs, len(profiles))
    cpu_capacity = resource_tokens.resource_capacity("cpu")
    workers = (
        args.workers_per_job
        if args.workers_per_job is not None
        else max(1, cpu_capacity // max_workers)
    )
    if workers > cpu_capacity:
        raise SystemExit(
            f"--workers-per-job {workers} exceeds CPU token capacity "
            f"{cpu_capacity}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_dir = (
        args.run_dir.resolve()
        if args.run_dir is not None
        else (ROOT / "logs" / "parallel-run" / f"{stamp}-{os.getpid()}")
    )
    run_dir.mkdir(parents=True, exist_ok=False)
    summary = (
        args.summary.resolve()
        if args.summary is not None
        else run_dir / "summary.tsv"
    )
    options = JobOptions(
        through=args.through,
        workers=workers,
        use_gpu=not args.cpu,
        force_reencode=args.force_reencode,
        record_seconds=args.record_seconds,
        stagger_seconds=(
            0.0 if args.sequential else args.stagger_seconds),
        run_dir=run_dir,
    )
    _say(
        f"parallel run: profiles={len(profiles)} jobs={max_workers} "
        f"CPU={workers}/job of {cpu_capacity} GPU="
        f"{resource_tokens.resource_capacity('gpu')} "
        f"EMU={resource_tokens.resource_capacity('emu')} "
        f"through={args.through}")

    results: list[JobResult] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_run_job, index, profile, options): index
            for index, profile in enumerate(profiles)
        }
        for future in as_completed(futures):
            results.append(future.result())
    order = {profile.path: index for index, profile in enumerate(profiles)}
    results.sort(key=lambda result: order[result.profile])
    _write_summary(summary, results)
    for result in results:
        _say(
            f"{result.status}\t{result.profile.name}\t"
            f"{result.elapsed_seconds:.1f}s\t{result.message}")
    _say(f"summary: {summary}")
    return 0 if all(result.status == "PASS" for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
