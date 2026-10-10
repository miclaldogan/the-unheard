const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright-core",
);
const fs = require("fs");
const out = process.env.UNHEARD_REVIEW_DIR || "/tmp/unheard-browser-review";
const reviewUrl = process.env.UNHEARD_REVIEW_URL || "http://127.0.0.1:5173";
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || undefined,
    headless: true,
    chromiumSandbox: true,
    args: [
      "--use-fake-device-for-media-stream",
      "--use-fake-ui-for-media-stream",
    ],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
    permissions: ["microphone"],
    acceptDownloads: true,
  });
  if (process.env.UNHEARD_REVIEW_TOKEN)
    await context.addInitScript(
      (token) => localStorage.setItem("unheard.token", token),
      process.env.UNHEARD_REVIEW_TOKEN,
    );
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(reviewUrl);
  await page.locator(".chamber-copy .narrative-voice").waitFor();
  if (!fs.existsSync(out + "/01-chamber-desktop.png"))
    await page.screenshot({
      path: out + "/01-chamber-desktop.png",
      fullPage: true,
    });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "Field", exact: true }).click();
  await page.screenshot({
    path: out + "/02-field-ready-mobile.png",
    fullPage: true,
  });
  const rec = page.locator(".field-recorder");
  await rec.getByLabel("start recording").click();
  await rec.getByLabel("stop recording").waitFor();
  if (
    await page.getByRole("button", { name: "Hearing", exact: true }).isEnabled()
  )
    throw Error("Navigation did not lock during recording");
  await page.screenshot({
    path: out + "/03-field-recording-mobile.png",
    fullPage: true,
  });
  await page.waitForTimeout(3900);
  await rec.getByLabel("stop recording").click();
  await rec.getByText(/Saved on this device/).waitFor();
  await context.setOffline(true);
  await rec.getByRole("button", { name: "Submit for analysis" }).click();
  await rec.getByRole("alert").waitFor();
  const idbCount = await page.evaluate(
    () =>
      new Promise((resolve, reject) => {
        const q = indexedDB.open("unheard-field", 1);
        q.onsuccess = () => {
          const db = q.result;
          const tx = db.transaction("captures", "readonly");
          const read = tx.objectStore("captures").getAll();
          read.onsuccess = () =>
            resolve(
              read.result.map((c) => ({
                id: c.id,
                bytes: c.blob.size,
                serverId: c.serverId,
              })),
            );
          tx.oncomplete = () => db.close();
        };
        q.onerror = () => reject(q.error);
      }),
  );
  if (idbCount.length !== 1 || idbCount[0].bytes === 0 || idbCount[0].serverId)
    throw Error("Offline save did not preserve bytes");
  await page.screenshot({
    path: out + "/04-field-offline-saved-mobile.png",
    fullPage: true,
  });
  await context.setOffline(false);
  await rec.getByRole("button", { name: "Submit for analysis" }).click();
  await rec.getByText(/Synchronized and measured/).waitFor({ timeout: 60000 });
  await page.getByRole("button", { name: "Open in laboratory" }).click();
  await page.getByLabel("new label").waitFor({ timeout: 15000 });
  await page.getByLabel("new label").fill("Browser test signal");
  await page.getByRole("button", { name: "Teach ECHO-0", exact: true }).click();
  await page.getByText(/A memory has taken shape/).waitFor();
  await page.setViewportSize({ width: 1366, height: 900 });
  await page.screenshot({
    path: out + "/05-hearing-laptop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Open visual memory" }).click();
  await page.getByRole("img", { name: /acoustic signature of/ }).waitFor();
  const audio = page.getByLabel("original recording");
  await audio.evaluate((el) => el.play());
  await page.waitForTimeout(250);
  await audio.evaluate((el) => el.pause());
  await page.screenshot({
    path: out + "/06-specimen-laptop.png",
    fullPage: true,
  });
  await page
    .getByRole("button", { name: "Atlas", exact: true })
    .first()
    .click();
  await page.getByLabel("select atlas memory").selectOption({ index: 1 });
  await page.getByRole("button", { name: "zoom in atlas" }).click();
  await page.screenshot({ path: out + "/07-atlas-laptop.png", fullPage: true });
  await page
    .getByRole("button", { name: "Open specimen", exact: true })
    .click();
  await page.getByRole("img", { name: /acoustic signature of/ }).waitFor();
  await page.getByRole("button", { name: "Orchestra", exact: true }).click();
  await page.locator(".pick input[type=checkbox]").first().check();
  await page.getByRole("button", { name: "Organic", exact: true }).click();
  await page
    .getByRole("button", { name: "Compose from 1 sound", exact: true })
    .click();
  await page.getByRole("button", { name: "Composing…", exact: true }).waitFor();
  await page
    .getByRole("button", { name: "Compose from 1 sound", exact: true })
    .waitFor({ timeout: 60000 });
  await page
    .getByRole("button", { name: "Play", exact: true })
    .waitFor({ timeout: 60000 });
  await page.getByRole("button", { name: "Play", exact: true }).click();
  await page.waitForTimeout(700);
  await page
    .getByRole("button", { name: "Atlas", exact: true })
    .first()
    .click();
  await page.waitForTimeout(600);
  await page.getByRole("button", { name: "Orchestra", exact: true }).click();
  await page.getByRole("button", { name: "Pause", exact: true }).waitFor();
  const mute = page.getByRole("button", { name: /^mute / }).first();
  await mute.click();
  if ((await mute.getAttribute("aria-pressed")) !== "true")
    throw Error("Mute failed");
  await mute.click();
  const solo = page.getByRole("button", { name: /^solo / }).first();
  await solo.click();
  await solo.click();
  await page.getByRole("slider", { name: "seek", exact: true }).fill("10");
  await page.getByRole("button", { name: "Pause", exact: true }).click();
  await page.screenshot({
    path: out + "/08-orchestra-organic-laptop.png",
    fullPage: true,
  });
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("link", { name: "Export WAV", exact: true }).click();
  const download = await downloadEvent;
  if (await download.failure()) throw Error("WAV export failed");
  await page.getByRole("button", { name: "Composed", exact: true }).click();
  const picks = page.locator(".pick input[type=checkbox]");
  const sourceCount = Math.min(3, await picks.count());
  for (let i = 0; i < sourceCount; i++) await picks.nth(i).check();
  await page
    .getByRole("button", {
      name: new RegExp(`Compose from ${sourceCount} sound`),
    })
    .click();
  await page.getByRole("button", { name: "Composing…", exact: true }).waitFor();
  await page
    .getByRole("button", {
      name: new RegExp(`Compose from ${sourceCount} sound`),
    })
    .waitFor({ timeout: 60000 });
  await page
    .getByRole("button", { name: "Play", exact: true })
    .waitFor({ timeout: 60000 });
  await page.screenshot({
    path: out + "/09-orchestra-composed-laptop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 844, height: 390 });
  await page.getByRole("button", { name: "Field", exact: true }).click();
  await page.screenshot({
    path: out + "/10-field-landscape.png",
    fullPage: true,
  });
  const overflow = await page.evaluate(() => ({
    width: innerWidth,
    scroll: document.documentElement.scrollWidth,
  }));
  const state = await page.request
    .get(`${reviewUrl}/api/narrative/state`)
    .then((r) => r.json());
  fs.writeFileSync(
    out + "/browser-results.json",
    JSON.stringify(
      {
        browser: await browser.version(),
        fakeMicrophone: true,
        physicalDevice: false,
        errors,
        offlineCapture: idbCount,
        landscape: overflow,
        narrative: { act: state.act, phase: state.phase, counts: state.counts },
        checks: [
          "M5 first-use",
          "microphone workflow",
          "navigation locked during capture",
          "real IndexedDB bytes",
          "offline upload retains capture",
          "manual retry",
          "real DSP processing",
          "backend annotation",
          "specimen playback",
          "atlas selection and zoom",
          "Organic composition",
          "playback continuity to Atlas",
          "mute and solo",
          "seek",
          "WAV export",
          "Composed composition",
        ],
      },
      null,
      2,
    ),
  );
  if (errors.length) throw Error(errors.join("\n"));
  await browser.close();
  console.log("Browser walkthrough passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
