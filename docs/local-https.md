# Local HTTPS for phone testing

`getUserMedia` (the microphone) is only available in a **secure context**. Browsers treat
`http://localhost` and `http://127.0.0.1` as secure, but **not** an ordinary LAN address such as
`http://192.168.1.20:5173`. So desktop testing works over plain HTTP, phone testing does not.

## Option A — mkcert (recommended, verified approach, not yet exercised on a phone in M1)

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

## Production PWA and current validation

Vite development does not register the service worker. For installation/offline testing, build `web/dist` and
serve it with FastAPI behind a trusted local HTTPS reverse proxy. Keep `/api` on that same origin and require
a bearer token. The backend can stay on loopback behind the proxy; it does not need a public address.
Do not bypass secure-context checks or publish the laptop through a tunnel for validation.

M5.5 verified actual laptop microphone capture and sandboxed desktop Chrome’s production PWA installation,
offline shell, local recording persistence, authenticated upload and playback. No physical Android/iPhone,
LAN HTTPS or outdoor test was performed. See `RELEASE-CHECKLIST.md` for those open gates.

Field now saves recordings in a bounded IndexedDB queue before upload. Offline capture is separate from
analysis: CLAP/Gemma and composition still need the connected laptop. Background or locked-screen recording
is not guaranteed. Keep the screen awake and stop/save explicitly before leaving the app.
