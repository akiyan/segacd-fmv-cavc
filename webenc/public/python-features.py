"""Small, observational summaries of the original encoder's selected data."""
import json
import pickle
from pathlib import Path
import numpy as np


def intervals(active):
    indices=np.flatnonzero(active)
    if not len(indices):return []
    groups=np.split(indices,np.flatnonzero(np.diff(indices)>1)+1)
    return [(int(group[0]),int(group[-1])+1) for group in groups]


def summarize(palettes,segments,frames,fps,*,scroll_active=None,scroll_positions=None,
              frame_types=None,shots=(),status='planned'):
    segments=np.asarray(segments)
    sets=[]
    for index,palette in enumerate(palettes):
        colors=np.asarray(palette,np.uint8)
        spans=[{'start':start,'end':end} for start,end in intervals(segments==index)]
        unique={tuple(sorted(tuple(map(int,color)) for color in line)) for line in colors}
        sets.append(dict(index=index,colors=colors.tolist(),uniqueLines=len(unique),spans=spans))
    scroll=None
    if scroll_active is not None:
        positions=np.asarray(scroll_positions)
        scroll=[]
        for start,end in intervals(scroll_active):
            axis='y' if np.any(positions[start:end,1]) else 'x'
            scroll.append(dict(start=start,end=end,axis=axis,finalPosition=int(positions[end-1,1 if axis=='y' else 0])))
    fades=None
    if frame_types is not None:
        types=np.asarray(frame_types)
        fades=[]
        for shot in shots:
            start=shot['anchor'] if isinstance(shot,dict) else shot.anchor
            end=max(shot['end'],shot.get('right_black_end',-1)) if isinstance(shot,dict) else shot.display_end
            for kind,value in [('in',1),('out',2)]:
                indices=np.flatnonzero((types==value)&(np.arange(frames)>=start)&(np.arange(frames)<=end))
                if len(indices):fades.append(dict(kind=kind,start=int(indices[0]),end=int(indices[-1])+1,controls=len(indices)))
    return dict(schema=1,status=status,colorEncoding='rgb333',frames=int(frames),fps=float(fps),
                paletteSets=sets,scroll=scroll,fades=fades,
                paletteSwitches=int(np.count_nonzero(segments[1:]!=segments[:-1])))


def from_context(context,fps):
    return summarize(context['seg_pals'],context['frame_seg'],context['n'],fps,
        scroll_active=context.get('scroll_active'),scroll_positions=context.get('scroll_positions'),
        frame_types=context.get('frame_types'),shots=context['fade_layout'].shots)


def from_decisions(directory):
    directory=Path(directory)
    with (directory/'decisions.pkl').open('rb') as file:log=pickle.load(file)
    result=summarize(log['seg_pals'],log['frame_seg'],len(log['frames']),log['fps'],
        scroll_active=log.get('scroll',{}).get('active'),scroll_positions=log.get('scroll',{}).get('positions'),
        frame_types=log['fade']['frame_types'],shots=log['fade']['shots'],status='verified')
    result['packedStreamVerified']=True
    from timeline import export
    result['timeline']=export(directory,log)
    (directory/'encode-summary.json').write_text(json.dumps(result,separators=(',',':'))+'\n')
    return result
