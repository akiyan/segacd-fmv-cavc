// A real ordinary-media encode after disconnecting before selecting the input.
import {chromium, expect} from '@playwright/test';
import {readFile, writeFile} from 'node:fs/promises';
import {unzipSync} from 'fflate';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';

const source = process.argv[2];
if (!source) throw new Error('Usage: node harness/offline/verify.mjs /absolute/source.mp4');
const repo = fileURLToPath(new URL('../../../', import.meta.url));
const lease = spawn(repo + 'tools/python.sh', [repo + 'webenc/harness/equivalence/lease.py', source], {stdio: ['pipe', 'pipe', 'inherit']});
await new Promise((resolve, reject) => {lease.stdout.once('data', resolve); lease.once('exit', code => {if (code) reject(new Error('Fixture lease failed'));});});
const browser = await chromium.launch({headless: true});
const errors = [], failed = [], requests = [], downloads = [];
let disconnected = false;
try {
  const context = await browser.newContext({acceptDownloads: true});
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  page.on('dialog', dialog => dialog.dismiss());
  context.on('requestfailed', request => {if (disconnected && request.url().startsWith('http')) failed.push({url: request.url(), error: request.failure()?.errorText});});
  context.on('response', response => {if (disconnected && response.url().startsWith('http')) requests.push({url: response.url(), cached: response.fromServiceWorker()});});
  // Prove that a partial preparation cannot enable encoding and can be retried.
  await context.route('**/ffmpeg-runtime/ffmpeg-core-0.wasm.part', route => route.fulfill({status: 503, body: 'Test download interruption'}));
  await page.goto(process.env.WEBENC_URL || 'http://127.0.0.1:4175/');
  await expect(page.locator('.offline-status')).toContainText('HTTP 503', {timeout: 90000});
  await expect(page.getByRole('button', {name: 'Preparing encoder…', exact: true})).toBeDisabled();
  await expect(page.getByLabel('Activity log', {exact: true})).toContainText('Offline preparation failed:');
  await context.unroute('**/ffmpeg-runtime/ffmpeg-core-0.wasm.part');
  await page.getByRole('button', {name: 'Retry download', exact: true}).click();
  await expect(page.locator('.offline-status')).toContainText('Offline ready', {timeout: 90000});
  const preparation = await page.getByLabel('Activity log', {exact: true}).textContent();
  expect(preparation).toContain('Using saved asset:');
  for (const asset of ['ffmpeg-runtime/', 'python-runtime/', 'm68k-runtime/', 'player-code.zip']) expect(preparation).toContain('Verified and saved: /' + asset);
  await context.setOffline(true);
  disconnected = true;
  // The untouched tab and a completely offline reload must both remain usable.
  await page.reload();
  await expect(page.locator('.offline-status')).toContainText('Offline ready', {timeout: 30000});
  await page.locator('input[type=file]').first().setInputFiles(source);
  await expect(page.getByRole('button', {name: 'Generate CAVC', exact: true})).toBeEnabled({timeout: 15000});
  await page.getByLabel('Picture dimensions').selectOption('320x224');
  await page.getByRole('button', {name: 'Generate CAVC', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Download ZIP', exact: true})).toBeEnabled({timeout: 300000});
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', {name: 'Download ZIP', exact: true}).click();
  const download = await downloadPromise;
  const files = unzipSync(new Uint8Array(await readFile(await download.path())));
  for (const name of ['HEADER.DAT', 'BODY.DAT', 'MOVIE.DAT', 'preview.mp4', 'playback.wav']) expect(files[name].length).toBeGreaterThan(0);
  expect(Object.keys(files).some(name => name.endsWith('.iso'))).toBe(true);
  expect(Object.keys(files).some(name => name.endsWith('.cue'))).toBe(true);
  downloads.push(download.suggestedFilename());
  // Repeat after discarding the first Worker: cancellation/completion must not
  // be relying on an already initialized Python/FFmpeg module in memory.
  await page.getByRole('button', {name: 'Generate CAVC', exact: true}).click();
  await expect(page.getByRole('button', {name: 'Download ZIP', exact: true})).toBeEnabled({timeout: 300000});
  await page.getByRole('button', {name: 'Licenses', exact: true}).click();
  const modal = page.getByRole('dialog');
  await expect(modal.getByRole('heading', {level: 3})).toHaveCount(14);
  await expect(modal.locator('.license-entry').first()).toContainText('MIT');
  expect(errors).toEqual([]);
  expect(failed).toEqual([]);
  expect(requests.length).toBeGreaterThan(10);
  expect(requests.every(request => request.cached)).toBe(true);
  const receipt = {gate: 'PASS', source, url: page.url(), offlineEncodes: 2, errors, failed, requests, downloads, preparation,
    log: await page.getByLabel('Activity log', {exact: true}).textContent()};
  await writeFile(repo + 'logs/webenc_offline_verification.json', JSON.stringify(receipt, null, 2) + '\n');
  console.log(JSON.stringify({gate: receipt.gate, offlineEncodes: receipt.offlineEncodes, cachedResponses: requests.length, downloads}));
} finally {
  await browser.close();
  lease.stdin.end();
}
