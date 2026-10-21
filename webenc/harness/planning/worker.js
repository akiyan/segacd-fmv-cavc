// Run the production Python adapter on an independently supplied codec bundle.
const send = value => self.postMessage(value);
const log = message => send({type: 'log', message});
const adapters = [
  'numeric-compat', 'stages', 'prebuffer-trace', 'progress',
  'features', 'timeline', 'pack-validation', 'replay',
];
const outputs = [
  'decisions.pkl', 'stats.npz', 'buffer_remaining.npz', 'seg_palettes.npz',
  'miss_masks.npy', 'palettes.bin', 'audio_22k05_s16_mono.wav',
  'audio_playback_adpcm22_rf5c.wav', 'stage-sha256.tsv',
  'packed/HEADER.DAT', 'packed/BODY.DAT', 'packed/MOVIE.DAT',
  'demoted-fade-anchors.json', 'playback-frames.tsv',
];

self.onmessage = async ({data}) => {
  try {
    const runtimeUrl = new URL('/python-runtime/pyodide.mjs', self.location.origin).href;
    const {loadPyodide} = await import(/* @vite-ignore */ runtimeUrl);
    const py = await loadPyodide({indexURL: '/python-runtime/', stdout: log, stderr: log});
    await py.loadPackage(['numpy', 'pillow']);
    const fetchBytes = async url => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (url.endsWith('.zip') && (bytes[0] !== 80 || bytes[1] !== 75)) {
        throw new Error(`${url}: expected a ZIP archive`);
      }
      return bytes;
    };
    py.FS.writeFile('/codec.zip', await fetchBytes('/planning/codec.zip'));
    py.FS.writeFile('/input.zip', await fetchBytes('/planning/input.zip'));
    await py.runPythonAsync(`
import sys, zipfile, json, os, shutil
from pathlib import Path
zipfile.ZipFile('/codec.zip').extractall('/codec')
zipfile.ZipFile('/input.zip').extractall('/work')
os.unlink('/codec.zip')
os.unlink('/input.zip')
shutil.copyfile('/work/audio_22k05_s16_mono.wav', '/original-audio.wav')
sys.path.insert(0, '/codec/tools')
runtime = json.loads(Path('/codec/manifest.json').read_text())
manifest = json.loads(Path('/work/manifest.json').read_text())
# Identical normalized RGB/PCM, authenticated to this frozen codec revision.
manifest['encoderSha256'] = runtime['encoderSha256']
Path('/work/manifest.json').write_text(json.dumps(manifest))
`);
    for (const name of adapters) {
      py.FS.writeFile(`/codec/tools/${name.replaceAll('-', '_')}.py`,
        await fetchBytes(`/python-${name}.py`));
    }
    py.FS.writeFile('/codec/numeric-constants.npz', await fetchBytes('/python-numeric.npz'));
    py.FS.writeFile('/codec/tools/benchmark_observe.py', await fetchBytes('/planning/observe.py'));
    await py.runPythonAsync(`
import hashlib
assert hashlib.sha256(Path('/codec/numeric-constants.npz').read_bytes()).hexdigest() == runtime['numericSha256']
import benchmark_observe
`);
    let lastProgress = 0;
    py.globals.set('__webenc_progress', (stage, percent, label, done, total) => {
      if (performance.now() - lastProgress < 5000) return;
      lastProgress = performance.now();
      log(`Progress: stage=${stage} ${label} ${done}/${total}`);
    });
    // Same adapter and numerical constants as the real Generate worker.
    await py.runPythonAsync(new TextDecoder().decode(await fetchBytes('/python-adapter.py')));
    const receipt = JSON.parse(await py.runPythonAsync(`
json.dumps(dict(completed=True, runtime='wasm',
  frames=manifest['frames'],
  source_sha256=manifest['sourceSha256'],
  profile_sha256=manifest['profileSha256'],
  encoder_sha256=runtime['encoderSha256'],
  scope='fresh browser encode on normalized full-profile inputs',
  **benchmark_observe.measurements))
`));
    receipt.revision = data.revision;
    receipt.browser = navigator.userAgent;
    await py.runPythonAsync("from replay import render\nrender('/work')");
    py.FS.writeFile('/work/benchmark.json', JSON.stringify(receipt, null, 2) + '\n');
    for (const name of [...outputs, 'benchmark.json']) {
      const response = await fetch('/planning/output/' + name, {
        method: 'POST', body: py.FS.readFile('/work/' + name),
      });
      if (!response.ok) throw new Error(`Saving ${name}: HTTP ${response.status}`);
    }
    send({type: 'complete', receipt});
  } catch (error) {
    send({type: 'error', message: String(error.stack || error)});
  }
};
