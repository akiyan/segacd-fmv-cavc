import {readFile, writeFile, readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root = fileURLToPath(new URL('../', import.meta.url));
const dist = path.join(root, 'dist/client');
const assets = [];
async function add(name) {
  const bytes = await readFile(path.join(dist, name));
  assets.push({url: '/' + name, size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex')});
}
async function collect(directory, accept = () => true) {
  for (const entry of await readdir(path.join(dist, directory), {withFileTypes: true})) {
    const name = path.posix.join(directory, entry.name);
    if (entry.isDirectory()) await collect(name, accept);
    else if (accept(name)) await add(name);
  }
}
await add('index.html');
await collect('assets'); // Includes both worker bundles and the AAC fallback.
await collect('python-runtime');
await collect('ffmpeg-runtime', name => /\.(js|json|part)$/.test(name));
await collect('m68k-runtime', name => /\.(mjs|wasm)$/.test(name));
await collect('licenses');
for (const name of await readdir(dist)) {
  if (/^python-.*\.(py|npz|json|zip)$/.test(name) || name === 'player-code.zip' || /^favicon\./.test(name)) await add(name);
}
assets.sort((a, b) => a.url.localeCompare(b.url));
const version = createHash('sha256').update(JSON.stringify(assets)).digest('hex').slice(0, 20);
const manifest = {schema: 1, version, assets};
await writeFile(path.join(dist, 'offline-manifest.json'), JSON.stringify(manifest) + '\n');
// The manifest must itself remain readable after the network is disconnected.
const bytes = await readFile(path.join(dist, 'offline-manifest.json'));
assets.push({url: '/offline-manifest.json', size: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex')});
const template = await readFile(path.join(root, 'scripts/offline-worker.js'), 'utf8');
await writeFile(path.join(dist, 'offline-worker.js'), template.replace('__OFFLINE_VERSION__', JSON.stringify(version)).replace('__OFFLINE_ASSETS__', JSON.stringify(assets)));
console.log(`Prepared offline encoder: ${assets.length} verified assets, ${(assets.reduce((sum, asset) => sum + asset.size, 0) / 1024 ** 2).toFixed(1)} MiB.`);
