// Fresh Chromium worker, full production Python adapter, no source-specific results.
import {createReadStream, createWriteStream} from 'node:fs';
import {readFile, writeFile, mkdir, access, unlink} from 'node:fs/promises';
import {pipeline} from 'node:stream/promises';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import {createServer} from 'vite';
import {chromium} from '@playwright/test';
import {zipSync, strToU8} from 'fflate';

const root = fileURLToPath(new URL('../../', import.meta.url));
const repo = path.resolve(root, '..');
const job = path.resolve(process.argv[2] || '');
const revision = process.argv[3];
if (!revision || !/^[a-z0-9-]+$/.test(revision)) throw new Error('Pass JOB and REVISION.');
const target = path.join(job, 'runs', `wasm-${revision}`);
try { await access(target); throw new Error(`Previous run exists: ${target}`); }
catch (error) { if (error.code !== 'ENOENT') throw error; }

const lease = spawn(path.join(repo, 'tools/python.sh'),
  [path.join(root, 'harness/equivalence/lease.py'), job],
  {stdio: ['pipe', 'pipe', 'inherit']});
await new Promise((resolve, reject) => {
  lease.stdout.on('data', bytes => {
    if (bytes.toString().includes('LEASE_READY')) resolve();
  });
  lease.once('exit', code => reject(new Error(`Lease exited: ${code}`)));
});

let browser, server;
try {
  await mkdir(target, {recursive: true});
  const {readdir} = await import('node:fs/promises');
  const entries = {}, fingerprint = createHash('sha256');
  const tools = path.join(job, 'revisions', revision, 'tools');
  for (const name of (await readdir(tools)).filter(n => n.endsWith('.py')).sort()) {
    const bytes = await readFile(path.join(tools, name));
    entries['tools/' + name] = bytes;
    fingerprint.update(name); fingerprint.update(bytes);
  }
  entries['tools/av_version.txt'] = await readFile(path.join(tools, 'av_version.txt'));
  const runtime = {
    encoderSha256: fingerprint.digest('hex'),
    numericSha256: createHash('sha256').update(
      await readFile(path.join(root, 'public/python-numeric.npz'))).digest('hex'),
  };
  entries['manifest.json'] = strToU8(JSON.stringify(runtime));
  const bundle = path.join(target, 'codec.zip');
  await writeFile(bundle, zipSync(entries, {level: 6}));
  const readable = new Map([
    ['/planning/codec.zip', bundle],
    ['/planning/input.zip', path.join(job, 'normalized.cavc-input.zip')],
    ['/planning/observe.py', path.join(root, 'harness/planning/observe.py')],
  ]);
  const outputs = new Set([
    'decisions.pkl', 'stats.npz', 'buffer_remaining.npz', 'seg_palettes.npz',
    'miss_masks.npy', 'palettes.bin', 'audio_22k05_s16_mono.wav',
    'audio_playback_adpcm22_rf5c.wav', 'stage-sha256.tsv',
    'packed/HEADER.DAT', 'packed/BODY.DAT', 'packed/MOVIE.DAT',
    'demoted-fade-anchors.json', 'playback-frames.tsv', 'benchmark.json',
  ]);
  const serveFixture = async (request, response, next) => {
    try {
      const input = readable.get(request.url);
      if (request.method === 'GET' && input) {
        response.setHeader('Content-Type', 'application/octet-stream');
        await pipeline(createReadStream(input), response);
      } else if (request.method === 'POST' && request.url.startsWith('/planning/output/')) {
        const name = request.url.slice('/planning/output/'.length);
        if (!outputs.has(name)) { response.writeHead(404).end(); return; }
        const file = path.join(target, name);
        await mkdir(path.dirname(file), {recursive: true});
        await pipeline(request, createWriteStream(file));
        response.end('saved');
      } else next();
    } catch (error) {
      console.error(error);
      if (!response.headersSent) response.writeHead(500);
      response.end();
    }
  };
  server = await createServer({
    root, logLevel: 'error', server: {host: '127.0.0.1', port: 0},
    plugins: [{
      name: 'planning-fixtures',
      configureServer(server) { server.middlewares.use(serveFixture); },
    }],
  });
  await server.listen();
  const origin = server.resolvedUrls.local[0];
  const served = Buffer.from(await (await fetch(origin + 'planning/codec.zip')).arrayBuffer());
  if (!served.equals(await readFile(bundle))) throw new Error('Codec fixture route differs');
  const upload = await fetch(origin + 'planning/output/benchmark.json', {
    method: 'POST', body: '{"completed":false,"transport_check":true}\n',
  });
  if (!upload.ok || (await upload.text()) !== 'saved') throw new Error('Output fixture route failed');
  await unlink(path.join(target, 'benchmark.json'));
  browser = await chromium.launch({headless: true});
  const page = await browser.newPage();
  page.on('console', message => console.log(message.text()));
  page.on('pageerror', error => console.error(error));
  await page.goto(server.resolvedUrls.local[0]);
  console.log(`Preview: ${await page.title()}; ${server.resolvedUrls.local[0]}`);
  const result = await page.evaluate(revision => new Promise((resolve, reject) => {
    const worker = new Worker('/harness/planning/worker.js', {type: 'module'});
    worker.onmessage = ({data}) => {
      if (data.type === 'log') console.log(data.message);
      else if (data.type === 'complete') { worker.terminate(); resolve(data.receipt); }
      else if (data.type === 'error') { worker.terminate(); reject(new Error(data.message)); }
    };
    worker.onerror = error => { worker.terminate(); reject(new Error(error.message)); };
    worker.postMessage({revision});
  }), revision);
  console.log(JSON.stringify(result));
} finally {
  await browser?.close();
  await server?.close();
  lease.stdin.end();
}
