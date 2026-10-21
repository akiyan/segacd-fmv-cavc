"""Checks for range omissions, stale parts, and unsafe loader builds."""
from contextlib import redirect_stderr, redirect_stdout
from fractions import Fraction
import io
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/"tools"))
import encode_config
import multipart
import multipart_build
import source_range


class MultipartTests(unittest.TestCase):
    def test_cli_resolves_profile_count_and_validates_overridden_selection(self):
        base = encode_config.load_profile(ROOT/"profiles/sonic-jam-op.toml")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"source.toml"
            data = {"schema_version": 5, **base.data, "multipart": {"parts": 3}}
            path.write_text(multipart.toml_text(data))
            for flags, expected in (([], (3, None)), (["--part", "2"], (3, 2)),
                                    (["--parts", "4", "--part", "4"], (4, 4))):
                with self.subTest(flags=flags):
                    args, _ = multipart.parse_args([str(path), *flags])
                    self.assertEqual((args.parts, args.part), expected)
            for flags, message in ((["--part", "4"], "1..3"),
                                   (["--parts", "2", "--part", "3"], "1..2"),
                                   (["--build-only", "--part", "1"], "cannot be combined")):
                with self.subTest(flags=flags), redirect_stderr(io.StringIO()) as error:
                    with self.assertRaises(SystemExit) as raised:
                        multipart.parse_args([str(path), *flags])
                    self.assertEqual(raised.exception.code, 2)
                    self.assertIn(message, error.getvalue())
            del data["multipart"]
            path.write_text(multipart.toml_text(data))
            with redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
                multipart.parse_args([str(path)])
            self.assertIn("set --parts N or [multipart].parts", error.getvalue())

    def test_profile_part_count_rejects_nonintegers_and_out_of_range_values(self):
        base = encode_config.load_profile(ROOT/"profiles/sonic-jam-op.toml")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"source.toml"
            for count in (0, 65, True, 3.0, "3"):
                path.write_text(multipart.toml_text({
                    "schema_version": 5, **base.data, "multipart": {"parts": count}}))
                with self.subTest(count=count), self.assertRaisesRegex(ValueError, "multipart.parts"):
                    encode_config.load_profile(path)

    def test_toml_and_cli_counts_keep_the_same_plan_and_part_profiles(self):
        # Moving a count into TOML must not change the packed-input profile
        # hashes or prevent an existing part from being reused.
        base = encode_config.load_profile(ROOT/"profiles/sonic-jam-op.toml")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/"source.nut"
            subprocess.run([
                "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=8x8:rate=30",
                "-frames:v", "6", "-c:v", "rawvideo", "-threads", "1", str(source),
            ], check=True)
            path = root/"source.toml"
            data = {"schema_version": 5, **base.data,
                    "source": {**base.data["source"], "path": str(source), "duration": "0.2"}}
            path.write_text(multipart.toml_text(data))
            (root/"logs").mkdir()
            with patch.object(multipart, "ROOT", root), redirect_stdout(io.StringIO()):
                args, profile = multipart.parse_args([str(path), "--parts", "3"])
                plan, profiles = multipart.prepare(profile, args.parts)
                originals = [p.path.read_bytes() for p in profiles]
                for default, flags in ((3, []), (4, ["--parts", "3"])):
                    data["multipart"] = {"parts": default}
                    path.write_text(multipart.toml_text(data))
                    args, profile = multipart.parse_args([str(path), *flags])
                    reused, profiles = multipart.prepare(profile, args.parts)
                    self.assertEqual(reused["stem"], plan["stem"])
                    self.assertEqual([p.path.read_bytes() for p in profiles], originals)

    @unittest.skipUnless(shutil.which("genisoimage") or shutil.which("mkisofs"), "ISO builder unavailable")
    def test_iso_verifier_rejects_directory_overflow_and_changed_payload(self):
        # Read a real ISO independently of its writer before mutating it.
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            staged = root/"disc"
            staged.mkdir()
            (staged/"PARTIP.BIN").write_bytes(b"selected module")
            iso = root/"test.iso"
            subprocess.run([shutil.which("genisoimage") or shutil.which("mkisofs"),
                            "-quiet", "-iso-level", "1", "-o", str(iso), str(staged)], check=True)
            multipart_build.verify_iso(iso, staged)
            original = iso.read_bytes()
            bad = bytearray(original)
            offset = 16*2048+156+10
            bad[offset:offset+8] = (65537).to_bytes(4, "little")+(65537).to_bytes(4, "big")
            iso.write_bytes(bad)
            with self.assertRaisesRegex(ValueError, "root directory"):
                multipart_build.verify_iso(iso, staged)
            iso.write_bytes(original.replace(b"selected module", b"replaced module"))
            with self.assertRaisesRegex(ValueError, "payload differs"):
                multipart_build.verify_iso(iso, staged)

    def test_completed_parts_reject_changed_streams_and_settings(self):
        # A completion marker must never authorize mixing another range or
        # modified packed bytes into an otherwise complete disc.
        base = encode_config.load_profile(ROOT/"profiles/sonic-jam-op.toml")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data = {"schema_version": 5, **base.data,
                    "source": {**base.data["source"], "start_frame": 0, "end_frame": 10}}
            path = root/"part.toml"
            path.write_text(multipart.toml_text(data))
            profile = encode_config.load_profile(path)
            plan = {"identity": {"source": "fixture", "parts": 3}}
            folder = root/profile.artifact_dir
            folder.mkdir(parents=True)
            with patch.object(multipart, "ROOT", root):
                self.assertIsNone(multipart.completed_part(plan, 1, profile))
                for name in multipart.PACKED_FILES:
                    (folder/name).write_bytes(name.encode())
                record = {"identity": multipart.part_identity(plan, 1, profile),
                          "files": {name: multipart.digest(folder/name) for name in multipart.PACKED_FILES}}
                multipart.write_json(folder/"multipart-complete.json", record)
                self.assertIsNotNone(multipart.completed_part(plan, 1, profile))
                with self.assertRaisesRegex(ValueError, "identity differs"):
                    multipart.completed_part(plan, 2, profile)
                (folder/"BODY.DAT").write_bytes(b"replaced by another run")
                with self.assertRaisesRegex(ValueError, "completed file changed"):
                    multipart.completed_part(plan, 1, profile)

    def test_uneven_sonic_partition_and_invalid_selection(self):
        self.assertEqual(multipart.split_frames(2714, 3),
                         [(0, 905), (905, 1810), (1810, 2714)])
        for frames, parts in ((100, 0), (100, 65), (5, 3), (83521, 1)):
            with self.subTest(frames=frames, parts=parts), self.assertRaises(ValueError):
                multipart.split_frames(frames, parts)
        result = subprocess.run([sys.executable, str(ROOT/"tools/multipart.py"),
                                 "missing.toml", "--parts", "3", "--part", "0"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("1-based", result.stderr)

    def test_fractional_rate_parts_reconstruct_actual_ffmpeg_frames(self):
        # Unique frame colors expose loss, duplication, or a timestamp reset.
        pixels = b"".join(bytes((i*5, i*3, i*7))*64 for i in range(35))
        def extract(bounds=None):
            return subprocess.check_output([
                "ffmpeg", "-v", "error", "-threads", "1", "-filter_threads", "1",
                "-f", "rawvideo", "-pixel_format", "rgb24", "-video_size", "8x8",
                "-framerate", "30", "-i", "pipe:0", "-vf",
                source_range.video_filter("setsar=1", "24000/1001", bounds),
                "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1",
            ], input=pixels)
        whole = extract()
        ranges = multipart.split_frames(len(whole)//192, 3)
        self.assertEqual(b"".join(extract(bounds) for bounds in ranges), whole)

    def test_fractional_audio_boundaries_reassemble_without_sample_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            original = directory/"source.wav"
            pcm = b"".join(struct.pack("<h", i % 32767) for i in range(16000))
            with wave.open(str(original), "wb") as stream:
                stream.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
                stream.writeframes(pcm)
            chunks = []
            for number, bounds in enumerate(multipart.split_frames(17, 3)):
                path = directory/f"{number}.wav"
                shutil.copyfile(original, path)
                source_range.trim_audio(path, bounds, "30000/1001")
                with wave.open(str(path), "rb") as stream:
                    chunks.append(stream.readframes(stream.getnframes()))
            end = int(Fraction(17*22050*1001, 30000))
            self.assertEqual(b"".join(chunks), pcm[:end*2])

    def test_profile_range_does_not_leak_into_a_later_single_movie(self):
        base = encode_config.load_profile(ROOT/"profiles/sonic-jam-op.toml")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/"part.toml"
            for bounds in ({"start_frame": 0}, {"start_frame": True, "end_frame": 5},
                           {"start_frame": 5, "end_frame": 5}):
                data = {"schema_version": 5, **base.data,
                        "source": {**base.data["source"], **bounds}}
                path.write_text(multipart.toml_text(data))
                with self.assertRaises(ValueError):
                    encode_config.load_profile(path)
            data["source"].update(start_frame=905, end_frame=1810)
            path.write_text(multipart.toml_text(data))
            part = encode_config.load_profile(path)
            env = {}
            encode_config.apply_profile_env(part, env)
            self.assertEqual((env["CBRSIM_START_FRAME"], env["CBRSIM_END_FRAME"]), ("905", "1810"))
            encode_config.apply_profile_env(base, env)
            self.assertNotIn("CBRSIM_START_FRAME", env)
            self.assertNotIn("CBRSIM_END_FRAME", env)


if __name__ == "__main__":
    unittest.main()
