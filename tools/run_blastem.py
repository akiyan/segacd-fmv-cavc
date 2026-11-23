#!/usr/bin/env python3
"""Run a Sega CD disc with standalone BlastEm under run_headless.sh."""

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import wave
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BINARY = ROOT / "vendor" / "blastem" / "blastem"
DEFAULT_INPUT = ROOT / "tools" / "blastem_start.txt"
REGIONS = {
    "jp": ("J", "jp_mcd2_9212.bin"),
    "us": ("U", "us_scd1_9210.bin"),
}
CUE_FILE = re.compile(r'^FILE\s+"([^"]+)"\s+\S+$', re.IGNORECASE)


def disc_files(disc: Path) -> list[Path]:
    if disc.suffix.lower() == ".iso":
        return [disc]
    if disc.suffix.lower() != ".cue":
        raise ValueError("BlastEm expects a .cue or .iso disc")
    tracks = []
    for line in disc.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and line.split(maxsplit=1)[0].upper() == "FILE":
            match = CUE_FILE.fullmatch(line)
            if match is None:
                raise ValueError(f"invalid FILE line in {disc}: {line}")
            tracks.append((disc.parent / match[1]).resolve(strict=True))
    if not tracks:
        raise ValueError(f"no track files in {disc}")
    return list(dict.fromkeys([disc, *tracks]))


def identity(path: Path) -> dict[str, str]:
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256")
    return {"path": str(path), "sha256": digest.hexdigest()}


def write_receipt(path: Path, data: dict) -> None:
    pending = path.with_suffix(".tmp")
    pending.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    pending.replace(path)


def check_fork(binary: Path, env: dict[str, str]) -> None:
    try:
        result = subprocess.run([str(binary), "-h"], env=env, capture_output=True,
                                text=True, errors="replace", timeout=5, check=False)
    except subprocess.TimeoutExpired as exc:
        raise ValueError(f"BlastEm capability check timed out: {binary}") from exc
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ValueError(f"BlastEm capability check failed for {binary}: {detail}")
    options = {line.split()[0] for line in result.stdout.splitlines() if line.strip()}
    if not {"--record", "--record-input", "--record-no-video"} <= options:
        raise ValueError(f"{binary} lacks the akiyan/blastem offline recording options")


