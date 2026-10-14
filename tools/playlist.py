#!/usr/bin/env python3
"""Strict profile references and isolated effective profiles for playlists."""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import re
import tomllib
from pathlib import Path

import encode_config

OVERRIDES = {
    "encoder": {"cold_cap", "auto_scroll"},
    "palette": {"core_boost_steps"},
}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Assembly indexes the generated long tables with a signed word displacement.
MAX_ITEMS = 8192


@dataclasses.dataclass(frozen=True)
class Item:
    id: str
    profile: Path
    overrides: dict


@dataclasses.dataclass(frozen=True)
class Playlist:
    path: Path
    items: tuple[Item, ...]
    youtube: dict = dataclasses.field(default_factory=dict)

    @property
    def stem(self) -> str:
        return self.path.stem


def load(path: str | Path) -> Playlist:
    path = Path(path).resolve()
    data = tomllib.loads(path.read_text())
    if not {"schema_version", "playlist"} <= set(data) or set(data) - {"schema_version", "playlist", "youtube"} or type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise ValueError("playlist requires schema_version = 1 and [playlist]")
    youtube = data.get("youtube", {})
    if not isinstance(youtube, dict) or set(youtube) - {"playback_title"}:
        raise ValueError("playlist [youtube] accepts only playback_title")
    if youtube and (not isinstance(youtube.get("playback_title"), str) or not 1 <= len(youtube["playback_title"].strip()) <= 100):
        raise ValueError("playlist playback_title must contain 1..100 characters")
    if not IDENTIFIER.fullmatch(path.stem):
        raise ValueError("invalid playlist filename")
    section = data["playlist"]
    if not isinstance(section, dict) or set(section) != {"items"}:
        raise ValueError("[playlist] requires only an items array")
    entries = section["items"]
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ITEMS:
        raise ValueError(f"playlist must contain 1..{MAX_ITEMS} items")
    result = []
    seen = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {"id", "profile", "overrides"}:
            raise ValueError("invalid playlist item keys")
        identifier = entry.get("id")
        reference = entry.get("profile")
        if not isinstance(identifier, str) or not IDENTIFIER.fullmatch(identifier) or identifier in seen:
            raise ValueError("playlist item id must be a unique filename-safe string")
        if not isinstance(reference, str) or not reference:
            raise ValueError(f"{identifier}: profile is required")
        source = (path.parent / reference).resolve()
        base = encode_config.load_profile(source)  # Rejects nested playlists too.
        overrides = entry.get("overrides", {})
        if not isinstance(overrides, dict):
            raise ValueError(f"{identifier}: overrides must be a table")
        for name, values in overrides.items():
            if name not in OVERRIDES or not isinstance(values, dict) or set(values) - OVERRIDES[name]:
                raise ValueError(f"{identifier}: unsupported overrides in {name}")
        seen.add(identifier)
        result.append(Item(identifier, base.path, copy.deepcopy(overrides)))
    return Playlist(path, tuple(result), youtube)


def _toml(data: dict) -> str:
    """Serialize the scalar/array/nested-table subset of encode profiles."""
    lines = []

    def table(values, prefix=()):
        if prefix:
            lines.extend(("", "[" + ".".join(json.dumps(part) for part in prefix) + "]"))
        for key, value in values.items():
            if not isinstance(value, dict):
                lines.append(json.dumps(key) + " = " + json.dumps(value, ensure_ascii=False, allow_nan=False))
        for key, value in values.items():
            if isinstance(value, dict):
                table(value, (*prefix, key))
    table(data)
    return "\n".join(lines) + "\n"


def materialize(playlist: Playlist, directory: Path) -> tuple[encode_config.EncodeProfile, ...]:
    """Resolve without editing sources or sharing single-movie output names."""
    directory.mkdir(parents=True, exist_ok=True)
    profiles = []
    for item in playlist.items:
        base = encode_config.load_profile(item.profile)
        data = copy.deepcopy(base.data)
        for section, values in item.overrides.items():
            data.setdefault(section, {}).update(values)
        data = {"schema_version": encode_config.SCHEMA_VERSION, **data}
        raw = _toml(data)
        digest = hashlib.sha256(raw.encode()).hexdigest()[:12]
        path = directory / f"{playlist.stem}--{item.id}--{digest}.toml"
        if not path.exists() or path.read_text() != raw:
            path.write_text(raw, encoding="utf-8")
        profiles.append(encode_config.load_profile(path))
    return tuple(profiles)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--print-stem", action="store_true")
    parser.add_argument("--resolve", action="store_true")
    args = parser.parse_args()
    playlist = load(args.profile)
    if args.print_stem:
        print(playlist.stem)
    elif args.resolve:
        root = Path(__file__).resolve().parents[1]
        for profile in materialize(playlist, root / "tmp" / playlist.stem / "profiles"):
            print(profile.path)
    else:
        for item in playlist.items:
            print(f"{item.id}: {item.profile}")


if __name__ == "__main__":
    main()
