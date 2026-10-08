# 10 — Privacy and Security

## Principles → mechanisms
| Requirement | Mechanism |
|---|---|
| Raw audio stays local | Server on user's machine; no third-party calls except optional model download (explicit script) and optional Ollama on localhost |
| No hidden recording | Recording only inside the Recording state, started by a tap; visible timer + browser mic indicator; max 30 s hard stop |
| Clear permissions | Pre-explainer; handles denial; no mic access on page load |
| No precise location | Core gameplay has none. Optional `place_note` free text. Coarse geo (rounded to 2 decimals ≈ 1 km) only if toggled on, stored locally |
| Remote inference visibility | `/api/health` reports `inference: local`. Any remote backend must set `inference: remote` and the UI shows a persistent banner. MVP ships none |
| Deletion & export | doc 08; export is a user action producing a local zip |
| No transcripts | No ASR anywhere in the pipeline. Speech is only a model label ("speech detected") and triggers a hint: *"People may be audible. Consider deleting this clip."* |
| Duration limits | 3–30 s |
| Exports | Explicit; stems/masters contain the user's audio — dialog says so |

## Threat model (local server)
- LAN exposure: server binds to the LAN only when `--lan` is passed; per-install **pairing token** (random 128-bit, shown as QR in Lab) required in `Authorization: Bearer` for all write endpoints and audio reads. Without it anyone on the Wi-Fi could read recordings. Token is not a substitute for network trust; documented.
- TLS: mkcert-issued cert for LAN IP; the CA must be installed on the phone (documented, optional alternative: tunnel — then traffic transits a relay and the UI must say so).
- Upload: size cap, ffmpeg run with `-nostdin` and a timeout, input never executed, filenames never used for paths (content hash names).
- Plan/LLM output is data validated by JSON Schema; no code from LLM is executed. Paths in plans are ids, not paths.
- Dependencies pinned; model files checked against SHA-256 recorded in `model_version`.
- Do not claim data is unrecoverable after delete: SQLite/file deletions on SSDs are not forensically secure (we state "removed from the app; use full-disk encryption for stronger guarantees"). `PRAGMA secure_delete=ON` and `VACUUM` after deletes are used best-effort.

## Safety / ethics in the experience
Quest copy includes: stay on public paths, keep distance from wildlife, avoid recording identifiable people without consent, no night/remote solo prompts. Never suggest a location. Label quality caveat: classification of sensitive content (speech, emotions) is not performed or claimed.

## Limitations to document
Models misclassify; dataset bias toward AudioSet (YouTube) sound sources [M]; microphone variance; the memory is personal and may not generalize across devices.
