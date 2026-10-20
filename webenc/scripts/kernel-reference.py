"""Independent fixtures from the repository's actual Python primitives."""
import json
from pathlib import Path
import numpy as np
from quantize_md_video import rgb888_to_rgb333, rgb333_to_rgb888, pack_tiles_4bpp
from quantize_global4_tiles import tile_blocks, palette_lut, rgb333_keys
from ima_adpcm import State, encode_chunk, decode_chunk, pcm16_to_sign_magnitude, sign_magnitude_to_pcm16
from test_paths import KERNEL_ROOT as root
root.mkdir(parents=True,exist_ok=True)
rng=np.random.default_rng(5812)
records=[]
for n in range(24):
    width,height=32,24
    rgba=rng.integers(0,256,(height,width,4),dtype=np.uint8);rgba[:,:,3]=255
    palette=rng.integers(0,8,(4,15,3),dtype=np.uint8)
    keys=rgb333_keys(tile_blocks(rgb888_to_rgb333(rgba[:,:,:3])))
    tables=[palette_lut(line,squared=True) for line in palette]
    errors=np.stack([table[0][keys].sum(1) for table in tables],axis=1)
    lines=errors.argmin(1)
    indices=np.stack([tables[line][1][keys[i]]+1 for i,line in enumerate(lines)])
    raster=indices.reshape(height//8,width//8,8,8).transpose(0,2,1,3).reshape(height,width)
    expected=np.stack([rgb333_to_rgb888(palette[line][indices[i]-1]) for i,line in enumerate(lines)]).reshape(height//8,width//8,8,8,3).transpose(0,2,1,3,4).reshape(height,width,3)
    output=np.concatenate((expected,np.full((height,width,1),255,dtype=np.uint8)),axis=2)
    stem=f'frame-{n}'
    for suffix,bytes_ in [('rgba',rgba.tobytes()),('palette',palette.tobytes()),('expected-rgba',output.tobytes()),('expected-tile',pack_tiles_4bpp(raster,width,height)),('expected-pmap',lines.astype(np.uint8).tobytes())]: (root/f'{stem}.{suffix}').write_bytes(bytes_)
    records.append({'stem':stem,'width':width,'height':height})
state=State()
audio=[]
for n in range(32):
    pcm=rng.integers(-32768,32768,1024,dtype=np.int16)
    if n==0:pcm[:16]=[-32768,32767,0,1,-1,256,-256,32512,-32256,127,-127,8192,-8192,0,0,0]
    initial=state
    encoded,state=encode_chunk(pcm,state)
    decoded,final=decode_chunk(encoded,len(pcm));assert final==state
    expected=sign_magnitude_to_pcm16(pcm16_to_sign_magnitude(decoded))
    stem=f'audio-{n}'
    (root/f'{stem}.pcm').write_bytes(pcm.astype('<i2').tobytes());(root/f'{stem}.expected-chunk').write_bytes(encoded);(root/f'{stem}.expected-pcm').write_bytes(expected.astype('<i2').tobytes())
    audio.append({'stem':stem,'initial':[initial.predictor,initial.index],'final':[state.predictor,state.index]})
from tile_alloc import TileAllocator
residency = []
allocator = TileAllocator(12, 17, 1)
bank = [rng.integers(0,256,32,dtype=np.uint8).tobytes() for _ in range(80)]
for frame in range(120):
    cells = sorted(rng.choice(12, size=12 if frame == 0 else int(rng.integers(0,13)), replace=False).tolist())
    keys = [bank[int(rng.integers(len(bank)))] for _ in cells]
    before = [allocator.is_resident(k) for k in keys]
    placed = allocator.place_frame(list(zip(cells, keys)), frame)
    residency.append({'cells': cells, 'keys': [list(k) for k in keys], 'before': before, 'placed': placed})
(root/'fixture.json').write_text(json.dumps({'frames':records,'audio':audio,'residency':residency}))
print(f'Python reference fixtures: {len(records)} frames, {len(audio)} continuous-state ADPCM chunks')
