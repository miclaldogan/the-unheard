# Local HTTPS for phone testing

`getUserMedia` (the microphone) is only available in a **secure context**. Browsers treat
`http://localhost` and `http://127.0.0.1` as secure, but **not** an ordinary LAN address such as
`http://192.168.1.20:5173`. So desktop testing works over plain HTTP, phone testing does not.

## Option A — mkcert (recommended; not yet exercised on a phone)

1. Install mkcert (`sudo pacman -S mkcert` on Arch, `brew install mkcert` on macOS).
2. Run `scripts/mkcert.sh`. It creates `web/certs/dev.pem` + `dev-key.pem` for
   `localhost`, `127.0.0.1` and your detected LAN IP, and installs the local CA on this machine.
3. Copy `$(mkcert -CAROOT)/rootCA.pem` to the phone and trust it
   (Android: Settings → Security → Encryption & credentials → Install a certificate → CA certificate;
   iOS: AirDrop/open the file, install the profile, then Settings → General → About →
   Certificate Trust Settings → enable).
4. Start the backend bound to the LAN with a pairing token (required, otherwise the server refuses):
   ```bash
   cd server && UNHEARD_API_TOKEN="$(openssl rand -hex 16)" uv run unheard serve --lan
   ```
5. Start Vite on the LAN: `cd web && UNHEARD_LAN=1 npm run dev`. Vite serves `https://<lan-ip>:5173`
   and proxies `/api` to the backend, so the phone only talks to one HTTPS origin.
6. On the phone open `https://<lan-ip>:5173/?token=<the token>` once; the token is stored in
   `localStorage` and sent as `Authorization: Bearer` on every API call.

## Production PWA over HTTPS (no extra proxy needed)

Vite development does not register the service worker. For installation/offline testing, build `web/dist` and let
the backend serve it with the same certificate, so the app and `/api` share one HTTPS origin:

```bash
cd web && npm run build
cd ../server
UNHEARD_API_TOKEN="$(openssl rand -hex 16)" uv run unheard serve --lan --port 8443 \
  --ssl-certfile ../web/certs/dev.pem --ssl-keyfile ../web/certs/dev-key.pem
```

`--ssl-certfile` and `--ssl-keyfile` must be given together. Without `--lan` the server stays on loopback; with `--lan`
the token is mandatory. Serving the shell, manifest, service worker and a token-protected API over HTTPS was verified with a
self-signed certificate on loopback; mkcert and an actual phone were not exercised in development. The full phone procedure and
a results checklist are in [`ANDROID-FIELD-TEST.md`](ANDROID-FIELD-TEST.md).
Do not bypass secure-context checks or publish the laptop through a tunnel for validation.

M5.5 verified actual laptop microphone capture and sandboxed desktop Chrome’s production PWA installation,
offline shell, local recording persistence, authenticated upload and playback. No physical Android/iPhone,
LAN HTTPS or outdoor test was performed. See `RELEASE-CHECKLIST.md` for those open gates.

Field now saves recordings in a bounded IndexedDB queue before upload. Offline capture is separate from
analysis: CLAP/Gemma and composition still need the connected laptop. Background or locked-screen recording
is not guaranteed. Keep the screen awake and stop/save explicitly before leaving the app.
