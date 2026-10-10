# Android field test: owner's checklist

**Status: NOT PERFORMED.** No Android device was available to the engineering session. Nothing on this page is a
result; every "Result" cell below is blank on purpose. Fill them in as you go and keep the screenshots.

What *was* verified on the laptop (not a substitute for the phone):

* `unheard serve --ssl-certfile … --ssl-keyfile …` serves the API, the built app shell, the web manifest and the service
  worker over HTTPS on one origin (checked with a throwaway self-signed certificate on loopback).
* With `UNHEARD_API_TOKEN` set, `/api/recordings` returns 401 without the token and 200 with it; plain HTTP to the TLS port
  fails.
* Not verified here: mkcert (it is not installed on the development laptop), binding to the LAN address, the
  certificate chain on Android, anything on a phone.

## 0. Why this needs care

The phone microphone only works in a secure context, and a PWA only installs and works offline from a secure origin
with a service worker. The Vite dev server does not register the service worker, so **the PWA test uses the production
build** served by the backend itself. The phone is only a capture and display device: CLAP, Gemma and composition run on
the laptop. There is no offline AI, and no background or locked-screen recording is claimed.

Do not publish the laptop through a tunnel and do not use "ignore certificate errors" to get past a warning.

## 1. Setup (about 15 minutes)

On the laptop, in the repository root:

```bash
# one-time: install mkcert (Arch: sudo pacman -S mkcert nss), then
scripts/mkcert.sh                      # writes web/certs/dev.pem + dev-key.pem for localhost and your LAN IP

cd web && npm ci && npm run build      # production app shell + service worker -> web/dist
cd ../server
export UNHEARD_API_TOKEN="$(openssl rand -hex 16)"; echo "$UNHEARD_API_TOKEN"   # keep private
UNHEARD_DEVICE=cpu UNHEARD_TORCH_THREADS=2 UNHEARD_NARRATIVE_MODEL=gemma3:4b \
  uv run unheard serve --lan --port 8443 \
  --ssl-certfile ../web/certs/dev.pem --ssl-keyfile ../web/certs/dev-key.pem
```

Use a **home or personal-hotspot network you control**, not a public or shared Wi-Fi. `--lan` listens on all interfaces, so
if the laptop runs a firewall, allow port 8443 only from the phone (for example
`sudo ufw allow from <phone-ip> to any port 8443 proto tcp`) and remove the rule afterwards. Ollama stays on
`127.0.0.1`; the phone never talks to it.

Trust the local CA on the phone, **only the public certificate**:

1. Copy `$(mkcert -CAROOT)/rootCA.pem` to the phone (USB or a private file transfer). Never copy `rootCA-key.pem`.
2. Android: Settings → Security (or Security & privacy) → More security settings → Encryption & credentials → Install a
   certificate → CA certificate → choose the file. Menu names vary by device; note yours.
3. Chrome on Android trusts user-installed CAs. Other apps may not; use Chrome for this test.

Open `https://<laptop-lan-ip>:8443/?token=<token>` once in Chrome. The token is stored on the phone and sent as a bearer
token. Treat that URL as private and do not screenshot it with the token visible.

## 2. Record what you test on

| Field | Value |
|---|---|
| Phone model / Android version | |
| Chrome version (chrome://version) | |
| Laptop / network (home Wi-Fi, hotspot) | |
| App commit (`git rev-parse --short HEAD`) | |
| Date, weather, place type (no address needed) | |

## 3. Checklist

Mark each row **PASS / FAIL / SKIPPED** and write what you saw. Take a screenshot where the Evidence column says so.
A FAIL with notes is more useful than a quiet PASS.

| # | Step | Expected | Result | Notes / evidence |
|---|---|---|---|---|
| 1 | Open the HTTPS URL | Loads with a padlock, no certificate warning, Chamber scene shows | | screenshot |
| 2 | Install the PWA (Chrome menu → Install app / Add to Home screen) | Installs, opens standalone, icon present | | screenshot |
| 3 | Microphone permission | One prompt; after Allow the recorder shows a live level | | |
| 4 | Deny microphone once (then re-allow in site settings) | Clear `MIC_DENIED` message and a recovery path | | |
| 5 | Record 3 different real sounds outdoors, 8-15 s each (safe place, no people without consent, keep animals at distance) | Each recording stops explicitly, previews, and is saved locally | | screenshot of the saved list |
| 6 | Screen behaviour | Keep the screen awake while recording; note what happens if it locks | | |
| 7 | Go offline (airplane mode), record one more | Saved locally with an "offline/queued" state; no error | | |
| 8 | Close and reopen the app while still offline | The local recordings are still listed | | |
| 9 | Reconnect and submit | Queued items upload; the count of recordings on the laptop matches the phone (no duplicates) | | `curl` count below |
| 10 | Real CLAP inference | Each upload shows ranked hypotheses within a few seconds; scores, not percentages | | screenshot |
| 11 | Teach: confirm one, correct one, mark one unknown | Annotation saved; the banner says memory **updated** only when it was | | |
| 12 | Teach a sound *before* its analysis finishes (do it right after upload) | Banner says memory has not changed yet; after analysis the label still counts (check Memory shows the exemplar) | | |
| 13 | Second example of the same name | Prediction for it now cites your memory | | |
| 14 | Gemma: read ECHO-0's line and open its facts | Line appears (template first, Gemma may replace it); facts listed; no invented place or sound | | note: template or Gemma? |
| 15 | Gemma missions | At least one mission is offered and is safe and feasible where you are | | |
| 16 | Atlas | Your sounds appear and relate; selecting one works with touch (pan, zoom) | | screenshot |
| 17 | Compose from 3+ taught sounds | Renders; playback works from the phone speaker and headphones; seek, mute/solo work | | |
| 18 | Ending | Appears after the composition and persists after reload | | |
| 19 | Reload, close app, reopen | Progress and recordings persist | | |
| 20 | Readability in daylight | Text and controls usable outdoors; note brightness, touch targets | | |

To check for duplicates on the laptop (token and host as in setup):

```bash
curl -s -H "Authorization: Bearer $UNHEARD_API_TOKEN" --cacert "$(mkcert -CAROOT)/rootCA.pem" \
  https://<laptop-lan-ip>:8443/api/recordings | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d if isinstance(d,list) else d.get('items',d)))"
```

## 4. After the test

1. Stop the server (`Ctrl+C`) and remove the firewall rule.
2. On the phone remove the CA: Settings → Security → Encryption & credentials → User credentials → select it → Remove.
3. Rotate the token (a new `openssl rand -hex 16` next time). If anything leaked a screenshot with the token, rotate it now.
4. Keep the recordings private. Only use ones you made and had consent for in the public demo.

## 5. Summary to fill in

| Question | Answer |
|---|---|
| Did HTTPS and mic work without workarounds? | |
| Did install and offline capture work? | |
| Was sync lossless (no duplicates, nothing missing)? | |
| Were predictions plausible for real outdoor sounds? | |
| Was anything unsafe, confusing or unreadable? | |
| Blockers for the demo video | |

Until this table is filled in, the submission must not say the app was validated on a phone.
