#!/usr/bin/env python3
"""Archive a growing regular log and release archived tmpfs pages.

The writer retains its inode and byte offsets. Only complete, durably flushed
gzip members are punched out. The ordinary post-run compactor finalizes the
archive and restores its compact text log before downstream consumers read it.
"""
import argparse
import ctypes
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

CHUNK = 8 * 1024 * 1024


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--finish", action="store_true")
    parser.add_argument("--pid", type=int)
    args = parser.parse_args()
    log = args.input
    marker = Path(str(log) + ".stream.json")
    if args.finish:
        state = json.loads(marker.read_text())
        Path(state["stop"]).touch()
        while not Path(state["done"]).exists():
            try:
                os.kill(state["pid"], 0)
            except ProcessLookupError:
                raise RuntimeError("stream archiver exited without completion")
            time.sleep(0.2)
        return
    assert args.pid
    archive = Path(str(log) + ".stream.gz")
    stop = Path(str(log) + ".stream.stop")
    done = Path(str(log) + ".stream.done.json")
    assert not any(p.exists() for p in (marker, archive, stop, done))
    marker.write_text(json.dumps(dict(pid=os.getpid(), archive=str(archive),
                                     stop=str(stop), done=str(done))) + "\n")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fallocate.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_longlong,
                              ctypes.c_longlong]
    offset = 0
    digest = hashlib.sha256()
    with log.open("r+b", buffering=0) as source, archive.open("xb") as target:
        while True:
            finishing = stop.exists()
            # Retain the live tail, including normal-shutdown messages, for
            # the harness's pre-compaction checks.
            if not finishing and log.stat().st_size - offset < 2 * CHUNK:
                time.sleep(0.05)
                continue
            source.seek(offset)
            data = source.read(CHUNK)
            if data:
                target.write(gzip.compress(data, compresslevel=1, mtime=0))
                target.flush()
                os.fsync(target.fileno())
                digest.update(data)
                # Keep a partial filesystem page until the following member.
                end = (offset + len(data)) // 4096 * 4096
                begin = offset // 4096 * 4096
                if not finishing and end > begin and libc.fallocate(source.fileno(), 3, begin,
                                                 end - begin) != 0:
                    raise OSError(ctypes.get_errno(), "punch archived pages")
                offset += len(data)
                continue
            if stop.exists():
                break
            time.sleep(0.05)
    done.write_text(json.dumps(dict(raw_bytes=offset, sha256=digest.hexdigest(),
                                   gzip_bytes=archive.stat().st_size)) + "\n")


if __name__ == "__main__":
    main()