def run(args: argparse.Namespace) -> None:
    region = os.environ.get("BIOS_REGION", "jp")
    if region not in REGIONS:
        raise ValueError(f"BIOS_REGION must be jp or us: {region}")
    region_flag, bios_name = REGIONS[region]
    bios = Path(os.environ.get("BIOS_IMAGE", ROOT / "original" / bios_name)).resolve(strict=True)
    requested_binary = os.environ.get("BLASTEM", str(DEFAULT_BINARY))
    executable = shutil.which(requested_binary)
    if executable is None:
        raise ValueError(f"BlastEm executable not found: {requested_binary}. "
                         "Build the akiyan fork from README.md or set BLASTEM.")
    binary = Path(executable).resolve()
    disc = args.disc.absolute()
    inputs = {
        "disc": [identity(path) for path in disc_files(disc)],
        "bios": identity(bios),
        "binary": identity(binary),
    }
    capture = args.record is not None or args.no_video
    input_script = (args.input_script or DEFAULT_INPUT).resolve(strict=True) if capture else None
    if input_script is not None:
        inputs["input_script"] = identity(input_script)

    tag = args.tag or disc.stem
    if Path(tag).name != tag or tag in {".", ".."} or any(char in tag for char in "\r\n"):
        raise ValueError(f"invalid output tag: {tag}")
    scratch = Path(os.environ.get("CAVC_SCRATCH_ROOT", ROOT / "tmp"))
    outdir = Path(os.environ.get("OUTDIR", scratch / disc.stem / "record")).resolve()
    outdir.mkdir(parents=True, exist_ok=True)
    output = args.record.absolute() if args.record else None
    if output is not None and (output.exists() or output.is_symlink()):
        raise ValueError(f"recording already exists: {output}")
    run_dir = Path(tempfile.mkdtemp(prefix=f"blastem_{tag}.", dir=outdir))
    logs = ROOT / "logs"
    logs.mkdir(exist_ok=True)
    receipt_path = logs / f"{run_dir.name}.json"
    log_path = run_dir / "blastem.log"
    config_dir = run_dir / "config"
    data_dir = run_dir / "data"
    saves = run_dir / "saves"
    (config_dir / "blastem").mkdir(parents=True)
    data_dir.mkdir()
    saves.mkdir()
    if any(char in str(bios) for char in "\r\n"):
        raise ValueError("BIOS_IMAGE path contains a line break")
    (config_dir / "blastem" / "blastem.cfg").write_text(
        f"system {{\n scd_bios_{region} {bios}\n}}\n", encoding="utf-8"
    )
    env = os.environ.copy()
    env.pop("BLASTEM_CTRL_SOCK", None)
    env.pop("BLASTEM_STATE_DIR", None)
    env.update(
        XDG_CONFIG_HOME=str(config_dir),
        XDG_DATA_HOME=str(data_dir),
        BLASTEM_SAVE_DIR=str(saves),
        BLASTEM_NO_GUI="1",
        SDL_VIDEODRIVER="dummy",
        SDL_AUDIODRIVER="dummy",
    )
    events = run_dir / "vdp.blastel" if args.vdp_event_log else None
    prefix = run_dir / "capture"
    command = [str(binary), "-r", region_flag]
    if events is not None:
        command.extend(("-e", str(events)))
    if capture:
        command.extend(("--record", str(prefix), str(args.max_frames)))
        command.extend(("--record-input", str(input_script)))
        if args.no_video:
            command.append("--record-no-video")
    else:
        command.extend(("-b", str(args.max_frames)))
    command.append(str(disc))
    receipt = {
        "backend": "blastem",
        "region": region,
        "inputs": inputs,
        "command": command,
        "max_frames": args.max_frames,
        "log": str(log_path),
        "vdp_event_log": str(events) if events is not None else None,
        "complete": False,
    }
    write_receipt(receipt_path, receipt)
    print(f"BLASTEM_RECEIPT={receipt_path}", flush=True)
    print(f"BLASTEM_LOG={log_path}", flush=True)
    check_fork(binary, env)
    with log_path.open("wb") as log, subprocess.Popen(
        command, env=env, stdout=log, stderr=subprocess.STDOUT
    ) as process:
        receipt["pid"] = process.pid
        write_receipt(receipt_path, receipt)
        try:
            process.wait()
        except KeyboardInterrupt:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise
        finally:
            receipt["exit_status"] = process.returncode
            write_receipt(receipt_path, receipt)
    if process.returncode:
        raise ValueError(f"BlastEm exited with status {process.returncode}; see {log_path}")
    if events is not None:
        with events.open("rb") as handle:
            if not handle.read(8).startswith(b"BLSTEL"):
                raise ValueError(f"BlastEm did not produce a BLSTEL event log: {events}")
        print(f"VDP_EVENT_LOG={events}", flush=True)
    if capture:
        meta_path = prefix.with_suffix(".json")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if (metadata.get("complete") is not True or metadata.get("frames") != args.max_frames
                or metadata.get("video") is not (output is not None)):
            raise ValueError(f"incomplete or unexpected BlastEm capture metadata: {meta_path}")
        receipt["capture_metadata"] = str(meta_path)
    if args.no_video:
        wav_path = prefix.with_suffix(".wav")
        with wave.open(str(wav_path), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()) != (
                    2, 2, metadata.get("sample_rate"), metadata.get("audio_samples")) or not audio.getnframes():
                raise ValueError(f"BlastEm WAV does not match capture metadata: {wav_path}")
        receipt["audio_recording"] = str(wav_path)
        print(f"AUDIO_RECORDING={wav_path}", flush=True)
    if output is not None:
        with log_path.open("ab") as log:
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/mux_blastem_capture.py"), str(prefix), str(output)],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=False,
            )
        if result.returncode:
            raise ValueError(f"BlastEm lossless mux failed; see {log_path}")
        receipt["raw_recording"] = str(output)
        for path in run_dir.glob("capture*.apng"):
            path.unlink()
        prefix.with_suffix(".wav").unlink()
        print(f"RECORDING={output}", flush=True)
    receipt["complete"] = True
    write_receipt(receipt_path, receipt)


def main() -> int:
    parser = argparse.ArgumentParser(prog="run_headless.sh",
                                     description=__doc__)
    parser.add_argument("disc", type=Path)
    parser.add_argument("--tag")
    parser.add_argument("--max-frames", type=int, required=True)
    capture = parser.add_mutually_exclusive_group()
    capture.add_argument("--record", type=Path, metavar="OUTPUT_MKV")
    capture.add_argument("--no-video", action="store_true", help="retain WAV and metadata without video")
    parser.add_argument("--input-script", type=Path, metavar="FILE")
    parser.add_argument("--vdp-event-log", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_frames <= 10_000_000:
        parser.error("--max-frames must be in 1..10000000")
    if args.input_script and not (args.record or args.no_video):
        parser.error("--input-script requires --record or --no-video")
    signal.signal(signal.SIGTERM, signal.default_int_handler)
    try:
        run(args)
    except (OSError, ValueError, wave.Error) as error:
        print(f"run_headless (BlastEm): {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
