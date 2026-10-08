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

## Option B — Chrome flag (quick, Android only, not for demos)

`chrome://flags/#unsafely-treat-insecure-origin-as-secure` → add `http://<lan-ip>:5173`. Works on
Android Chrome; iOS Safari has no equivalent.

## Option C — temporary tunnel

A quick tunnel (e.g. `cloudflared tunnel --url http://localhost:5173`) gives a public HTTPS URL.
Traffic then transits a third-party relay; **the architecture requires the UI to label this**
(doc 02). Not wired up in M1. Always set `UNHEARD_API_TOKEN` before exposing anything.

## What is and is not verified in M1

- Verified: desktop capture on `http://localhost:5173` with the Vite proxy (Chrome / Firefox on Linux).
- Not verified: an actual phone over LAN HTTPS. `scripts/mkcert.sh` and the Vite config are in
  place but no physical device test was run in this milestone. Do not claim otherwise.
- Not implemented: offline capture queue (IndexedDB) and service worker. The manifest makes the
  app installable, but an installed PWA still needs the server reachable to upload. This is
  the "Offline queue → simple retry" cut from doc 12.
