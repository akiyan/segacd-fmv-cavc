import {fileURLToPath} from 'node:url';
import { chromium, expect } from "@playwright/test";
import { unzipSync, strFromU8 } from "fflate";
import { readFile, mkdir } from "node:fs/promises";
const output = "/dev/shm/segacd-fmv-cavc/webenc-qa";
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1024 },
  deviceScaleFactor: 1,
  acceptDownloads: true,
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
page.on("console", (msg) => {
  if (msg.type() === "error") errors.push(msg.text());
});
await page.goto(process.env.WEBENC_URL || "http://127.0.0.1:4173");
await expect(page.getByRole("button", {name:"Generate CAVC",exact:true})).toBeDisabled();
await page.locator('input[type=file]').first().setInputFiles(fileURLToPath(new URL('../public/sample-test.mp4',import.meta.url)));
await expect(page.getByRole("button", {name:"Generate CAVC",exact:true})).toBeEnabled();
await page.getByLabel('Picture dimensions').selectOption('320x224');
await expect(page.getByRole("button", { name: "Generate CAVC" })).toBeEnabled({timeout:15000});
await page.waitForFunction(() => document.querySelector(".source-surface video")?.readyState >= 2);
await page.screenshot({ path: `${output}/desktop-ready.png`, fullPage: true });
expect(await page.evaluate(() => document.body.scrollWidth)).toBe(1440);
expect(
  await page.evaluate(() => document.body.scrollHeight),
).toBeLessThanOrEqual(1024);
await page.getByRole("spinbutton", {name:"Crop W",exact:true}).fill("500");
const crop = page.getByTestId("crop-rectangle");
let box = await crop.boundingBox();
await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
await page.mouse.down();
await page.mouse.move(box.x + box.width / 2 + 20, box.y + box.height / 2 + 10, {
  steps: 8,
});
await page.mouse.up();
expect(
  Number(
    await page
      .getByRole("spinbutton", { name: "Crop X", exact: true })
      .inputValue(),
  ),
).toBeGreaterThan(0);
const originalWidth = Number(
  await page
    .getByRole("spinbutton", { name: "Crop W", exact: true })
    .inputValue(),
);
const handle = await page.getByTestId("crop-se").boundingBox();
await page.mouse.move(handle.x + 5, handle.y + 5);
await page.mouse.down();
await page.mouse.move(handle.x - 35, handle.y - 20, { steps: 8 });
await page.mouse.up();
expect(
  Number(
    await page
      .getByRole("spinbutton", { name: "Crop W", exact: true })
      .inputValue(),
  ),
).toBeLessThan(originalWidth);
await page.getByLabel("Lock aspect").uncheck();
await page
  .getByRole("spinbutton", { name: "Crop X", exact: true })
  .fill("999999");
const x = Number(
    await page
      .getByRole("spinbutton", { name: "Crop X", exact: true })
      .inputValue(),
  ),
  w = Number(
    await page
      .getByRole("spinbutton", { name: "Crop W", exact: true })
      .inputValue(),
  );
