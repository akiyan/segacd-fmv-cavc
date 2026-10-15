// Collect the installed runtime notices without loading them into the app bundle.
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {unzipSync, strFromU8} from 'fflate';

const root = fileURLToPath(new URL('../', import.meta.url));
const dest = path.join(root, 'public/licenses');
const cache = path.join(root, '.toolchain/license-texts');
await mkdir(dest, {recursive: true});
await mkdir(cache, {recursive: true});
const read = relative => readFile(path.join(root, relative), 'utf8');
const pkg = async name => JSON.parse(await read(`node_modules/${name}/package.json`));
const link = (label, href) => ({label, href});
async function upstream(file, url) {
  const cached = path.join(cache, file);
  try {return await readFile(cached, 'utf8');} catch (error) {if (error.code !== 'ENOENT') throw error;}
  const response = await fetch(url, {signal: AbortSignal.timeout(30000)});
  if (!response.ok) throw new Error(`Cannot prepare license ${url}: ${response.status}`);
  const text = await response.text();
  await writeFile(cached, text);
  return text;
}
const projectLicense = await read('../LICENSE');
await writeFile(path.join(dest, 'project.txt'), projectLicense);
const entries = [{name: 'Sega CD Constraint-Aware Video Codec', license: 'MIT',
  links: [link('Project source code', 'https://github.com/akiyan/segacd-fmv-cavc'), link('License text', '/licenses/project.txt')],
  texts: [{name: 'Project license', text: projectLicense}]}];

const packages = [
  ['react', 'LICENSE', 'https://github.com/facebook/react/tree/v19.2.0/packages/react'],
  ['react-dom', 'LICENSE', 'https://github.com/facebook/react/tree/v19.2.0/packages/react-dom'],
  ['scheduler', 'LICENSE', 'https://github.com/facebook/react/tree/v19.2.0/packages/scheduler'],
  ['@phosphor-icons/react', 'LICENSE', 'https://github.com/phosphor-icons/react/tree/v2.1.10'],
  ['fflate', 'LICENSE', 'https://github.com/101arrowz/fflate/tree/v0.8.3'],
  ['mediabunny', 'LICENSE', 'https://github.com/Vanilagy/mediabunny/tree/d901f02d5fdd33d7a7488bd8b9393f76a98b2eb1'],
  ['@mediabunny/aac-encoder', 'LICENSE', 'https://github.com/Vanilagy/mediabunny/tree/d901f02d5fdd33d7a7488bd8b9393f76a98b2eb1/packages/aac-encoder'],
];
for (const [name, file, source] of packages) {
  const info = await pkg(name);
  const entry = {name, version: info.version, license: info.license, links: [link('Source code', source)],
    texts: [{name: 'License & copyright notice', text: await read(`node_modules/${name}/${file}`)}]};
  if (name === '@mediabunny/aac-encoder') {
    entry.license = 'MPL-2.0 / FFmpeg LGPL';
    entry.note = 'The AAC fallback contains an FFmpeg AAC encoder compiled to WebAssembly. FFmpeg licensing also applies.';
    entry.links.push(link('FFmpeg source & build instructions', 'https://github.com/Vanilagy/mediabunny/blob/d901f02d5fdd33d7a7488bd8b9393f76a98b2eb1/packages/aac-encoder/README.md'), link('FFmpeg licensing', 'https://ffmpeg.org/legal.html'));
    entry.texts.push({name: 'GNU LGPL version 2.1', text: await upstream('ffmpeg-lgpl-2.1.txt', 'https://raw.githubusercontent.com/FFmpeg/FFmpeg/n5.1.4/COPYING.LGPLv2.1')});
  }
  entries.push(entry);
}
const ffmpeg = await pkg('@ffmpeg/core');
entries.push({name: '@ffmpeg/core', version: ffmpeg.version, license: ffmpeg.license,
  note: 'Includes FFmpeg 5.1.4 and third-party codec libraries. Their respective licenses also apply.',
  links: [link('FFmpeg source archive', '/ffmpeg-runtime/ffmpeg-5.1.4-source.tar.gz'), link('Wasm source & build scripts', '/ffmpeg-runtime/ffmpeg.wasm-source.tar.gz'), link('Build & dependency source references', '/ffmpeg-runtime/sources.json'), link('FFmpeg licensing', 'https://ffmpeg.org/legal.html')],
  texts: await Promise.all(['COPYING.GPLv2', 'COPYING.GPLv3'].map(async name => ({name, text: await read(`public/ffmpeg-runtime/${name}`)})))});
entries.push({name: 'GNU Binutils', version: '2.40', license: 'GPL-3.0-or-later (tool-specific exceptions may apply)',
  links: [link('Source archive', '/m68k-runtime/binutils-2.40.tar.xz'), link('Build script & modifications', '/m68k-runtime/build-m68k-runtime.sh')],
  texts: [{name: 'GNU GPL version 3', text: await read('public/m68k-runtime/COPYING3')}]});
const pyodide = await pkg('pyodide');
const lock = JSON.parse(await read('public/python-runtime/pyodide-lock.json'));
entries.push({name: 'Pyodide', version: pyodide.version, license: pyodide.license,
  links: [link('Source code', `https://github.com/pyodide/pyodide/tree/${pyodide.version}`)],
  texts: [{name: 'Mozilla Public License 2.0', text: await upstream(`pyodide-${pyodide.version}.txt`, `https://raw.githubusercontent.com/pyodide/pyodide/${pyodide.version}/LICENSE`)}]});
entries.push({name: 'CPython', version: lock.info.python, license: 'PSF-2.0 and included notices',
  links: [link('Source code', `https://github.com/python/cpython/tree/v${lock.info.python}`)],
  texts: [{name: 'Python license & history', text: await upstream(`cpython-${lock.info.python}.txt`, `https://raw.githubusercontent.com/python/cpython/v${lock.info.python}/LICENSE`)}]});
for (const name of ['numpy', 'pillow']) {
  const info = lock.packages[name];
  const files = unzipSync(new Uint8Array(await readFile(path.join(root, 'public/python-runtime', info.file_name))));
  const texts = Object.entries(files).filter(([name]) => /\.dist-info\/licenses\//.test(name) && !name.endsWith('/'))
    .map(([name, bytes]) => ({name: name.split('/licenses/')[1], text: strFromU8(bytes)}));
  if (!texts.length) throw new Error(`No license notices found for ${name}`);
  entries.push({name: name === 'pillow' ? 'Pillow' : 'NumPy', version: info.version,
    license: name === 'pillow' ? 'MIT-CMU and included notices' : 'BSD-3-Clause and included notices',
    links: [link('Source code', name === 'pillow' ? `https://github.com/python-pillow/Pillow/tree/${info.version}` : `https://github.com/numpy/numpy/tree/v${info.version}`)], texts});
}
await writeFile(path.join(dest, 'notices.json'), JSON.stringify(entries) + '\n');
console.log(`Prepared license notices for ${entries.length} runtime components.`);
