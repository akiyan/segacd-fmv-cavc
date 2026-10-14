#!/usr/bin/env python3
"""Export existing profile geometry/rate/caps without source media or metadata."""
import json
import sys
import tomllib
from fractions import Fraction
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / 'tools'))
import av_config
import cavc_routing
import shadow_updates

rows = []
for path in sorted((root / 'profiles').glob('*.toml')):
    profile = tomllib.loads(path.read_text())
    video = profile.get('video', {})
    source = profile.get('source', {})
    cap = profile.get('encoder', {}).get('cold_cap')
    if cap is None:
        continue
    fps = float(Fraction(str(source['fps'])))
    av_config.frame_cold_caps(2, fps, cap)
    rows.append({'profile': path.stem, 'width': video['width'], 'height': video['height'], 'fps': fps, 'cap': av_config.cold_cap_spec(cap)})
if not rows:
    raise RuntimeError('No encoder profile cold-cap references were found')
output = root / 'webenc/src/generated/profile-caps.json'
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({'maxColdCap': av_config.VRAM_PATTERN_POOL_TILES, 'profiles': rows}, indent=2) + '\n')
print(f'Synced {len(rows)} profile cold-cap references.')
schedule = {
    'sectorBytes': av_config.CD_SECTOR_BYTES,
    'sectorRate': av_config.CD_SECTORS_PER_SECOND,
    'vsync': av_config.NTSC_VSYNC,
    'maxInterval': av_config.MAX_FIXED_VBLANK_INTERVAL,
    'intervalTolerance': av_config._INTEGER_VBLANK_TOLERANCE,
    'deliveryCapKb': av_config.DELIVERY_CAP_KB,
    'jitterReferenceKb': av_config.RING_JITTER_REFERENCE_KB,
    'jitterReferenceFps': av_config.RING_JITTER_REFERENCE_FPS,
    'frameSectors': cavc_routing.FRAME_SECTORS,
    'maxControlSectors': cavc_routing.MAX_CTRL_SECTORS,
    'maxFrames': cavc_routing.MAX_FRAMES,
    'shadowEntryBytes': shadow_updates.SHADOW_ENTRY_BYTES,
    'listItemBytes': shadow_updates.LIST_ITEM_BYTES,
}
(output.parent / 'schedule-config.json').write_text(json.dumps(schedule, indent=2) + '\n')
