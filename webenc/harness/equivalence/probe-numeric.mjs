import {loadPyodide} from 'pyodide';
import {readFile,writeFile} from 'node:fs/promises';
import {unzipSync} from 'fflate';
const job=process.argv[2];
const py=await loadPyodide({indexURL:new URL('../../node_modules/pyodide/',import.meta.url).pathname});
await py.loadPackage(['numpy','pillow']);
const sources=unzipSync(new Uint8Array(await readFile(new URL('../../public/python-codec.zip',import.meta.url))));
py.FS.mkdirTree('/codec/tools');
for(const [name,data]of Object.entries(sources))if(name.startsWith('tools/'))py.FS.writeFile('/codec/'+name,data);
py.FS.writeFile('/reference.npz',new Uint8Array(await readFile(job+'/numeric-constants.npz')));
await py.runPythonAsync(`
import os,sys,types,hashlib,numpy as np
os.environ['CBRSIM_OUT']='/work'
sys.path.insert(0,'/codec/tools')
sys.modules['resource_tokens']=types.ModuleType('resource_tokens')
sys.modules['tmpfs_workspace']=types.ModuleType('tmpfs_workspace')
import sim
with np.load('/reference.npz') as data:
 for name in data.files:
  a=data[name];b=getattr(sim,name)
  print(name,'different entries',np.count_nonzero(a!=b),'max difference',np.max(np.abs(a-b)))
`);
