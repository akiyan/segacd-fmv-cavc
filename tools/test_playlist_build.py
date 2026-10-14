"""Authenticate staged bytes against real ISO9660 directory records."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import playlist_build


@unittest.skipUnless(shutil.which("mkisofs") or shutil.which("genisoimage"), "ISO builder unavailable")
class ISOAuthentication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.stage = root / "stage"
        self.stage.mkdir()
        (self.stage / "MENUIP.BIN").write_bytes(b"launcher" * 400)
        (self.stage / "V0000BOD.DAT").write_bytes(b"body" * 2000)
        self.iso = root / "test.iso"
        subprocess.run([shutil.which("mkisofs") or shutil.which("genisoimage"),
                        "-quiet", "-o", str(self.iso), str(self.stage)], check=True)

    def test_authenticates_all_staged_bytes(self):
        playlist_build.verify_iso(self.iso, self.stage)
        (self.stage / "MENUIP.BIN").write_bytes(b"modified" * 400)
        with self.assertRaisesRegex(ValueError, "byte mismatch"):
            playlist_build.verify_iso(self.iso, self.stage)

    def test_missing_staged_member(self):
        (self.stage / "MISSING.DAT").write_bytes(b"missing")
        with self.assertRaisesRegex(ValueError, "missing ISO file"):
            playlist_build.verify_iso(self.iso, self.stage)

    def test_truncated_directory(self):
        data = self.iso.read_bytes()
        root_lba = int.from_bytes(data[16 * 2048 + 158:16 * 2048 + 162], "little")
        self.iso.write_bytes(data[:root_lba * 2048 + 5])
        with self.assertRaisesRegex(ValueError, "truncated ISO root"):
            playlist_build.verify_iso(self.iso, self.stage)

    def test_corrupt_directory_record(self):
        data = bytearray(self.iso.read_bytes())
        root_lba = int.from_bytes(data[16 * 2048 + 158:16 * 2048 + 162], "little")
        data[root_lba * 2048] = 1
        self.iso.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "invalid ISO directory"):
            playlist_build.verify_iso(self.iso, self.stage)

    def test_loader_big_endian_extent_must_match_verifier_extent(self):
        data = bytearray(self.iso.read_bytes())
        root_lba = int.from_bytes(data[16 * 2048 + 158:16 * 2048 + 162], "little")
        offset = root_lba * 2048
        while data[offset + 25] & 2:
            offset += data[offset]
        data[offset + 9] ^= 1
        self.iso.write_bytes(data)
        with self.assertRaisesRegex(ValueError, "endian directory fields disagree"):
            playlist_build.verify_iso(self.iso, self.stage)

class PackedRebuildAuthentication(unittest.TestCase):
    def setUp(self):
        import json
        import encode_config
        import playlist
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        repo = Path(__file__).resolve().parents[1]
        old = self.root / 'source.toml'
        old.write_bytes((repo / 'profiles/sonic-jam-op.toml').read_bytes())
        self.prior = encode_config.load_profile(old)
        source = self.root / self.prior.section('source')['path']
        source.parent.mkdir(parents=True)
        source.write_bytes(b'fixture source')
        self.item = playlist.Item('jam', old, {})
        self.profile = self.prior
        self.packed = self.root / 'out' / self.prior.artifact_stem
        self.packed.mkdir(parents=True)
        files, palettes = {}, {}
        for name, key in [('HEADER.DAT', 'V0000HDR.DAT'), ('BODY.DAT', 'V0000BOD.DAT'), ('paltab.bin', 'paltab.bin'), ('palidx.bin', 'palidx.bin')]:
            p = self.packed / name
            p.write_bytes(name.encode())
            (palettes if name.endswith('.bin') else files)[key] = dict(bytes=p.stat().st_size, sha256=playlist_build.digest(p))
        self.baseline = dict(items=[dict(id='jam',source_profile=str(old),effective_profile=str(old),profile_sha256=self.prior.sha256,source_sha256=playlist_build.digest(source),overrides={},files=files,palette_files=palettes)])

    def test_authenticates_bytes_without_sim(self):
        playlist_build.reuse_packed(self.root, self.item, self.profile, self.baseline)
        for name in ['HEADER.DAT', 'BODY.DAT', 'paltab.bin', 'palidx.bin']:
            p = self.packed / name
            original = p.read_bytes()
            p.write_bytes(b'x' * len(original))
            with self.assertRaisesRegex(ValueError, 'baseline bytes changed'):
                playlist_build.reuse_packed(self.root, self.item, self.profile, self.baseline)
            p.write_bytes(original)

    def test_rejects_changed_source(self):
        (self.root / self.prior.section('source')['path']).write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'source bytes changed'):
            playlist_build.reuse_packed(self.root, self.item, self.profile, self.baseline)

    def test_rejects_changed_encoding(self):
        import encode_config
        import playlist
        data = dict(self.prior.data)
        data['encoder'] = dict(data['encoder'], cold_cap=170)
        changed = self.root / 'changed.toml'
        changed.write_text(playlist._toml(dict(schema_version=encode_config.SCHEMA_VERSION, **data)))
        with self.assertRaisesRegex(ValueError, 'encoded settings changed'):
            playlist_build.reuse_packed(self.root, self.item, encode_config.load_profile(changed), self.baseline)


if __name__ == "__main__":
    unittest.main()
