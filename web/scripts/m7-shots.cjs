/**
 * Presentation screenshots against a backend already seeded by m7_synthetic_journey.py.
 * Captures every scene at desktop and mobile, tolerating anything that is not reachable.
 *
 *   UNHEARD_REVIEW_URL=http://127.0.0.1:8013 \
 *   UNHEARD_SHOT_DIR=/tmp/unheard-shots/png \
 *   PLAYWRIGHT_MODULE=<path>/node_modules/playwright-core \
 *   CHROME_PATH=/usr/bin/google-chrome-stable node shots.cjs
 */
const { chromium } = require(
  process.env.PLAYWRIGHT_MODULE || "playwright-core",
);
const fs = require("fs");

const out = process.env.UNHEARD_SHOT_DIR || "/tmp/unheard-shots/png";
const url = process.env.UNHEARD_REVIEW_URL || "http://127.0.0.1:8013";
const DESKTOP = { width: 1440, height: 1000 };
const MOBILE = { width: 390, height: 844 };

fs.mkdirSync(out, { recursive: true });

const log = [];
const note = (m) => {
  console.log(m);
  log.push(m);
};

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
    viewport: DESKTOP,
    reducedMotion: "reduce",
    permissions: ["microphone"],
    deviceScaleFactor: 2, // crisp enough for slides
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));

  const shot = async (name, size) => {
    await page.setViewportSize(size);
    // drop focus so the "Skip to experience" link does not sit over the first panel
    await page.evaluate(() => {
      const a = document.activeElement;
      if (a && a !== document.body && typeof a.blur === "function") a.blur();
      window.scrollTo(0, 0);
    });
    await page.waitForTimeout(700);
    const file = `${out}/${name}.png`;
    await page.screenshot({ path: file, fullPage: true });
    const kb = Math.round(fs.statSync(file).size / 1024);
    note(`  ${name}.png  ${size.width}x${size.height}  ${kb} KB`);
  };

  const nav = async (label) => {
    const b = page.getByRole("button", { name: label, exact: true }).first();
    if (!(await b.isVisible().catch(() => false))) return false;
    if (!(await b.isEnabled().catch(() => false))) return false;
    await b.click();
    await page.waitForTimeout(900);
    return true;
  };

  const step = async (name, fn) => {
    try {
      await fn();
    } catch (e) {
      note(
        `  SKIPPED ${name}: ${String(e.message).split("\n")[0].slice(0, 110)}`,
      );
    }
  };

  await page.goto(url, { waitUntil: "networkidle" });
  await page
    .locator(".chamber-copy .narrative-voice")
    .waitFor({ timeout: 30000 });

  note("Chamber");
  await shot("01-chamber-desktop", DESKTOP);
  await shot("02-chamber-mobile", MOBILE);

  note("Field");
  await step("field", async () => {
    if (!(await nav("Field"))) throw Error("Field not reachable");
    await shot("03-field-desktop", DESKTOP);
    await shot("04-field-mobile", MOBILE);
  });

  note("Hearing");
  await step("hearing", async () => {
    if (!(await nav("Hearing"))) throw Error("Hearing not reachable");
    await page.setViewportSize(DESKTOP);
    // Open a preserved signal so the analysis panel, the hypothesis and Specimen all become reachable.
    // aria-label is "analyse <recording id>"; prefer the held-out clip so the taught label is on screen
    const held = process.env.UNHEARD_HELD_ID;
    let analyse = held
      ? page.getByRole("button", { name: `analyse ${held}`, exact: true })
      : page.getByRole("button", { name: /^analyse / });
    if (!(await analyse.count()))
      analyse = page.getByRole("button", { name: /^analyse / });
    if (await analyse.count()) {
      await analyse.first().click();
      // the fused prediction carries the taught label; wait for it rather than a fixed delay
      await page
        .getByText(/Roof gutter|Bells/)
        .first()
        .waitFor({ timeout: 60000 })
        .catch(() => {});
      await page.waitForTimeout(1500);
    }
    await shot("05-hearing-desktop", DESKTOP);
    await shot("06-hearing-mobile", MOBILE);
  });

  note("Specimen");
  await step("specimen", async () => {
    await page.setViewportSize(DESKTOP);
    const open = page
      .getByRole("button", { name: /Open visual memory|Open specimen/ })
      .first();
    if (!(await open.isVisible().catch(() => false)))
      throw Error("no specimen entry point");
    await open.click();
    await page
      .getByRole("img", { name: /acoustic signature of/ })
      .waitFor({ timeout: 20000 });
    await shot("07-specimen-desktop", DESKTOP);
    await shot("08-specimen-mobile", MOBILE);
  });

  note("Atlas");
  await step("atlas", async () => {
    if (!(await nav("Atlas"))) throw Error("Atlas not reachable");
    await step("atlas-select", async () => {
      await page.getByLabel("select atlas memory").selectOption({ index: 1 });
      await page.waitForTimeout(500);
    });
    await shot("09-atlas-desktop", DESKTOP);
    await shot("10-atlas-mobile", MOBILE);
  });

  note("Orchestra");
  await step("orchestra", async () => {
    if (!(await nav("Orchestra"))) throw Error("Orchestra not reachable");
    await page.setViewportSize(DESKTOP);
    // Pick the three taught bells and actually render, so the player and layers are on screen.
    const picks = page.locator(".pick input[type=checkbox]");
    const total = await picks.count();
    const n = Math.min(3, total);
    for (let i = 0; i < n; i++) await picks.nth(i).check();
    const compose = page.getByRole("button", {
      name: new RegExp(`Compose from ${n} sound`),
    });
    await compose.click();
    await page
      .getByRole("button", { name: "Composing…", exact: true })
      .waitFor({ timeout: 15000 })
      .catch(() => {});
    await page
      .getByRole("button", { name: "Play", exact: true })
      .waitFor({ timeout: 120000 });
    await page.getByRole("button", { name: "Play", exact: true }).click();
    await page.waitForTimeout(2500);
    await page
      .getByRole("button", { name: "Pause", exact: true })
      .click()
      .catch(() => {});
    await shot("11-orchestra-desktop", DESKTOP);
    await shot("12-orchestra-mobile", MOBILE);
  });

  note("Field, landscape");
  await step("landscape", async () => {
    if (!(await nav("Field"))) throw Error("Field not reachable");
    await shot("13-field-landscape", { width: 844, height: 390 });
  });

  const state = await page.request
    .get(`${url}/api/narrative/state`)
    .then((r) => r.json());
  const atlas = await page.request
    .get(`${url}/api/atlas`)
    .then((r) => r.json());
  fs.writeFileSync(
    `${out}/shots.json`,
    JSON.stringify(
      {
        browser: await browser.version(),
        audio:
          "synthetic set from scripts/m7_synthetic_sounds.py; not field recordings",
        seededBy: "scripts/m7_synthetic_journey.py",
        physicalDevice: false,
        note: "mobile frames are emulated viewports in desktop Chrome, not a physical phone",
        viewports: {
          desktop: DESKTOP,
          mobile: MOBILE,
          landscape: { width: 844, height: 390 },
        },
        deviceScaleFactor: 2,
        taught: state.counts,
        phase: state.phase,
        endingUnlocked: state.ending_unlocked,
        atlasNodes: (atlas.nodes || []).length,
        pageErrors: errors,
        log,
      },
      null,
      2,
    ) + "\n",
  );

  note(`\npage errors: ${errors.length ? errors.join(" | ") : "none"}`);
  await browser.close();
})().catch((e) => {
  console.error("FAILED:", e);
  process.exit(1);
});
