let current = {status: 'loading', done: 0, total: 0, detail: 'Preparing offline encoder…'};
let pending;
let logId = 0;
const listeners = new Set();
const update = state => {current = state; for (const listener of listeners) listener(state);};
const log = text => update({...current, entry: {id: ++logId, text}});

function activated(worker) {
  return new Promise((resolve, reject) => {
    const check = () => {
      if (worker.state === 'activated') {worker.removeEventListener('statechange', check); resolve(worker);}
      else if (worker.state === 'redundant') {worker.removeEventListener('statechange', check); reject(new Error('Offline setup was interrupted. Retry to finish downloading.'));}
    };
    worker.addEventListener('statechange', check); check();
  });
}

async function prepare() {
  if (import.meta.env.DEV) {
    update({status: 'development', done: 0, total: 0, detail: 'Development server · offline preparation requires a production build'});
    return;
  }
  update({status: 'loading', done: 0, total: 0, detail: 'Preparing offline encoder…'});
  log('Preparing all encoder libraries and data for offline use. No source video is downloaded or uploaded.');
  if (!('serviceWorker' in navigator) || !isSecureContext) throw new Error('Offline encoding needs HTTPS and service worker support.');
  const response = await fetch('/offline-manifest.json', {cache: 'no-cache'});
  if (!response.ok) throw new Error('Cannot load the offline encoder manifest.');
  const manifest = await response.json();
  const existing = await navigator.serviceWorker.getRegistration('/');
  const registration = await navigator.serviceWorker.register('/offline-worker.js', {updateViaCache: 'none'}).catch(error => {
    if (existing?.active) return existing;
    throw error;
  });
  const worker = await activated(registration.installing || registration.waiting || registration.active);
  await new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = ({data}) => {
      if (data.version !== manifest.version) {
        channel.port1.close(); reject(new Error('A new release is available. Reload the page to finish offline setup.')); return;
      }
      if (data.type === 'progress') update({status: 'loading', ...data, detail: `Preparing offline encoder · ${(data.done / 1024 ** 2).toFixed(1)} / ${(data.total / 1024 ** 2).toFixed(1)} MiB`});
      if (data.type === 'log') log(data.message);
      if (data.type === 'error') {channel.port1.close(); reject(new Error(data.message));}
      if (data.type === 'ready') {channel.port1.close(); resolve();}
    };
    worker.postMessage({type: 'prepare'}, [channel.port2]);
  });
  // claim() in activate controls this first visit as well as its future workers.
  if (!navigator.serviceWorker.controller) await new Promise(resolve => navigator.serviceWorker.addEventListener('controllerchange', resolve, {once: true}));
  update({status: 'ready', done: 1, total: 1, detail: 'Offline ready'});
  log('Offline ready. All encoder libraries and data are saved; encoding through MP4, ISO/CUE and ZIP needs no network connection.');
}

export function prepareOfflineEncoder() {
  if (!pending) pending = prepare().catch(error => {
    pending = null;
    update({status: 'error', done: 0, total: 0, detail: error.message});
    log(`Offline preparation failed: ${error.message}`);
  });
  return pending;
}
export function subscribeOfflineEncoder(listener) {
  listeners.add(listener); listener(current); prepareOfflineEncoder();
  return () => listeners.delete(listener);
}
