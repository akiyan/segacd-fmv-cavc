from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import tmpfs_workspace as workspace


class TmpfsWorkspaceTests(unittest.TestCase):
    def env(self, root: Path):
        return patch.dict(os.environ, {
            "SEGACD_TMPFS_ROOT": str(root),
            "SEGACD_TMPFS_ALLOW_NON_TMPFS": "1",
            "SEGACD_TMPFS_MIN_FREE_GB": "0",
        })

    def test_direct_directory_path_and_live_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            lease = workspace.activate_directory(
                kind="sim", key="profile-abc")
            direct = workspace.managed_directory_path(
                kind="sim", key="profile-abc")
            self.assertEqual(direct, lease.entry / "data")
            self.assertFalse(direct.is_symlink())
            second = workspace.lease_managed_path(direct)
            self.assertIsNotNone(second)
            self.assertEqual(second.entry, lease.entry)
            second.release()
            record = json.loads(lease.marker.read_text(encoding="utf-8"))
            self.assertEqual(Path(record["entry"]), lease.entry)
            lease.release()
            self.assertFalse(lease.marker.exists())

    def test_managed_alias_lease_records_derived_space_reservation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            owner = workspace.activate_directory(
                kind="sim", key="profile-abc")
            derived = workspace.lease_managed_path(
                owner.entry / "data", required_bytes=123456)
            self.assertIsNotNone(derived)
            record = json.loads(derived.marker.read_text(encoding="utf-8"))
            self.assertEqual(record["required_bytes"], 123456)
            derived.release()
            owner.release()

    def test_completed_directory_reuses_only_matching_token(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            first = workspace.activate_directory(
                kind="sim", key="same-effective-settings",
                reuse_token="token-a")
            (first.entry / "data" / "kept.txt").write_text(
                "complete", encoding="utf-8")
            workspace.mark_directory_complete(
                first, reuse_token="token-a", details={"frames": 12})
            first.release()

            reused = workspace.activate_directory(
                kind="sim", key="same-effective-settings",
                reuse_token="token-a")
            self.assertTrue(reused.reused)
            self.assertEqual(
                (reused.entry / "data" / "kept.txt").read_text(
                    encoding="utf-8"),
                "complete")
            reused.release()

            reset = workspace.activate_directory(
                kind="sim", key="same-effective-settings",
                reuse_token="token-b")
            self.assertFalse(reset.reused)
            self.assertFalse((reset.entry / "data" / "kept.txt").exists())
            reset.release()

    def test_file_is_returned_as_direct_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            requested = Path("movie_analysis.mp4")
            actual, lease = workspace.allocate_file(
                requested, kind="analysis", key="profile-abc")
            actual.write_bytes(b"video")
            self.assertFalse(requested.exists())
            self.assertFalse(actual.is_symlink())
            self.assertEqual(actual.read_bytes(), b"video")
            lease.release()

    def test_file_command_returns_direct_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            source_lease = workspace.activate_directory(
                kind="record", key="source-recording")
            source = source_lease.entry / "data" / "source.bin"
            source.write_bytes(b"rendered")
            source_lease.release()
            requested = Path("rendered.mp4")
            actual = workspace.run_file_command(
                requested,
                kind="test-render",
                required_bytes=0,
                input_paths=[source],
                command=[
                    "sh", "-c",
                    "test \"$(find \"$1\" -name '*.json' | wc -l)\" -eq 2 "
                    "&& cp \"$2\" \"$3\"",
                    "sh",
                    str(workspace.ensure_root() / "leases"),
                    str(source),
                    "{output}",
                ],
            )
            self.assertFalse(requested.exists())
            self.assertEqual(actual.read_bytes(), b"rendered")
            self.assertFalse(workspace._active_entries(workspace.ensure_root()))

    def test_directory_command_holds_one_direct_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            actual = workspace.run_directory_command(
                kind="record",
                key="profile-abc",
                required_bytes=0,
                command=[
                    "sh", "-c",
                    "test -n \"$1\" && printf recorded > \"$1/capture.mkv\"",
                    "sh", "{output}",
                ],
            )
            self.assertEqual(
                (actual / "capture.mkv").read_text(encoding="utf-8"),
                "recorded",
            )
            self.assertFalse(workspace._active_entries(workspace.ensure_root()))

    def test_stale_lease_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            root = workspace.ensure_root()
            entry = root / "artifacts" / "old"
            entry.mkdir()
            marker = root / "leases" / "stale.json"
            marker.write_text(json.dumps({
                "pid": 99999999, "entry": str(entry),
            }), encoding="utf-8")
            self.assertEqual(workspace._active_entries(root), set())
            self.assertFalse(marker.exists())

    def test_low_space_evicts_oldest_inactive_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            root = workspace.ensure_root()
            old = root / "artifacts" / "old"
            new = root / "artifacts" / "new"
            old.mkdir()
            new.mkdir()
            os.utime(old, ns=(1, 1))
            os.utime(new, ns=(2, 2))
            usage = shutil._ntuple_diskusage
            with patch.object(
                    workspace.shutil, "disk_usage",
                    side_effect=[
                        usage(100, 90, 10),
                        usage(100, 70, 30),
                        usage(100, 70, 30),
                    ]):
                removed = workspace.evict_old_entries(20, root=root)
            self.assertEqual(removed, [old])
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())

    def test_user_quota_triggers_proactive_eviction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            root = workspace.ensure_root()
            old = root / "artifacts" / "old"
            new = root / "artifacts" / "new"
            old.mkdir()
            new.mkdir()
            os.utime(old, ns=(1, 1))
            os.utime(new, ns=(2, 2))
            usage = shutil._ntuple_diskusage
            with (
                patch.object(
                    workspace.shutil, "disk_usage",
                    return_value=usage(100, 10, 90),
                ),
                patch.object(
                    workspace,
                    "_user_quota_available_bytes",
                    side_effect=[10, 30, 30],
                ),
            ):
                removed = workspace.evict_old_entries(20, root=root)
            self.assertEqual(removed, [old])
            self.assertFalse(old.exists())
            self.assertTrue(new.exists())

    def test_workspace_lock_serializes_threads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            root = workspace.ensure_root()
            entered = threading.Event()

            def contender():
                with workspace._workspace_lock(root):
                    entered.set()

            with workspace._workspace_lock(root):
                thread = threading.Thread(target=contender)
                thread.start()
                time.sleep(0.05)
                self.assertFalse(entered.is_set())
            thread.join(timeout=2)
            self.assertTrue(entered.is_set())

    def test_required_bytes_are_published_in_live_lease(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            lease = workspace.activate_directory(
                kind="sim", key="reservation", required_bytes=123456)
            record = json.loads(lease.marker.read_text(encoding="utf-8"))
            self.assertEqual(record["required_bytes"], 123456)
            self.assertGreater(
                workspace._active_reservation_bytes(workspace.ensure_root()), 0)
            lease.release()

    def test_replacing_same_file_key_replaces_managed_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, self.env(Path(tmp) / "ram"):
            requested = Path("movie_analysis.mp4")
            first, first_lease = workspace.allocate_file(
                requested, kind="analysis", key="first")
            first.write_bytes(b"first")
            first_lease.release()
            second, second_lease = workspace.allocate_file(
                requested, kind="analysis", key="second")
            second.write_bytes(b"second")
            self.assertNotEqual(first, second)
            self.assertEqual(second.read_bytes(), b"second")
            second_lease.release()


if __name__ == "__main__":
    unittest.main()
