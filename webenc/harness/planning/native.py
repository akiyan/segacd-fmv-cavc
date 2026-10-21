"""Time a fresh native encode and verified pack on shared normalized inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    parser.add_argument("revision")
    args = parser.parse_args()
    job = args.job.resolve()
    tools = job / "revisions" / args.revision / "tools"
    target = job / "runs" / f"native-{args.revision}"
    if target.exists():
        raise SystemExit(f"Refusing to overwrite a previous run: {target}")
    sys.path.insert(0, str(ROOT / "tools"))
    from tmpfs_workspace import lease_managed_path
    lease = lease_managed_path(job, required_bytes=4 * 1024**3)
    if lease is None:
        raise SystemExit("The input must belong to the selected managed workspace")
    try:
        manifest = json.loads((job / "inputs/manifest.json").read_text())
        target.mkdir(parents=True)
        for name in ("master", "raw"):
            shutil.copytree(job / "inputs" / name, target / name, copy_function=os.link)
        shutil.copyfile(job / "inputs/audio_22k05_s16_mono.wav",
                        target / "audio_22k05_s16_mono.wav")
        for key in list(os.environ):
            if key.startswith("CBRSIM_"):
                del os.environ[key]
        env = manifest["environment"].copy()
        env.pop("CBRSIM_CONFIG", None)
        env.update(CBRSIM_OUT=str(target), CBRSIM_REUSE="1",
                   CBRSIM_GPU="0", CBRSIM_WORKERS="1",
                   CBRSIM_MASTER_VF="setsar=1", CBRSIM_RAW_VF="setsar=1")
        os.environ.update(env)
        sys.path.insert(0, str(tools))
        sys.path.insert(1, str(ROOT / "webenc/harness/equivalence"))
        sys.argv = ["planner-benchmark"]
        import sim
        from encode_config import EncodeProfile
        from prebuffer_trace import install as install_prebuffer
        from stages import install as install_stages
        import resource_tokens
        # Common provenance path, matching the production browser adapter.
        sim.CONFIG_PROFILE = EncodeProfile(
            Path("/profiles") / manifest["profile"],
            manifest["profileSections"], manifest["profileSha256"])
        install_prebuffer(sim)
        install_stages(sim, target, cache=False)
        with resource_tokens.acquire_stem(sim.CONFIG_PROFILE.sim_stem):
            started = time.perf_counter()
            anchors = set()
            while True:
                try:
                    sim.main(demoted_fade_anchors=frozenset(anchors))
                    break
                except sim.FadeDeadlineInfeasible as error:
                    if error.anchor in anchors:
                        raise
                    anchors.add(error.anchor)
                    import gc
                    gc.enable()
            encode_seconds = time.perf_counter() - started
            import pack_stream
            from pack_validation import install as install_pack
            install_pack(pack_stream)
            sys.argv = [
                "pack_stream", "--dec-log", str(target / "decisions.pkl"),
                "--audio", str(job / "inputs/audio_22k05_s16_mono.wav"),
                "--sp-extension", str(job / "inputs/sp-extension.bin"),
                "--output", str(target / "packed/MOVIE.DAT"), "--verify",
            ]
            started = time.perf_counter()
            pack_stream.main()
            pack_seconds = time.perf_counter() - started
            from replay import render
            render(target)
        receipt = {
            "completed": True, "runtime": "native", "revision": args.revision,
            "frames": manifest["frames"], "encode_seconds": encode_seconds,
            "pack_seconds": pack_seconds, "demoted_fade_anchors": sorted(anchors),
            "scope": "fresh CPU/one-worker encode on normalized full-profile inputs",
            "source_sha256": manifest["sourceSha256"],
            "profile_sha256": manifest["profileSha256"],
            "encoder_sha256": hashlib.sha256(b"".join(
                file.name.encode() + file.read_bytes()
                for file in sorted(tools.glob("*.py")))).hexdigest(),
        }
        (target / "benchmark.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
    finally:
        lease.release()


if __name__ == "__main__":
    main()
