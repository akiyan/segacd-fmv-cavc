"""Byte-for-byte comparison of independently produced complete CAVC streams."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path

parser=argparse.ArgumentParser();parser.add_argument('job',type=Path);args=parser.parse_args()
job=args.job.resolve();manifest=json.loads((job/'manifest.json').read_text())
rows=[];passed=True
for name in ['HEADER.DAT','BODY.DAT','MOVIE.DAT']:
    native=(job/'native/packed'/name).read_bytes();wasm=(job/('wasm-'+name)).read_bytes()
    same=native==wasm;passed &= same
    first=next((i for i,(a,b) in enumerate(zip(native,wasm)) if a!=b),min(len(native),len(wasm))) if not same else -1
    rows.append((name,len(native),len(wasm),hashlib.sha256(native).hexdigest(),hashlib.sha256(wasm).hexdigest(),first,'PASS' if same else 'FAIL'))
result={'gate':'PASS' if passed else 'FAIL','profile':manifest['profile'],'profileSha256':manifest['profileSha256'],'sourceSha256':manifest['sourceSha256'],'encoderSha256':manifest['encoderSha256'],'frames':manifest['frames'],'duration':manifest['duration'],'iteration':manifest.get('iteration','complete source profile'),'fullProfile':not bool(manifest.get('iteration')),'nativeInput':str(job/'inputs'),'nativeOutput':str(job/'native/packed'),'wasmOutput':str(job)}
stage_same=(job/'native/stage-sha256.tsv').read_bytes()==(job/'wasm-stage-sha256.tsv').read_bytes()
result['stageDigestsMatch']=stage_same
result['browserRuntime']=json.loads((job/'wasm-result.json').read_text())['runtime']
result['artifacts']=[dict(zip(['name','nativeBytes','wasmBytes','nativeSha256','wasmSha256','firstDifference','gate'],row)) for row in rows]
print('Stage digests:', 'MATCH' if stage_same else 'DIFFER (inspect per-stage TSV; final binary comparison remains authoritative)')
text='artifact\tnative_bytes\twasm_bytes\tnative_sha256\twasm_sha256\tfirst_difference\tgate\n'
text+=''.join('\t'.join(map(str,row))+'\n' for row in rows)
(job/'byte-match.tsv').write_text(text);(job/'byte-match.json').write_text(json.dumps(result,indent=2)+'\n')
root=Path(__file__).resolve().parents[3];logs=root/'logs';logs.mkdir(exist_ok=True)
stem=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'_webenc_'+Path(manifest['profile']).stem+('_half' if manifest.get('iteration') else '_full')+'_byte_match'
(logs/(stem+'.tsv')).write_text(text);(logs/(stem+'.json')).write_text(json.dumps(result,indent=2)+'\n')
print(text,end='');print(f"{result['gate']}: {manifest['frames']} frames, scope={result['iteration']}")
if not passed:raise SystemExit(1)
