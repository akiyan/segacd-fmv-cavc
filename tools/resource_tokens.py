#!/usr/bin/env python3
"""Cross-process resource tokens and profile-stem exclusion.

The locks are ordinary Linux ``flock`` locks.  Python callers use
``acquire_tokens`` / ``acquire_stem`` and shell callers use the ``run`` /
``run-stem`` subcommands.  Locks disappear automatically when their owning
process exits, including abnormal exits.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Iterable


DEFAULT_ROOT = Path("/dev/shm/segacd-fmv-ttrc/resources")
HELD_STEMS_ENV = "SEGACD_HELD_STEM_LOCKS"


class ResourceTokenError(RuntimeError):
    pass


class ResourceBusyError(ResourceTokenError):
    pass


def resource_root() -> Path:
    root = Path(os.environ.get(
        "SEGACD_RESOURCE_ROOT", str(DEFAULT_ROOT))).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def available_cpu_count() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except AttributeError:
        return max(1, os.cpu_count() or 1)


def resource_capacity(resource: str) -> int:
    env_names = {
        "cpu": "SEGACD_CPU_TOKENS",
        "gpu": "SEGACD_GPU_TOKENS",
        "emu": "SEGACD_EMU_TOKENS",
    }
    defaults = {
        "cpu": max(1, available_cpu_count() - 2),
        "gpu": 1,
        "emu": 2,
    }
    if resource not in env_names:
        raise ResourceTokenError(
            f"capacity is required for custom resource {resource!r}")
    raw = os.environ.get(env_names[resource], str(defaults[resource]))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ResourceTokenError(
            f"{env_names[resource]} must be an integer: {raw!r}") from exc
    if value <= 0:
        raise ResourceTokenError(
            f"{env_names[resource]} must be positive: {value}")
    return value


def requested_cpu_workers(*, limit: int | None = None) -> int:
    """Return the worker count one CPU-heavy stage should reserve and use."""

    capacity = resource_capacity("cpu")
    raw = os.environ.get("CBRSIM_WORKERS", str(capacity))
    try:
        requested = int(raw)
    except ValueError as exc:
        raise ResourceTokenError(
            f"CBRSIM_WORKERS must be an integer: {raw!r}") from exc
    if requested <= 0:
        raise ResourceTokenError(
            f"CBRSIM_WORKERS must be positive: {requested}")
    requested = min(requested, capacity)
    if limit is not None:
        requested = min(requested, max(1, int(limit)))
    return requested


def _resource_slug(resource: str) -> str:
    readable = re.sub(r"[^A-Za-z0-9._-]+", "-", resource).strip("-._")
    readable = (readable or "resource")[:48]
    digest = hashlib.sha256(resource.encode("utf-8")).hexdigest()[:12]
    return f"{readable}-{digest}"


def _resource_dir(resource: str, root: Path) -> Path:
    directory = root / _resource_slug(resource)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _open_locked(path: Path, *, blocking: bool) -> int | None:
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    flags = fcntl.LOCK_EX
    if not blocking:
        flags |= fcntl.LOCK_NB
    try:
        fcntl.flock(descriptor, flags)
    except BlockingIOError:
        os.close(descriptor)
        return None
    return descriptor


def _try_lock_all_slots(directory: Path, capacity: int) -> list[int] | None:
    descriptors: list[int] = []
    for index in range(capacity):
        descriptor = _open_locked(
            directory / f"slot-{index:04d}.lock", blocking=False)
        if descriptor is None:
            for held in descriptors:
                os.close(held)
            return None
        descriptors.append(descriptor)
    return descriptors


def _ensure_capacity(directory: Path, capacity: int) -> None:
    meta_path = directory / "capacity.json"
    meta_lock = _open_locked(directory / "capacity.lock", blocking=True)
    assert meta_lock is not None
    try:
        previous = None
        if meta_path.is_file():
            try:
                previous = int(json.loads(
                    meta_path.read_text(encoding="utf-8"))["capacity"])
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                previous = None
        if previous not in (None, capacity):
            descriptors = _try_lock_all_slots(
                directory, max(previous, capacity))
            if descriptors is None:
                raise ResourceTokenError(
                    f"resource capacity changed while tokens are active: "
                    f"{previous} -> {capacity} ({directory.name})")
            for descriptor in descriptors:
                os.close(descriptor)
        temporary = directory / f"capacity.{os.getpid()}.tmp"
        temporary.write_text(
            json.dumps({"capacity": capacity}, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, meta_path)
    finally:
        os.close(meta_lock)


class TokenLease:
    def __init__(
        self,
        resource: str,
        capacity: int,
        descriptors: Iterable[int] = (),
        *,
        reentrant: bool = False,
    ):
        self.resource = resource
        self.capacity = capacity
        self._descriptors = list(descriptors)
        self.reentrant = reentrant

    @property
    def count(self) -> int:
        return len(self._descriptors)

    def release(self) -> None:
        while self._descriptors:
            os.close(self._descriptors.pop())

    def __enter__(self) -> "TokenLease":
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.release()


def acquire_tokens(
    resource: str,
    *,
    count: int = 1,
    capacity: int | None = None,
    wait: bool = True,
    timeout: float | None = None,
    poll_interval: float = 0.05,
    root: Path | None = None,
) -> TokenLease:
    """Acquire exactly ``count`` slots without holding a partial reservation."""

    capacity = resource_capacity(resource) if capacity is None else int(capacity)
    count = int(count)
    if capacity <= 0 or count <= 0 or count > capacity:
        raise ResourceTokenError(
            f"invalid {resource} token request: count={count}, capacity={capacity}")
    root = (root or resource_root()).resolve()
    root.mkdir(parents=True, exist_ok=True)
    directory = _resource_dir(resource, root)
    _ensure_capacity(directory, capacity)
    started = time.monotonic()
    while True:
        descriptors: list[int] = []
        for index in range(capacity):
            descriptor = _open_locked(
                directory / f"slot-{index:04d}.lock", blocking=False)
            if descriptor is not None:
                descriptors.append(descriptor)
                if len(descriptors) == count:
                    return TokenLease(resource, capacity, descriptors)
        for descriptor in descriptors:
            os.close(descriptor)
        if not wait:
            raise ResourceBusyError(
                f"resource busy: {resource} needs {count}/{capacity} tokens")
        if timeout is not None and time.monotonic() - started >= timeout:
            raise ResourceBusyError(
                f"resource timeout: {resource} needs {count}/{capacity} tokens")
        time.sleep(max(0.001, poll_interval))


def stem_lock_id(stem: str) -> str:
    return hashlib.sha256(stem.encode("utf-8")).hexdigest()[:24]


def _held_stem_ids() -> set[str]:
    return {
        value for value in os.environ.get(HELD_STEMS_ENV, "").split(",")
        if value
    }


def held_stem_environment(stem: str, env: dict[str, str] | None = None) -> dict[str, str]:
    result = dict(os.environ if env is None else env)
    held = {
        value for value in result.get(HELD_STEMS_ENV, "").split(",")
        if value
    }
    held.add(stem_lock_id(stem))
    result[HELD_STEMS_ENV] = ",".join(sorted(held))
    return result


def acquire_stem(
    stem: str,
    *,
    wait: bool = False,
    root: Path | None = None,
) -> TokenLease:
    """Acquire the one-owner lock for a complete media artifact stem."""

    identifier = stem_lock_id(stem)
    if identifier in _held_stem_ids():
        return TokenLease(
            f"stem:{stem}", 1, reentrant=True)
    return acquire_tokens(
        f"stem:{stem}", count=1, capacity=1, wait=wait, root=root)


def _profile_stem(config: Path) -> str:
    from encode_config import load_profile
    return load_profile(config).sim_stem


def _run_command(command: list[str], *, env: dict[str, str] | None = None) -> int:
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise ResourceTokenError("command is required after --")
    return subprocess.run(command, env=env, check=False).returncode


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    run = subparsers.add_parser(
        "run", help="run a shell command while holding resource tokens")
    run.add_argument("--resource", required=True)
    run.add_argument("--count", type=int, default=1)
    run.add_argument("--capacity", type=int)
    run.add_argument("--no-wait", action="store_true")
    run.add_argument("--timeout", type=float)
    run.add_argument("command", nargs=argparse.REMAINDER)

    stem = subparsers.add_parser(
        "run-stem", help="run a command under one profile stem lock")
    source = stem.add_mutually_exclusive_group(required=True)
    source.add_argument("--stem")
    source.add_argument("--config", type=Path)
    stem.add_argument("--wait", action="store_true")
    stem.add_argument("command", nargs=argparse.REMAINDER)

    workers = subparsers.add_parser(
        "cpu-workers",
        help="print the CPU worker count implied by capacity and CBRSIM_WORKERS",
    )
    workers.add_argument("--limit", type=int)
    return parser.parse_args()


def _main() -> int:
    args = _parse_args()
    try:
        if args.action == "run":
            with acquire_tokens(
                args.resource,
                count=args.count,
                capacity=args.capacity,
                wait=not args.no_wait,
                timeout=args.timeout,
            ):
                return _run_command(args.command)
        if args.action == "run-stem":
            stem = args.stem or _profile_stem(args.config)
            with acquire_stem(stem, wait=args.wait):
                return _run_command(
                    args.command, env=held_stem_environment(stem))
        if args.action == "cpu-workers":
            print(requested_cpu_workers(limit=args.limit))
            return 0
    except ResourceBusyError as exc:
        print(str(exc), file=os.sys.stderr)
        return 75
    except ResourceTokenError as exc:
        print(str(exc), file=os.sys.stderr)
        return 2
    raise AssertionError(args.action)


if __name__ == "__main__":
    raise SystemExit(_main())
