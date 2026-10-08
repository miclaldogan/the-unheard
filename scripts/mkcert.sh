#!/usr/bin/env bash
# Create a locally-trusted TLS certificate for phone testing on the LAN.
# Requires mkcert (https://github.com/FiloSottile/mkcert). Arch: `sudo pacman -S mkcert`.
# Produces web/certs/dev.pem and web/certs/dev-key.pem (gitignored); Vite picks them up automatically.
set -euo pipefail
cd "$(dirname "$0")/.."
if ! command -v mkcert >/dev/null 2>&1; then
  echo "mkcert is not installed. See docs/local-https.md for alternatives." >&2
  exit 1
fi
LAN_IP="${LAN_IP:-$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") print $(i+1)}' | head -n1)}"
mkdir -p web/certs
mkcert -install
mkcert -cert-file web/certs/dev.pem -key-file web/certs/dev-key.pem localhost 127.0.0.1 ::1 ${LAN_IP:+"$LAN_IP"}
echo
echo "Certificate written to web/certs/. LAN IP: ${LAN_IP:-<none detected>}"
echo "Install the CA on your phone: copy \"$(mkcert -CAROOT)/rootCA.pem\" to the phone and trust it"
echo "(Android: Settings → Security → Install certificate → CA; iOS: open the file, then Settings → General → About → Certificate Trust)."
echo "Then run: UNHEARD_LAN=1 npm run dev   and open https://${LAN_IP:-<lan-ip>}:5173 on the phone."
