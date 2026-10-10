# Browser and mobile human review

Use non-sensitive recordings and a disposable backend data directory. Build the frontend, serve `web/dist` through the real backend, and use a trusted HTTPS origin on phones. The backend must have M5 installed for progression checks. Test once with CLAP/Gemma enabled and once with them disabled; template narration is an expected working mode.

## Walkthrough

1. Fresh browser, empty backend: meet ECHO-0, identify the first action within five seconds, and enter Field without reading documentation. Verify purposeful empty states in Hearing, Atlas and Orchestra.
2. Returning library: names and actual act/milestone state appear without replaying a tutorial. Delete/correct a taught recording and verify the backend-derived state changes after refresh/poll.
3. Portrait phone outdoors: Record and Stop are obvious, finger-sized and legible. Record 3–30 seconds. Confirm the timer/live indicator, stop control and input meter; navigation must be disabled while the microphone is active.
4. Deny/revoke microphone permission, remove the input device, and use an insecure origin. Verify specific errors and recovery without recording or a contradictory live indicator.
5. Switch apps and lock the phone during capture. Check actual browser suspension behavior, microphone indicator and attempted stop/save. Do not assume continuation. Repeat at the maximum duration.
6. Disconnect the laptop before capture. Stop; confirm a local saved message and notebook entry. Reload offline after installing the shell: the original must survive. Preview/download the original. A local save failure must never claim durability.
7. Request upload while disconnected; restore connectivity with the app visible. Verify automatic recovery of requested captures, preserved capture time and a single backend recording. Retry manually. Repeat a lost-response/duplicate acknowledgement case. Never auto-upload a capture the player did not request.
8. Simulate quota/full storage. Download or delete a local copy; save again. Delete a pending item, reopen, and ensure it does not reappear. Test two tabs on browsers with/without Web Locks.
9. Hearing: compare CLAP hypotheses and score explanations, inspect actual waveform/spectrogram, teach, reject, mark unknown, add a new name, and correct a previous annotation. The formation acknowledgement appears only after a successful POST; failures retain editable input.
10. Specimen: play the original, seek/adjust volume, inspect measured properties and similar memories, and export PNG/SVG. Annotation changes color/semantic state without replacing measured geometry. Test protected playback with a backend token.
11. Atlas: select by touch and by dropdown/keyboard, pan, zoom, reset, filter uncertain/name, navigate to a specimen, choose orchestra sources. Playback reactions must follow events and muted stems must remain dark.
12. Orchestra: create Organic and Composed arrangements; play/pause/seek, change master volume, mute/solo, inspect an event and compare original/layer/full. Move to Atlas and back without restarting the composition. Starting an original must pause other audio. Export WAV and the stems/plan bundle; repeat authenticated exports.
13. Teach three actual recordings and create a ready composition from those recordings. Verify M5 acts/ending from backend responses. Accept a field mission; verify objective, evidence and backend-evaluated completion. Verify grounded versus imagination provenance and pending/template fallback.
14. Turn on reduced motion. Traverse every view with keyboard only; verify focus, skip link, semantic controls and readable errors with a screen reader. Check zoom to 200%, long labels, mobile portrait/landscape and safe areas.
15. Install the PWA from a normal browser profile, reopen offline, update it, and confirm an update does not interrupt active capture. Inspect caches: no `/api` or audio entries. Clear browser storage deliberately and confirm local-loss expectations.

## Artistic review

Judge identity, narrative, readability, technical integrity and emotional impact against `UI-ART-DIRECTION.md`. In particular, ask a new player to record, teach and compose without coaching. Screenshots and automated tests cannot certify emotional response, sunlight contrast, physical microphone quality, Safari behavior or actual phone installation.

## Automated evidence

The committed `ui-review/` screenshots and JSON reports record sandboxed Chrome runs with a simulated microphone and real backend DSP/annotations/compositions. The frontend unit suite also exercises permission denial, unavailable backend, upload failures, duplicate recovery and narrative fallback. The browser scripts under `web/scripts/` are reproducible test tooling, with paths configured through environment variables. No physical-device pass is recorded.
