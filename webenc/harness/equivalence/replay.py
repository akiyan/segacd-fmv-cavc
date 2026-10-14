"""Render the canonical /sim display, without importing analysis UI dependencies."""
import ast
import json
import pickle
import hashlib
from pathlib import Path
import numpy as np
from PIL import Image
import scroll_plan
import scroll_frames
import shadow_updates


def render(directory, frame_callback=None):
    directory=Path(directory)
    with (directory/'decisions.pkl').open('rb') as file:log=pickle.load(file)
    frames=log['frames'];nf=len(frames)
    columns,rows,cells,tile=map(int,log['geom'])
    if tile!=8 or cells!=columns*rows:raise ValueError('Invalid replay geometry')
    masks=log['display_category_masks'];order=tuple(masks['bit_order'])
    mask_rows=np.stack([np.frombuffer(row,dtype='<u2') for row in masks['rows']])
    # Use exactly the canonical render_analysis.py display implementation.
    # Its category-map/overlay tail is excluded; the displayed pixels are not.
    source=(Path(shadow_updates.__file__).parent/'render_analysis.py').read_text()
    functions={node.name:node for node in ast.parse(source).body if isinstance(node,ast.FunctionDef)}
    code=ast.get_source_segment(source,functions['_cells_to_image'])+'\n'
    canonical=ast.get_source_segment(source,functions['materialize_analysis_panels'])
    boundary='\n        border_names ='
    if boundary not in canonical:raise RuntimeError('Canonical renderer boundary changed')
    canonical=canonical.split(boundary,1)[0]
    canonical=canonical.replace('for frame, updates in enumerate(DECISION_FRAMES):',
        'for frame, updates in enumerate(DECISION_FRAMES):\n        if frame % 100 == 0: print(f"Playback frames {frame}/{NF}", flush=True)')
    if frame_callback is not None:
        canonical += '\n        frame_callback(frame, str(preview_dir / f"{frame:05d}.png"), NF, W, H)'
    fade=log['fade'];scroll=log.get('scroll',{})
    active=np.asarray(scroll.get('active',np.zeros(nf,np.bool_)),np.bool_)
    namespace=dict(frame_callback=frame_callback,np=np,Image=Image,Path=Path,SIM=str(directory),NF=nf,C=cells,
        TCOLS=columns,TROWS=rows,W=columns*8,H=rows*8,DECISION_FRAMES=frames,
        CATEGORY_MASK_ORDER=order,CATEGORY_MASK_ROWS=masks['rows'],
        FULL={name:np.count_nonzero(mask_rows & (1<<bit),axis=1) for bit,name in enumerate(order)},
        ACTIVE_FRAME_CRAM=np.asarray(fade['active_frame_cram'],np.uint8),
        SCROLL_ACTIVE=active,SCROLL_POSITIONS=np.asarray(scroll.get('positions',np.zeros((nf,2))),np.int64),
        SCROLL_ON=bool(active.any()),scroll_plan=scroll_plan,scroll_frames=scroll_frames,shadow_updates=shadow_updates)
    exec(code+canonical,namespace)
    namespace['materialize_analysis_panels'](range(nf))
    lines=['frame\twidth\theight\trgb_sha256']
    for frame in range(nf):
        pixels=np.asarray(Image.open(directory/'preview'/f'{frame:05d}.png').convert('RGB'),np.uint8)
        lines.append(f'{frame}\t{columns*8}\t{rows*8}\t{hashlib.sha256(pixels.tobytes()).hexdigest()}')
    (directory/'playback-frames.tsv').write_text('\n'.join(lines)+'\n')
    with np.load(directory/'stats.npz',allow_pickle=True) as stats:
        audio=str(stats['audio_playback_file'])
    result=dict(frames=nf,width=columns*8,height=rows*8,fps=float(log['fps']),audio=audio)
    (directory/'playback.json').write_text(json.dumps(result)+'\n')
    print(f'Playback frames {nf}/{nf}',flush=True)
    return result
