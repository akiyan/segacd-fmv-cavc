// Replaced by prepare-offline.mjs after bundling the complete application.
const VERSION = __OFFLINE_VERSION__;
const ASSETS = __OFFLINE_ASSETS__;
// Identical runtimes are shared between releases. A UI update must not cause
// another 57 MiB download; each response is addressed by its verified digest.
const CACHE = 'cavc-offline-assets-v1';
const cacheKey = asset => `/__cavc_offline_asset__/${asset.sha256}`;
const byUrl = new Map(ASSETS.map(asset => [asset.url, asset]));
let preparing;
const listeners = new Set();
const broadcast = value => {for (const port of listeners) port.postMessage({...value, version: VERSION});};

self.addEventListener('install', event => event.waitUntil(self.skipWaiting()));
self.addEventListener('activate', event => event.waitUntil(self.clients.claim()));

async function prepare() {
  const cache = await caches.open(CACHE);
  const total = ASSETS.reduce((sum, asset) => sum + asset.size, 0);
  let done = 0;
  const mib = bytes => `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  for (const asset of ASSETS) {
    if (await cache.match(cacheKey(asset))) {
      broadcast({type: 'log', message: `Using saved asset: ${asset.url} (${mib(asset.size)})`});
      done += asset.size;
      broadcast({type: 'progress', done, total, file: asset.url});
      continue;
    }
    broadcast({type: 'log', message: `Downloading ${asset.url} (${mib(asset.size)})`});
    const response = await fetch(asset.url, {cache: 'no-store'});
    if (!response.ok) throw new Error(`Cannot prepare ${asset.url}: HTTP ${response.status}`);
    const reader = response.body.getReader(), chunks = [];
    let received = 0, lastReport = 0, lastQuarter = 0;
    while (true) {
      const {value, done: ended} = await reader.read();
      if (ended) break;
      chunks.push(value);
      received += value.length;
      const now = performance.now();
      if (now - lastReport >= 100 || received >= asset.size) {
        broadcast({type: 'progress', done: done + received, total, file: asset.url});
        lastReport = now;
      }
      const quarter = Math.floor(received / asset.size * 4);
      if (asset.size >= 4 * 1024 ** 2 && quarter > lastQuarter && quarter < 4) {
        broadcast({type: 'log', message: `Downloading ${asset.url}: ${mib(received)} / ${mib(asset.size)}`});
        lastQuarter = quarter;
      }
    }
    const bytes = new Uint8Array(received);
    let offset = 0;
    for (const chunk of chunks) {bytes.set(chunk, offset); offset += chunk.length;}
    const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))].map(v => v.toString(16).padStart(2, '0')).join('');
    if (received !== asset.size || digest !== asset.sha256) throw new Error(`Offline asset verification failed: ${asset.url}. Reload the page to get a consistent release.`);
    const headers = new Headers(response.headers);
    headers.delete('content-encoding'); headers.delete('content-length');
    await cache.put(cacheKey(asset), new Response(bytes, {headers}));
    broadcast({type: 'log', message: `Verified and saved: ${asset.url} (${mib(asset.size)})`});
    done += received;
  }
}

self.addEventListener('message', event => {
  if (event.data?.type !== 'prepare' || !event.ports[0]) return;
  const port = event.ports[0];
  listeners.add(port);
  if (!preparing) preparing = prepare().catch(error => {preparing = null; throw error;});
  event.waitUntil(preparing.then(() => port.postMessage({type: 'ready', version: VERSION}))
    .catch(error => port.postMessage({type: 'error', message: error.message, version: VERSION}))
    .finally(() => {listeners.delete(port); port.close();}));
});

self.addEventListener('fetch', event => {
  const request = event.request, url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  // Navigation checks the server for a new release; offline visits use the
  // complete cached page. All executable/runtime assets use this release cache.
  if (request.mode === 'navigate') {
    const cachedPage = async () => {
      const response = await (await caches.open(CACHE)).match(cacheKey(byUrl.get('/index.html')));
      if (!response) throw new Error('The offline page is not ready.');
      return response;
    };
    event.respondWith(self.navigator.onLine === false ? cachedPage() : fetch(request).catch(cachedPage));
    return;
  }
  event.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const asset = byUrl.get(url.pathname);
    return (asset && await cache.match(cacheKey(asset))) || fetch(request);
  })());
});
