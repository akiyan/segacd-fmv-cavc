"""Create an exact first-half iteration fixture from the normalized full input."""
import json
from pathlib import Path
import sys
import shutil
import wave
import zipfile
import hashlib

full=Path(sys.argv[1]).resolve();half=full/'half';inputs=half/'inputs'
inputs.mkdir(parents=True,exist_ok=True)
manifest=json.loads((full/'manifest.json').read_text())
count=manifest['frames']//2
fps=float(manifest['fps']);duration=count/fps
for name in ['master','raw']:
    (inputs/name).mkdir(exist_ok=True)
    for source in sorted((full/'inputs'/name).glob('*.png'))[:count]:
        target=inputs/name/source.name
        if not target.exists():target.hardlink_to(source)
with wave.open(str(full/'inputs/audio_22k05_s16_mono.wav'),'rb') as wav:
    samples=min(wav.getnframes(),round(duration*22050))
    pcm=wav.readframes(samples)
with wave.open(str(inputs/'audio_22k05_s16_mono.wav'),'wb') as wav:
    wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(22050);wav.writeframes(pcm)
(inputs/'audio.s16le').write_bytes(pcm)
source_rows=(full/'inputs/input-sha256.tsv').read_text().splitlines()
rows=[source_rows[0]]
for row in source_rows[1:]:
    fields=row.split('\t')
    if fields[0] in ('master','raw') and int(fields[1])<count:rows.append(row)
rows.append('\t'.join(['pcm','0',str(len(pcm)),hashlib.sha256(pcm).hexdigest(),
    hashlib.sha256((inputs/'audio_22k05_s16_mono.wav').read_bytes()).hexdigest()]))
(inputs/'input-sha256.tsv').write_text('\n'.join(rows)+'\n')
shutil.copyfile(full/'inputs/sp-extension.bin',inputs/'sp-extension.bin')
manifest['fullFrames']=manifest['frames'];manifest['frames']=count
manifest['fullDuration']=manifest['duration'];manifest['duration']=format(duration,'.15g')
manifest['audioSamples']=samples
manifest['iteration']='first half; final qualification requires the full original fixture'
manifest['environment']['CBRSIM_DURATION']=manifest['duration']
for target in [half/'manifest.json',inputs/'manifest.json']:
    target.write_text(json.dumps(manifest,indent=2)+'\n')
if not (half/'snapshot').exists():(half/'snapshot').symlink_to(full/'snapshot',target_is_directory=True)
with zipfile.ZipFile(half/'normalized.cavc-input.zip','w',compression=zipfile.ZIP_STORED) as archive:
    for target in sorted(inputs.rglob('*')):
        if target.is_file():archive.write(target,target.relative_to(inputs).as_posix())
print(f'Iteration fixture: {count} frames, {duration:.6f} seconds, {samples} PCM samples')
print(half)
