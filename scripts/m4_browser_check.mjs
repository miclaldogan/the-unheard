// M4.5 real-browser validation  (STATUS: harness written but NOT yet run to completion; see
// docs/M4-LISTENING-REVIEW.md — in the authoring sandbox Chrome could not complete any HTTP load): drives a real (headless) Google Chrome through the Chrome
// DevTools Protocol using only Node built-ins (WebSocket, fetch, FormData; Node >= 22).
//
//   cd <repo> && (cd web && npm run build) && node scripts/m4_browser_check.mjs [--out DIR] [--chrome PATH]
//
// It starts its own `unheard serve` on a scratch data directory (model disabled), uploads real
// ESC-50 clips from server/data/eval/esc50 (git-ignored; CC BY-NC, local use only), then
// exercises the Orchestra in Chrome and prints one JSON report. A headless browser can verify
// that audio decodes and plays on a running AudioContext, but it cannot HEAR it: a human still
// has to listen (docs/M4-LISTENING-REVIEW.md).
import { spawn } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, rmSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const args = process.argv.slice(2);
const arg = (k, d) => (args.includes(k) ? args[args.indexOf(k) + 1] : d);
const OUT = resolve(arg('--out', join(ROOT, 'server/data/m4_browser')));
const CHROME = arg('--chrome', '/opt/google/chrome/chrome');
const PORT = 8124;
const CDP_PORT = 9333;
const BASE = `http://127.0.0.1:${PORT}`;
const ESC = join(ROOT, 'server/data/eval/esc50');
const CLIPS = ['1-12653-A-15.wav', '1-34495-A-14.wav', '1-137296-A-16.wav', '1-155858-A-25.wav', '1-17367-A-10.wav'];
mkdirSync(OUT, { recursive: true });

