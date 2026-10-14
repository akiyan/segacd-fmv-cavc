"""Observational stage digests; optional native-only local recomputation cache."""
import hashlib
import json
from pathlib import Path
import pickle
import numpy as np


def install(sim, target, cache=False, identity=''):
    target=Path(target)
    palette_original=sim.segment_and_train
    quant_original=sim.precompute_quant
    digest_path=target/'stage-sha256.tsv'
    digest_path.write_text('stage\tframe\tname\tbytes\tsha256\n')
    def record(stage,frame,name,array):
        value=np.asarray(array)
        data=value.tobytes()
        with digest_path.open('a') as out:
            out.write(f'{stage}\t{frame}\t{name}\t{len(data)}\t{hashlib.sha256(data).hexdigest()}\n')
    def palette(*args,**kwargs):
        stored=target.parent/'native-cache'/('palette-'+identity+'.pkl')
        if cache and stored.exists():
            print('Reuse independently computed native palette cache',flush=True)
            with stored.open('rb') as file:result=pickle.load(file)
        else:
            result=palette_original(*args,**kwargs)
            if cache:
                stored.parent.mkdir(exist_ok=True)
                with stored.open('wb') as file:pickle.dump(result,file)
        record('palette',-1,'palettes',np.asarray(result[1],np.uint8))
        record('palette',-1,'frame_segments',np.asarray(result[2],np.int32))
        return result
    def quant(*args,**kwargs):
        palette_hash=hashlib.sha256(np.asarray(args[1],np.uint8).tobytes()+np.asarray(args[2],np.int32).tobytes()).hexdigest()
        stored=target.parent/'native-cache'/('quant-'+identity+'-'+palette_hash[:16]+'.pkl')
        if cache and stored.exists():
            print('Reuse independently computed native quantization cache',flush=True)
            with stored.open('rb') as file:result=pickle.load(file)
        else:
            result=quant_original(*args,**kwargs)
            if cache:
                stored.parent.mkdir(exist_ok=True)
                with stored.open('wb') as file:pickle.dump(result,file)
        for frame,(detail,assign,index) in enumerate(zip(*result)):
            record('quantize',frame,'detail',detail)
            record('quantize',frame,'palette_assignment',assign)
            record('quantize',frame,'indices',index)
        return result
    sim.segment_and_train=palette
    sim.precompute_quant=quant
