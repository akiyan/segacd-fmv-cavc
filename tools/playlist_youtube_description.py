#!/usr/bin/env python3
"""Render playlist playback metadata from its exact build and published graphs."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from contextlib import ExitStack
from pathlib import Path
import encode_config
import playlist
import tmpfs_workspace
from youtube_description import TEMPLATE_DIR, StrictFormatter, build_version, cram_counts, band_kib


def render(config: Path, manifest_path: Path, evidence_path: Path) -> tuple[str, str]:
    collection = playlist.load(config)
    title = collection.youtube.get('playback_title')
    if not title:
        raise ValueError('playlist [youtube].playback_title is required')
    manifest = json.loads(manifest_path.read_text())
    evidence = json.loads(evidence_path.read_text())
    if [i.id for i in collection.items] != [i['id'] for i in manifest['items']] or [i.id for i in collection.items] != [i['id'] for i in evidence['items']]:
        raise ValueError('playlist, build and graph order must match')
    if not build_version().endswith('.' + '.'.join(manifest['versions'])):
        raise ValueError('build version mismatch')
    english, japanese, links = [], [], []
    with ExitStack() as stack:
        for item, built, graph in zip(collection.items, manifest['items'], evidence['items']):
            # Metadata may change without changing an encoded item; effective
            # profile bytes and playback order must still match the capture.
            if str(item.profile) != built['source_profile'] or item.overrides != built['overrides']:
                raise ValueError(f'{item.id}: source or overrides changed')
            path = Path(built['effective_profile'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != built['profile_sha256']:
                raise ValueError(f'{item.id}: effective profile changed')
            profile = encode_config.load_profile(path)
            source = encode_config.load_profile(item.profile)
            current = copy.deepcopy(source.data)
            for section, values in item.overrides.items():
                current.setdefault(section, {}).update(values)
            expected = copy.deepcopy(profile.data)
            current.pop('youtube', None)
            expected.pop('youtube', None)
            if current != expected:
                raise ValueError(f'{item.id}: encoded settings changed')
            if not source.source_label or not source.source_label_ja:
                raise ValueError(f'{item.id}: bilingual source labels required')
            lease = tmpfs_workspace.lease_managed_path(profile.output_dir)
            if lease:
                stack.callback(lease.release)
            segments, switches = cram_counts(profile.output_dir)
            layout = json.loads(Path(graph['timeline']['layout']).read_text())
            timeline = Path(layout['tsv'])
            if layout['config_sha256'] != built['profile_sha256'] or hashlib.sha256(timeline.read_bytes()).hexdigest() != layout['tsv_sha256']:
                raise ValueError(f'{item.id}: graph does not match encoded profile/TSV')
            band = band_kib(timeline)
            v = profile.section('video')
            width, height = v['width'], v['height']
            cols, rows = width // 8, height // 8
            common = f"{width}x{height}, {built['fps']} fps; {cols}x{rows} tiles ({cols*rows}); "
            en = f"Source: {source.source_label}."
            ja = f"Source: {source.source_label_ja}。"
            source_url = source.section('youtube').get('source_url')
            if source_url:
                en += f'\nSource video: {source_url}'
            if source.source_license:
                en += f'\nLicense: {source.source_license}\nLicense terms: {source.source_license_url}'
                ja += f'\nLicense: {source.source_license_ja}'
            english.append(en + f'\nOutput: {common}CRAM switches: {switches} ({segments} segments); BODY {band} KiB/s.')
            japanese.append(ja + f'\n出力: {common}CRAM switchは{switches}回 ({segments} segments); BODY {band} KiB/s。')
            links.append(f"{item.id}: {graph['timeline']['publication']['gist_url']}")
    template = (TEMPLATE_DIR / 'playlist_playback.txt').read_text()
    text = StrictFormatter().vformat(template, (), dict(items_en='\n\n'.join(english), items_ja='\n\n'.join(japanese), links='\n'.join(links), build=build_version()))
    return title, text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--graphs', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    title, text = render(args.config, args.manifest, args.graphs)
    args.output.write_text(text, encoding='utf-8')
    print(title)
    print(f'{args.output}: {len(text)} characters')

if __name__ == '__main__':
    main()
