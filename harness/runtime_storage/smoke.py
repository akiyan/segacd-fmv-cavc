#!/usr/bin/env python3
"""Exercise selected disk roots, child processes, leases and numeric cache values."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from runtime_paths import scratch_root


CHILD = r'''
import json, os, shutil, subprocess, sys, tempfile
from pathlib import Path
import numpy as np
import resource_tokens as tokens
import tmpfs_workspace as workspace
from runtime_paths import workspace_root, scratch_root
from array_storage import ArrayStorage

root, scratch = workspace_root(), scratch_root()
assert root == Path(sys.argv[1]) and scratch == Path(sys.argv[2])
with tempfile.NamedTemporaryFile() as temp:
    assert Path(temp.name).parent == scratch
lease = workspace.activate_directory(kind="smoke", key="live")
payload = lease.entry / "data" / "keep.bin"
payload.write_bytes(b"preserve live artifact")
outsider = root / "unmanaged.txt"
outsider.write_text("not an artifact")
inactive = workspace.activate_directory(kind="smoke", key="inactive")
inactive_path = inactive.entry
inactive.release()
try:
    workspace.evict_old_entries(shutil.disk_usage(root).free + 1024 ** 2, root=root)
except workspace.TmpfsWorkspaceError:
    pass
else:
    raise AssertionError("impossible reservation accepted")
assert payload.read_bytes() == b"preserve live artifact"
assert outsider.exists() and not inactive_path.exists()
lease.release()

command = [sys.executable, str(Path(tokens.__file__)), "run", "--resource", "smoke",
           "--capacity", "1", "--no-wait", "--", sys.executable, "-c", "pass"]
with tokens.acquire_tokens("smoke", capacity=1):
    blocked = subprocess.run(command, capture_output=True)
    assert blocked.returncode == 75, blocked.stderr
subprocess.run(command, check=True)
assert tokens.resource_root() == root / "resources"

reference = np.arange(3 * 7 * 64, dtype=np.uint8).reshape(3, 7, 64)
with ArrayStorage() as storage:
    values = storage.empty(reference.shape, reference.dtype)
    values[:] = reference
    values[1] = values[0]
    reference[1] = reference[0]
    storage.settle()
    np.testing.assert_array_equal(values, reference)
    assert Path(values.filename).is_relative_to(scratch)
    del values
assert not list(scratch.glob("cavc-arrays-*"))
print(json.dumps({"workspace": str(root), "scratch": str(scratch), "result": "PASS"}))
'''


def main():
    # Spaces and non-ASCII exercise shell/CLI propagation, not only Path helpers.
    with tempfile.TemporaryDirectory(prefix="runtime smoke-日本語-", dir=scratch_root()) as temporary:
        directory = Path(temporary)
        workspace = directory / "artifacts disk"
        scratch = directory / "scratch disk"
        env = dict(os.environ)
        env.pop("SEGACD_RESOURCE_ROOT", None)
        env["CAVC_WORKSPACE_MIN_FREE_GB"] = "0"
        subprocess.run([
            str(ROOT / "tools/python.sh"),
            "--workspace-root", str(workspace), "--scratch-root", str(scratch),
            "--array-storage", "disk", "-c", CHILD, str(workspace), str(scratch),
        ], cwd=directory, env=env, check=True)


if __name__ == "__main__":
    main()
