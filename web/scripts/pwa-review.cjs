const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright-core",
);
const fs = require("fs");
const out = process.env.UNHEARD_REVIEW_DIR || "/tmp/unheard-pwa-review";
const reviewUrl = process.env.UNHEARD_REVIEW_URL || "http://127.0.0.1:8000";
fs.mkdirSync(out, { recursive: true });
(async () => {
  const c = await chromium.launchPersistentContext(
    process.env.UNHEARD_REVIEW_PROFILE ||
      `/tmp/unheard-pwa-profile-${Date.now()}`,
    {
      executablePath: process.env.CHROME_PATH || undefined,
      headless: true,
      chromiumSandbox: true,
      args: [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
      ],
      viewport: { width: 390, height: 844 },
      permissions: ["microphone"],
      reducedMotion: "reduce",
    },
  );
  if (process.env.UNHEARD_REVIEW_TOKEN)
    await c.addInitScript(
      (token) => localStorage.setItem("unheard.token", token),
      process.env.UNHEARD_REVIEW_TOKEN,
    );
  const p = await c.newPage();
  const errors = [];
  p.on("pageerror", (e) => errors.push(e.message));
  await p.goto(reviewUrl);
  await p.evaluate(() => navigator.serviceWorker.ready);
  await p.reload();
  await p.waitForFunction(() => !!navigator.serviceWorker.controller);
  const install = await (
    await c.newCDPSession(p)
  ).send("Page.getInstallabilityErrors");
  const load = await p.evaluate(() => ({
    domContentLoaded:
      performance.getEntriesByType("navigation")[0].domContentLoadedEventEnd,
    heap: performance.memory?.usedJSHeapSize,
  }));
  await c.setOffline(true);
  await p.reload();
  await p.waitForTimeout(800);
  await p.getByRole("button", { name: "Field", exact: true }).click();
  const rec = p.locator(".field-recorder");
  await rec.getByLabel("start recording").click();
  await rec.getByLabel("stop recording").waitFor();
  await p.waitForTimeout(3500);
  await rec.getByLabel("stop recording").click();
  await rec.getByText(/Saved on this device/).waitFor();
  await p.screenshot({
    path: `${out}/11-pwa-offline-mobile.png`,
    fullPage: true,
  });
  await c.setOffline(false);
  await rec.getByRole("button", { name: "Submit for analysis" }).click();
  await rec.getByText(/Synchronized and measured/).waitFor({ timeout: 60000 });
  await p.getByRole("button", { name: "Open in laboratory" }).click();
  await p.getByRole("button", { name: "Open visual memory" }).click();
  await p.getByRole("img", { name: /acoustic signature of/ }).waitFor();
  const audio = p.getByLabel("original recording");
  await p.waitForFunction(() =>
    document
      .querySelector('audio[aria-label="original recording"]')
      ?.src.startsWith("blob:"),
  );
  await audio.evaluate((a) => a.play());
  await audio.evaluate((a) => a.pause());
  const cache = await p.evaluate(async () => {
    const names = await caches.keys();
    const urls = [];
    for (const n of names) {
      for (const r of await (await caches.open(n)).keys())
        urls.push(new URL(r.url).pathname);
    }
    return urls;
  });
  if (cache.some((u) => u.startsWith("/api/")))
    throw Error("Private API cached");
  if (install.installabilityErrors.length) throw Error(JSON.stringify(install));
  if (errors.length) throw Error(errors.join("\n"));
  fs.writeFileSync(
    `${out}/pwa-results.json`,
    JSON.stringify(
      {
        browser: c.browser()?.version(),
        installability: install,
        offlineReload: true,
        offlineMicrophoneCapture: true,
        authenticatedUpload: true,
        authenticatedSpecimenPlayback: true,
        cachedPaths: cache,
        load,
        errors,
      },
      null,
      2,
    ),
  );
  await c.close();
  console.log("Production PWA and authenticated audio passed");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
