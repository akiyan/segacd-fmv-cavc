import {fileURLToPath} from 'node:url';
import { chromium, expect } from "@playwright/test";
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({
  viewport: { width: 1440, height: 1024 },
  acceptDownloads: true,
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
await page.goto(process.env.WEBENC_URL || "http://127.0.0.1:4173");
await expect(page.getByRole("button", {name:"Generate CAVC",exact:true})).toBeDisabled();
await page.locator('input[type=file]').first().setInputFiles(fileURLToPath(new URL('../public/sample-test.mp4',import.meta.url)));
await expect(page.getByRole("button", {name:"Generate CAVC",exact:true})).toBeEnabled();
await page.getByLabel('Picture dimensions').selectOption('320x224');
await expect(page.getByRole("button", { name: "Generate CAVC" })).toBeEnabled({timeout:15000});
await page.getByRole("button", { name: "Advanced settings" }).click();
const cap = page.getByRole("textbox", { name: "Cold cap", exact: true });
await expect(cap).toHaveValue("2:180,3:230");
await cap.fill("170");
await expect(page.getByText("Manual override", { exact: false })).toBeVisible();
await page.getByRole("button", { name: "Use automatic cap" }).click();
await expect(cap).toHaveValue("2:180,3:230");
await page.getByLabel("Picture dimensions").selectOption("320x168");
await page.getByLabel("Frame rate", { exact: true }).selectOption("30");
await expect(cap).toHaveValue("200");
await cap.fill("190");
await page.getByLabel("Picture dimensions").selectOption("320x224");
await expect(cap).toHaveValue("210");
await page.getByLabel("Frame rate", { exact: true }).selectOption("source");
await page.getByLabel("Source fps", { exact: true }).fill("59.94");
await expect(cap).toHaveValue("210");
await page.getByLabel("Frame rate", { exact: true }).selectOption("15");
await expect(cap).toHaveValue("380");
await page.getByLabel("Picture dimensions").selectOption("320x144");
await expect(cap).toHaveValue("480");
await page.getByLabel("Frame rate", { exact: true }).selectOption("30");
await expect(cap).toHaveValue("230");
await page.getByLabel("Frame rate", { exact: true }).selectOption("24");
await expect(cap).toHaveValue("2:210,3:265");
await expect(
  page.getByText("Profile-based estimate", { exact: false }),
).toBeVisible();
await page.getByLabel("Picture dimensions").selectOption("320x168");
await expect(cap).toHaveValue("2:180,3:230");
await cap.fill("2:160,3:220");
await expect(
  page.getByRole("button", { name: "Generate CAVC" }),
).toBeEnabled();
await cap.fill("2:160");
await expect(
  page.getByRole("button", { name: "Generate CAVC" }),
).toBeDisabled();
await cap.fill("0");
await expect(
  page.getByRole("button", { name: "Generate CAVC" }),
).toBeDisabled();
await cap.fill("2:160,3:220");
await page.screenshot({
  path: "/dev/shm/segacd-fmv-cavc/webenc-qa/cold-cap-manual.png",
  fullPage: true,
});
expect(errors).toEqual([]);
console.log(
  "PASS: profile scalar/cadence caps, conservative unmatched cap, 59.94-to-30 automatic output, manual override/reset, geometry reset and invalid-cadence rejection.",
);
await browser.close();
