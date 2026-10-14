"""Freeze source-independent RGB333 comparison constants of the native codec."""
import hashlib
import json
import os
import argparse
from pathlib import Path
import sys
import numpy as np
if np.__version__!='2.3.5':
    raise RuntimeError('Generate native comparison constants with the locked NumPy 2.3.5 reference environment')
parser=argparse.ArgumentParser()
parser.add_argument('job',type=Path,nargs='?')
parser.add_argument('--tools',type=Path)
parser.add_argument('--output',type=Path)
args=parser.parse_args()
if args.job:
    job=args.job.resolve()
    source=job/'snapshot/tools'
    output=job/'numeric-constants.npz'
else:
    if not args.tools or not args.output:parser.error('Supply a job or --tools and --output')
    source=args.tools.resolve();output=args.output.resolve()
for key in list(os.environ):
    if key.startswith('CBRSIM_'):del os.environ[key]
sys.path.insert(0,str(source));sys.argv=['numeric-constants']
os.environ['CBRSIM_OUT']='/dev/shm/segacd-fmv-cavc/numeric-probe'
import sim
names=['_MD_LUM','_MD_CB','_MD_CR','_F3_DY_LUT','_F3_DC_LUT']
arrays={name:getattr(sim,name) for name in names}
output.parent.mkdir(parents=True,exist_ok=True)
np.savez(output,**arrays)
print('Source-independent codec constants:')
for name,array in arrays.items():print(name,array.nbytes,hashlib.sha256(array.tobytes()).hexdigest())
