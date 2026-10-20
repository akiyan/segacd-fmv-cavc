"""Stage-scoped numeric caches with optional file backing.

Disk backing changes allocation, never array values or encoder settings. Use a
disk scratch root to save physical RAM; a tmpfs scratch root still uses RAM.
"""

from __future__ import annotations

import tempfile
import weakref

import numpy as np

from runtime_paths import array_storage, scratch_root


class ArrayStorage:
    def __init__(self):
        self.mode = array_storage()
        self._directory = None
        self._arrays = []

    def __enter__(self):
        if self.mode == "disk":
            self._directory = tempfile.TemporaryDirectory(
                prefix="cavc-arrays-", dir=scratch_root())
        print(f"array cache: {self.mode}" + (
            f" ({self._directory.name})" if self._directory else ""), flush=True)
        return self

    def empty(self, shape, dtype):
        if self._directory is None:
            return np.empty(shape, dtype=dtype)
        from pathlib import Path
        path = Path(self._directory.name) / f"array-{len(self._arrays)}.bin"
        array = np.memmap(path, mode="w+", shape=shape, dtype=dtype)
        # Do not keep an otherwise dead stage cache alive through this owner.
        self._arrays.append(weakref.ref(array))
        return array

    def settle(self):
        """Flush completed writes and let the OS reclaim their cached pages."""
        import mmap
        for reference in self._arrays:
            array = reference()
            if array is not None:
                array.flush()
                if hasattr(array._mmap, "madvise") and hasattr(mmap, "MADV_DONTNEED"):
                    try:
                        array._mmap.madvise(mmap.MADV_DONTNEED)
                    except OSError:
                        pass  # Reclaim is optional; flushed values remain valid.

    def __exit__(self, *_exc):
        # No forced mmap.close(): views may outlive the owner during unwinding.
        # Unix removes the names immediately and frees bytes after the last view.
        if self._directory is not None:
            self._directory.cleanup()
