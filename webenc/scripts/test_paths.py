"""Shared paths for native/browser reference fixtures."""
import os
from pathlib import Path
from runtime_paths import workspace_root

QA_ROOT = Path(os.environ.get("WEBENC_TEST_OUTPUT") or workspace_root() / "webenc-qa")
KERNEL_ROOT = Path(os.environ.get("WEBENC_KERNEL_OUTPUT") or workspace_root() / "webenc-kernel-test")