const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const check = (name, ok, detail = '') => {
  results.push({ name, ok: !!ok, detail: String(detail) });
  console.error(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
};

// ---------------------------------------------------------------- processes
const data = join(tmpdir(), `unheard-m4-browser-${process.pid}`);
rmSync(data, { recursive: true, force: true });
const server = spawn('uv', ['run', 'unheard', 'serve', '--port', String(PORT)], {
  cwd: join(ROOT, 'server'),
  env: { ...process.env, UNHEARD_DATA_DIR: data, UNHEARD_MODEL_NAME: 'none' },
  stdio: 'ignore',
});
const profile = join(tmpdir(), `unheard-chrome-${process.pid}`);
let chrome;
const cleanup = () => { try { server.kill(); } catch {} try { chrome?.kill(); } catch {} rmSync(profile, { recursive: true, force: true }); rmSync(data, { recursive: true, force: true }); };
process.on('exit', cleanup);

async function waitFor(fn, ms = 30000, step = 200) {
  const end = Date.now() + ms;
  for (;;) {
    try { const v = await fn(); if (v) return v; } catch {}
    if (Date.now() > end) return null;
    await sleep(step);
  }
}

// ---------------------------------------------------------------- tiny CDP client
class CDP {
  constructor(ws) { this.ws = ws; this.id = 0; this.sessionId = undefined; this.pending = new Map(); this.listeners = []; ws.addEventListener('message', (m) => { const d = JSON.parse(m.data); if (d.id && this.pending.has(d.id)) { const { res, rej } = this.pending.get(d.id); this.pending.delete(d.id); d.error ? rej(new Error(d.error.message)) : res(d.result); } else if (d.method) this.listeners.forEach((l) => l(d)); }); }
  send(method, params = {}, sessionId = this.sessionId) { const id = ++this.id; this.ws.send(JSON.stringify({ id, method, params, sessionId })); return new Promise((res, rej) => this.pending.set(id, { res, rej })); }
  on(fn) { this.listeners.push(fn); }
}
let cdp;
const ev = async (expression) => {
  const r = await Promise.race([cdp.send('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true }), sleep(30000).then(() => { throw new Error('CDP evaluate timed out: ' + expression.slice(0, 80)); })]);
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description || r.exceptionDetails.text);
  return r.result.value;
};
const shot = async (name) => { const r = await cdp.send('Page.captureScreenshot', { format: 'png' }); writeFileSync(join(OUT, `${name}.png`), Buffer.from(r.data, 'base64')); };
const clickText = (selector, text) => ev(`(() => { const el = [...document.querySelectorAll(${JSON.stringify(selector)})].find(e => e.textContent.trim().startsWith(${JSON.stringify(text)}) && !e.disabled); if (!el) return false; el.click(); return true; })()`);
const clickAria = (label) => ev(`(() => { const el = document.querySelector('[aria-label=${JSON.stringify(label)}]'); if (!el || el.disabled) return false; el.click(); return true; })()`);
const setRange = (label, value) => ev(`(() => { const el = document.querySelector('input[aria-label=${JSON.stringify(label)}]'); const set = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set; set.call(el, ${value}); el.dispatchEvent(new Event('input', { bubbles: true })); el.dispatchEvent(new Event('change', { bubbles: true })); return el.value; })()`);
const text = (sel) => ev(`document.querySelector(${JSON.stringify(sel)})?.innerText ?? null`);
const seekValue = () => ev(`Number(document.querySelector('input[aria-label="seek"]')?.value ?? -1)`);
const gains = () => ev(`window.__ac.gains.map(g => Math.round(g.gain.value * 100) / 100)`);
const hook = () => `
(() => {
  const ac = window.__ac = { ctxs: [], decoded: [], sources: [], gains: [], errors: [] };
  const Orig = window.AudioContext;
  window.AudioContext = class extends Orig {
    constructor(...a) { super(...a); ac.ctxs.push(this); }
    decodeAudioData(buf, ...r) { return super.decodeAudioData(buf, ...r).then((b) => { ac.decoded.push({ duration: b.duration, channels: b.numberOfChannels, rate: b.sampleRate }); return b; }); }
    createBufferSource() { const s = super.createBufferSource(); const st = s.start.bind(s); s.start = (...a) => { ac.sources.push({ at: this.currentTime, offset: a[1] }); return st(...a); }; return s; }
    createGain() { const g = super.createGain(); ac.gains.push(g); return g; }
  };
  window.addEventListener('error', (e) => ac.errors.push(String(e.message)));
  window.addEventListener('unhandledrejection', (e) => ac.errors.push('rejection: ' + String(e.reason)));
})();`;

async function api(path, init) { const r = await fetch(BASE + path, init); return r.headers.get('content-type')?.includes('json') ? r.json() : r; }

// ---------------------------------------------------------------- main
try {
  if (!existsSync(join(ROOT, 'web/dist/index.html'))) throw new Error('build the web app first: (cd web && npm run build)');
  if (!existsSync(join(ESC, CLIPS[0]))) throw new Error('ESC-50 clips missing (see eval/README.md)');
  if (!(await waitFor(async () => (await fetch(BASE + '/api/health')).ok, 60000))) throw new Error('server did not start');
  for (const f of CLIPS) {
    const form = new FormData();
    form.append('file', new Blob([readFileSync(join(ESC, f))], { type: 'audio/wav' }), f);
    form.append('captured_at', new Date().toISOString());
    const r = await fetch(BASE + '/api/recordings', { method: 'POST', body: form });
    if (r.status !== 202) throw new Error(`upload ${f}: ${r.status}`);
  }
  await waitFor(async () => (await api('/api/recordings')).items.every((r) => r.status === 'ready'), 60000);
  const recs = (await api('/api/recordings')).items;
  check('setup: 5 real recordings uploaded and processed', recs.length === 5 && recs.every((r) => r.status === 'ready'), `${recs.length} ready`);

  chrome = spawn(CHROME, ['--headless=new', '--disable-gpu', '--no-sandbox', '--no-first-run', '--no-default-browser-check', '--autoplay-policy=no-user-gesture-required', `--remote-debugging-port=${CDP_PORT}`, `--user-data-dir=${profile}`, '--window-size=1280,900', 'about:blank'], { stdio: 'ignore' });
  const version = await waitFor(async () => (await fetch(`http://127.0.0.1:${CDP_PORT}/json/version`)).json(), 30000);
  if (!version) throw new Error('Chrome did not start');
  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  cdp = new CDP(ws);
  // a fresh target attached through a flattened session (the initial about:blank page does not answer)
  const { targetId } = await cdp.send('Target.createTarget', { url: 'about:blank' });
  cdp.sessionId = (await cdp.send('Target.attachToTarget', { targetId, flatten: true })).sessionId;
  const consoleErrors = [];
  cdp.on((d) => {
    if (d.method === 'Runtime.exceptionThrown') consoleErrors.push(d.params.exceptionDetails.exception?.description || d.params.exceptionDetails.text);
    if (d.method === 'Runtime.consoleAPICalled' && d.params.type === 'error') consoleErrors.push(d.params.args.map((a) => a.value ?? a.description).join(' '));
  });
  await cdp.send('Runtime.enable');
  await cdp.send('Page.enable');
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: hook() });
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const ua = await ev('navigator.userAgent');
  await cdp.send('Page.navigate', { url: BASE + '/' });
  await waitFor(() => ev("!!document.querySelector('.views')"), 20000);
  check('app loads in real Chrome', true, ua.match(/Chrome\/[\d.]+/)?.[0]);

  // ---- 1. source selection
  await clickText('.views button', 'Orchestra');
  const boxes = await waitFor(() => ev(`document.querySelectorAll('.picklist input[type=checkbox]').length`).then((n) => n >= 5 && n), 15000);
  check('Orchestra lists the ready recordings as selectable sources', boxes === 5, `${boxes} checkboxes`);
  await ev(`document.querySelectorAll('.picklist input[type=checkbox]').forEach((c, i) => { if (i < 4 && !c.checked) c.click(); })`);
  await sleep(300);
  const composeLabel = await ev(`[...document.querySelectorAll('button')].map(b => b.textContent.trim()).find(t => t.startsWith('Compose from'))`);
  check('selecting four sources updates the compose button', composeLabel === 'Compose from 4 sounds', composeLabel);
  const labelsShown = await ev(`[...document.querySelectorAll('.pick-name')].map(e => e.textContent)`);
  check('atlas names are shown beside sources (or "unnamed" when the model is off)', labelsShown.length === 5, labelsShown.join(','));

  // ---- 2. create + render
  const t0 = Date.now();
  await clickText('button', 'Compose from 4');
  const ready = await waitFor(() => ev(`[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Play')`), 120000, 400);
  const renderS = ((Date.now() - t0) / 1000).toFixed(1);
  check('composition is created, rendered and loaded', ready, `${renderS} s from click to playable`);
  await shot('1-orchestra-ready');
  const nTracks = await ev(`document.querySelectorAll('.track').length`);
  check('one instrument/layer per source with role chips', nTracks === 4, `${nTracks} tracks: ` + (await ev(`[...document.querySelectorAll('.track .chip')].map(c => c.textContent).join(', ')`)));
  const dec = await ev('window.__ac.decoded');
  const compo = (await api('/api/compositions'))[0];
  const full = await api(`/api/compositions/${compo.id}`);
  check('Chrome decoded all four stems (48 kHz stereo, piece length)', dec.length === 4 && dec.every((d) => d.channels === 2 && Math.abs(d.duration - full.metrics.duration_s) < 0.1), JSON.stringify(dec[0]));
  const tl = await ev(`(() => { const c = document.querySelector('canvas.timeline'); const ctx = c.getContext('2d'); const d = ctx.getImageData(0, 0, c.width, c.height).data; let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 20) n++; return { w: c.width, h: c.height, painted: n }; })()`);
  check('timeline canvas is painted from real events', tl.painted > 2000, JSON.stringify(tl));

  // ---- 3. play / pause / seek
  await clickText('button', 'Play');
  await sleep(1800);
  const st1 = await ev(`({ state: window.__ac.ctxs[0].state, t: window.__ac.ctxs[0].currentTime, sources: window.__ac.sources.length, btn: [...document.querySelectorAll('button')].map(b => b.textContent.trim()).filter(t => t === 'Pause' || t === 'Play') })`);
  const s1 = await seekValue();
  check('Play: AudioContext running, 4 stems started, playhead advancing', st1.state === 'running' && st1.sources === 4 && s1 > 1.2 && st1.btn[0] === 'Pause', JSON.stringify({ ...st1, seek: s1 }));
  await clickText('button', 'Pause');
  await sleep(300);
  const p1 = await seekValue();
  await sleep(1200);
  const p2 = await seekValue();
  check('Pause: playhead freezes and the button flips back to Play', Math.abs(p2 - p1) < 0.1 && (await clickText('button', 'Play') ? true : false), `${p1.toFixed(2)} → ${p2.toFixed(2)}`);
  await clickText('button', 'Pause');
  await setRange('seek', 20);
  await sleep(150);
  const sv = await seekValue();
  await clickText('button', 'Play');
  await sleep(1500);
  const after = await seekValue();
  const lastSrc = await ev('window.__ac.sources.slice(-4).map(s => Math.round(s.offset * 10) / 10)');
  check('Seek to 20 s then play: audio restarts from 20 s on all stems', sv === 20 && after > 20.8 && after < 24 && lastSrc.every((o) => Math.abs(o - 20) < 0.2), JSON.stringify({ set: sv, after, offsets: lastSrc }));

  // ---- 4. mute / solo on the live graph
  await clickAria('mute Rain') || await ev(`document.querySelector('button[aria-label^="mute "]').click()`);
  await sleep(300);
  const g1 = await gains();
  check('Mute: exactly one stem gain goes to 0 while playing', g1.filter((v) => v === 0).length === 1 && g1.filter((v) => v === 1).length === 3, JSON.stringify(g1));
  await ev(`document.querySelectorAll('button[aria-label^="solo "]')[2].click()`);
  await sleep(300);
  const g2 = await gains();
  check('Solo: only the soloed stem is audible', g2.filter((v) => v === 1).length === 1 && g2[2] === 1, JSON.stringify(g2));
  await ev(`document.querySelectorAll('button[aria-label^="solo "]')[2].click(); document.querySelector('button[aria-label^="mute "]').click()`);
  await sleep(300);
  const g3 = await gains();
  check('Un-solo and un-mute restore all stems', g3.every((v) => v === 1), JSON.stringify(g3));

  // ---- 5. specimens + atlas react while playing
  const lv = await ev(`[...document.querySelectorAll('.instrument')].map(e => Number(getComputedStyle(e).getPropertyValue('--lv') || 0))`);
  await ev(`document.querySelector('input[aria-label="seek"]'); 0`);
  // find a moment where several events sound: pick the convergence section
  const events = await api(`/api/compositions/${compo.id}/events`);
  const conv = full.sections.find((s) => s.name === 'convergence');
  await clickText('button', 'Pause');
  await setRange('seek', (conv.start_s + 1).toFixed(2));
  await clickText('button', 'Play');
  await sleep(700);
  const lvPlaying = await ev(`[...document.querySelectorAll('.instrument')].map(e => Number(getComputedStyle(e).getPropertyValue('--lv') || 0))`);
  check('specimens light up in proportion to their events while playing', lvPlaying.some((v) => v > 0.05) && lvPlaying.filter((v) => v > 0.05).length < 5, JSON.stringify(lvPlaying));
  await shot('2-orchestra-playing');
  await clickText('.views button', 'Atlas');
  await sleep(900);
  const atlasSum = () => ev(`(() => { const c = document.querySelector('canvas.atlas-canvas'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data; let s = 0; for (let i = 0; i < d.length; i += 16) s += d[i] + d[i + 1] + d[i + 2]; return s; })()`);
  const a1 = await atlasSum();
  await sleep(500);
  const a2 = await atlasSum();
  await shot('3-atlas-while-playing');
  const stillPlaying = await ev(`window.__ac.ctxs[0].state === 'running'`);
  await clickText('.views button', 'Orchestra');
  await sleep(200);
  await clickText('button', 'Pause');
  await sleep(300);
  await clickText('.views button', 'Atlas');
  await sleep(500);
  const a3 = await atlasSum();
  await shot('4-atlas-paused');
  check('music keeps playing after switching to the Atlas', stillPlaying, '');
  check('Atlas canvas changes while the orchestra plays and settles when paused', a1 !== a2 || a1 !== a3, `playing ${a1}/${a2} vs paused ${a3}`);
  await clickText('.views button', 'Orchestra');
  await sleep(300);

  // ---- 6. comparison: original / layer / full
  await ev(`document.querySelector('button[aria-label^="inspect "]').click()`);
  await sleep(200);
  const hasCompare = await ev(`!!document.querySelector('[aria-label="source comparison"]')`);
  await clickText('button', '1 · Original');
  await sleep(1200);
  const orig = await ev(`(() => { const a = document.querySelector('audio[aria-label="original recording"]'); return { src: a.getAttribute('src'), paused: a.paused, t: a.currentTime, err: a.error?.code ?? null }; })()`);
  const playerPaused = await ev(`[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Play')`);
  check('Original recording plays through <audio> and the stems pause', hasCompare && orig.src?.includes('/audio') && !orig.paused && orig.t > 0.3 && !orig.err && playerPaused, JSON.stringify(orig));
  await clickText('button', '2 · Transformed');
  await sleep(500);
  const soloOn = await ev(`document.querySelector('button[aria-label^="solo "][aria-pressed="true"]') !== null`);
  const gl = await gains();
  const origStopped = await ev(`document.querySelector('audio[aria-label="original recording"]').paused`);
  check('Transformed layer = that stem soloed, original stops', soloOn && gl.filter((v) => v === 1).length === 1 && origStopped, JSON.stringify(gl));
  await clickText('button', '3 · Full');
  await sleep(500);
  const gf = await gains();
  check('Full composition = all stems audible', gf.every((v) => v === 1), JSON.stringify(gf));
  await clickText('button', 'Pause');

  // ---- 7. event timeline + provenance (real mouse click on a real event)
  const trackKeys = full.tracks.map((t) => t.track_key);
  const pick = events.find((e) => e.kind === 'slice' && e.comp_dur_s > 0.2 && e.comp_start_s > 3);
  const lane = trackKeys.indexOf(pick.track_key);
  const geo = await ev(`(() => { const c = document.querySelector('canvas.timeline'); c.scrollIntoView({ block: 'center' }); const r = c.getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width }; })()`);
  await sleep(200);
  const geo2 = await ev(`(() => { const r = document.querySelector('canvas.timeline').getBoundingClientRect(); return { x: r.left, y: r.top, w: r.width }; })()`);
  const cx = geo2.x + ((pick.comp_start_s + Math.min(pick.comp_dur_s, 0.15) / 2) / full.duration_s) * geo2.w;
  const cy = geo2.y + lane * 26 + 13;
  for (const type of ['mousePressed', 'mouseReleased']) await cdp.send('Input.dispatchMouseEvent', { type, x: cx, y: cy, button: 'left', clickCount: 1 });
  const prov = await waitFor(() => text('[aria-label="event provenance"]'), 6000);
  const trace = await api(`/api/compositions/${compo.id}/trace/${pick.seq}`);
  check('clicking a timeline event shows its provenance', prov && prov.includes(pick.source_start_s.toFixed(2)) && prov.includes(pick.source_end_s.toFixed(2)), (prov || 'no panel').replace(/\s+/g, ' ').slice(0, 220));
  check('provenance matches the API trace (source recording, specimen)', trace.source.exists && trace.specimen?.geometry_hash && trace.event.recording_id === pick.recording_id, trace.specimen?.geometry_hash);
  await shot('5-provenance');
  const specBtn = await clickText('button', 'Open its specimen');
  await sleep(1200);
  const onSpecimen = await ev(`!!document.querySelector('.specimen-head, canvas.signature')`);
  check('"Open its specimen" navigates to the source recording\'s specimen', specBtn && onSpecimen, '');
  await clickText('.views button', 'Orchestra');
  await sleep(300);

  // ---- 8. export
  const exp = await ev(`(async () => { const a = [...document.querySelectorAll('a.btn')].find(x => x.textContent.trim() === 'Export WAV'); const r = await fetch(a.href); const b = new Uint8Array(await r.arrayBuffer()); return { href: a.getAttribute('href'), download: a.hasAttribute('download'), status: r.status, ct: r.headers.get('content-type'), cd: r.headers.get('content-disposition'), bytes: b.length, riff: String.fromCharCode(...b.slice(0, 4)), wave: String.fromCharCode(...b.slice(8, 12)) }; })()`);
  check('Export WAV link downloads a valid RIFF/WAVE file', exp.status === 200 && exp.riff === 'RIFF' && exp.wave === 'WAVE' && exp.bytes > 1_000_000 && exp.cd?.includes('attachment') && exp.download, JSON.stringify(exp));
  const zip = await ev(`(async () => { const a = [...document.querySelectorAll('a.btn')].find(x => x.textContent.includes('stems')); const b = new Uint8Array(await (await fetch(a.href)).arrayBuffer()); return { bytes: b.length, magic: String.fromCharCode(...b.slice(0, 2)) }; })()`);
  check('Export bundle is a zip (master, stems, plan, provenance)', zip.magic === 'PK' && zip.bytes > 4_000_000, JSON.stringify(zip));

  // ---- 9. save, reload, reopen
  await ev(`(() => { const el = document.querySelector('input[aria-label="composition name"]'); Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, 'Browser test piece'); el.dispatchEvent(new Event('input', { bubbles: true })); })()`);
  await clickText('button', 'Save');
  await sleep(600);
  const savedLabel = await ev(`[...document.querySelectorAll('button')].map(b => b.textContent.trim()).find(t => t.includes('Saved'))`);
  const sha = (await api(`/api/compositions/${compo.id}`)).master_sha256;
  await cdp.send('Page.navigate', { url: BASE + '/' });
  await waitFor(() => ev("!!document.querySelector('.views')"), 20000);
  await clickText('.views button', 'Orchestra');
  await waitFor(() => ev(`document.querySelectorAll('.saved li').length > 0`), 10000);
  await ev(`document.querySelector('.saved').open = true`);
  const listed = await ev(`[...document.querySelectorAll('.saved li button')].map(b => b.textContent.trim())`);
  await ev(`[...document.querySelectorAll('.saved li button')].find(b => b.textContent.includes('Browser test piece')).click()`);
  const reopened = await waitFor(() => ev(`[...document.querySelectorAll('button')].some(b => b.textContent.trim() === 'Play')`), 60000);
  const reTracks = await ev(`document.querySelectorAll('.track').length`);
  const reSha = (await api(`/api/compositions/${compo.id}`)).master_sha256;
  check('Save → page reload → reopen from "Saved & recent"', savedLabel?.includes('Saved') && reopened && reTracks === 4 && sha === reSha, `listed: ${listed[0]} · tracks ${reTracks} · sha same ${sha === reSha}`);
  await clickText('button', 'Play');
  await sleep(1200);
  const rePlay = await seekValue();
  check('reopened composition plays', rePlay > 0.8, `playhead ${rePlay.toFixed(2)} s`);
  await clickText('button', 'Pause');

  // ---- 10. variation
  const before = await ev(`document.querySelector('.orchestra .caption').parentElement.innerText.match(/seed (\\d+)/)?.[1]`);
  await clickText('button', 'Another variation');
  await waitFor(async () => (await api('/api/compositions')).length >= 2 && (await api('/api/compositions')).every((c) => c.status === 'ready'), 90000);
  await sleep(1500);
  const list = await api('/api/compositions');
  const v = list.find((c) => c.parent_id);
  check('Another variation renders a different valid composition', !!v && v.status === 'ready' && v.seed !== full.seed, `parent seed ${full.seed} → ${v?.seed}`);

  // ---- 11. layout + health
  const mobile = async () => {
    await cdp.send('Emulation.setDeviceMetricsOverride', { width: 390, height: 844, deviceScaleFactor: 2, mobile: true });
    await sleep(500);
    const m = await ev(`({ sw: document.documentElement.scrollWidth, iw: window.innerWidth })`);
    await shot('6-orchestra-mobile');
    return m;
  };
  const mb = await mobile();
  check('phone width (390 px): no horizontal page scroll', mb.sw <= mb.iw + 1, JSON.stringify(mb));
  await cdp.send('Emulation.setDeviceMetricsOverride', { width: 1280, height: 900, deviceScaleFactor: 1, mobile: false });
  const acErrors = await ev('window.__ac.errors');
  const real = consoleErrors.filter((e) => !/favicon|Failed to load resource.*404/i.test(e));
  check('no uncaught errors or console errors during the whole run', real.length === 0 && acErrors.length === 0, [...real, ...acErrors].slice(0, 3).join(' | '));
} catch (e) {
  check('script completed', false, e.stack || e);
} finally {
  const failed = results.filter((r) => !r.ok);
  const report = { when: new Date().toISOString(), chrome: CHROME, passed: results.length - failed.length, failed: failed.length, results };
  writeFileSync(join(OUT, 'browser-report.json'), JSON.stringify(report, null, 1));
  console.log(JSON.stringify({ passed: report.passed, failed: report.failed, failures: failed }, null, 1));
  cleanup();
  process.exit(failed.length ? 1 : 0);
}