expect(x + w).toBeLessThanOrEqual(640);
await page.getByRole("button", { name: "Reset crop" }).click();
expect(
  await page
    .getByRole("spinbutton", { name: "Crop W", exact: true })
    .inputValue(),
).toBe("640");
await page.getByRole("button", { name: "Custom", exact: true }).click();
await page.getByLabel("Pixel aspect numerator").fill("2");
await page.getByLabel("Pixel aspect denominator").fill("1");
const mediaBox = await page.locator(".source-surface").boundingBox();
expect(mediaBox.width / mediaBox.height).toBeCloseTo((640 * 2) / 360, 1);
await page.getByLabel("Pixel aspect denominator").fill("0");
await expect(
  page.getByRole("button", { name: "Generate CAVC" }),
).toBeDisabled();
await page.getByLabel("Pixel aspect denominator").fill("1");
await page.getByRole("button", { name: "1:1", exact: true }).click();
await page.getByLabel("Frame rate", { exact: true }).selectOption("15");
await page.getByLabel("Picture dimensions").selectOption("320x224");
await page.getByLabel("Fit", { exact: true }).selectOption("crop");
await page.route("**/python-runtime/pyodide.asm.wasm", async route => {
  await new Promise(resolve=>setTimeout(resolve,700));
  try { await route.continue(); } catch {}
});
await page.getByRole("button", { name: "Generate CAVC" }).click();
await expect(page.getByLabel("Frame rate", { exact: true })).toBeDisabled();
await page.getByRole("button", { name: "Cancel", exact: true }).click();
await expect(page.getByLabel("Frame rate", { exact: true })).toBeEnabled();
await expect(page.getByRole("button", { name: "Download ZIP" })).toBeDisabled();
await page.getByLabel("Frame rate", { exact: true }).selectOption("24");
await page.getByLabel("Picture dimensions").selectOption("320x168");
await page.getByLabel("Fit", { exact: true }).selectOption("pad");
await page.getByRole("button", { name: "Generate CAVC" }).click();
await page.waitForFunction(() => Number(document.querySelector('[role="progressbar"]').getAttribute("aria-valuenow")) >= 70, null, { timeout: 180000 });
await page.screenshot({
  path: `${output}/desktop-running.png`,
  fullPage: true,
});
await expect(page.getByRole("button", { name: "Download ZIP" })).toBeEnabled({
  timeout: 180000,
});
const downloadPromise = page.waitForEvent("download");
await page.getByRole("button", { name: "Download ZIP" }).click();
const download = await downloadPromise;
const zipPath = `${output}/${download.suggestedFilename()}`;
await download.saveAs(zipPath);
const files = unzipSync(await readFile(zipPath));
for (const name of ["README.txt","preview.mp4","playback.wav","HEADER.DAT","BODY.DAT","MOVIE.DAT","settings.json","playback-frames.tsv"]) expect(files[name]?.byteLength).toBeGreaterThan(0);
const settings = JSON.parse(strFromU8(files["settings.json"]));
expect(Number(settings.input.fps)).toBe(24);
expect(settings.input.inputSettings.audio.mode).toBe("source");
expect(settings.input.inputSettings.audio).not.toHaveProperty("file");
expect(settings.input.inputSettings.source.crop.w).toBe(640);
expect(strFromU8(files["README.txt"])).toContain("bootable Sega CD disc");
await page.getByRole("spinbutton", { name: "Crop X", exact: true }).fill("1");
await expect(page.getByRole("button", { name: "Download ZIP" })).toBeDisabled();
await page
  .locator("input[type=file]")
  .first()
  .setInputFiles(`${output}/test-video.mp4`);
await expect(
  page.getByRole("spinbutton", { name: "Crop W", exact: true }),
).toHaveValue("640");
await page.waitForFunction(
  () => document.querySelector(".source-surface video")?.readyState >= 2,
);
const firstFrame = await page
  .locator("canvas")
  .evaluate((el) => el.toDataURL());
await page.getByRole("button", { name: "Play preview", exact: true }).click();
await page.waitForFunction(
  () => document.querySelector(".source-surface video").currentTime > 0.4,
);
await page.getByRole("button", { name: "Pause preview", exact: true }).click();
expect(await page.locator("canvas").evaluate((el) => el.toDataURL())).not.toBe(
  firstFrame,
);
await page.getByRole("slider", { name: "Preview position" }).fill("36");
await page.waitForFunction(
  () =>
    Math.abs(
      document.querySelector(".source-surface video").currentTime - 1.5,
    ) < 0.1,
);
await expect(
  page.getByRole("heading", { name: "Source audio", exact: true }),
).toHaveCount(0);
await expect(page.locator('input[type=file][accept*="audio"]')).toHaveCount(0);
await page.getByRole("button", { name: "Mute preview", exact: true }).click();
expect(
  await page.locator(".source-surface video").evaluate((v) => v.muted),
).toBe(true);
await page.getByRole("button", { name: "Unmute preview", exact: true }).click();
expect(
  await page.locator(".source-surface video").evaluate((v) => v.muted),
).toBe(false);
await page.getByRole("button", { name: "Advanced settings" }).click();
await page.getByLabel("Source fps", { exact: true }).fill("30");
await page.getByLabel("Frame rate", { exact: true }).selectOption("source");
await expect(
  page.getByText("320 × 168 picture · 30 fps selected"),
).toBeVisible();
await page.getByRole("button", { name: "Advanced settings" }).click();
await page.setViewportSize({ width: 390, height: 844 });
await page.waitForFunction(
  () =>
    document.querySelector(".source-surface").getBoundingClientRect().height >
    100,
);
await page.screenshot({ path: `${output}/mobile.png`, fullPage: true });
expect(await page.evaluate(() => document.body.scrollWidth)).toBe(390);
await expect(
  page.getByRole("button", { name: "Generate CAVC" }),
).toBeEnabled();
expect(errors).toEqual([]);
console.log(
  JSON.stringify({
    result: "PASS",
    checks: [
      "crop drag and resize",
      "crop bounds and reset",
      "source pixel aspect geometry and validation",
      "fps and fit",
      "cancel and retry",
      "worker progress",
      "ZIP contents and invalidation",
      "local video load/play/seek",
      "source-video audio and mute",
      "advanced settings",
      "desktop viewport",
      "mobile overflow",
      "console errors",
    ],
    zipPath,
    screenshots: output,
  }),
);
await browser.close();
