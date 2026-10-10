# THE UNHEARD — mobile strategy

Ship the React PWA for the competition. After physical-phone validation, use Capacitor with a small Android recording/storage bridge if native lifecycle requirements justify it. Preserve FastAPI, the models and the music renderer as the connected laboratory.

| Option | Reuse / packaging | Recording and storage | Playback / permissions | Backend and testing |
| --- | --- | --- | --- | --- |
| React PWA (implemented) | Existing React/TypeScript; manifest, icons and shell worker | Explicit browser microphone capture; bounded IndexedDB originals; foreground retry. Screen-lock/background continuity is not promised | Native browser audio and Web Audio; secure-context permission prompt | Reachable authenticated HTTPS laboratory for DSP/CLAP/Gemma/composition. Test Chrome Android, Safari, storage quota, suspension and network loss |
| Capacitor + Android SDK (recommended next) | Reuse scenes, API client, queue logic, deterministic visuals; add Android project and plugins | Native recorder and app-private files replace browser adapters. Deliberate foreground-service recording is a separate feature | WebView/native playback bridge and Android runtime permissions; haptics/lifecycle bridges | Same backend remains necessary. Test emulator plus real phones, permission denial/revocation, interruption, process death, upgrades, battery and secure connection |
| Kotlin / Jetpack Compose | Rewrite all presentation and much of capture/playback; largest schedule and maintenance cost | Strong native audio/storage control; still needs explicit service/lifecycle design | Native media/session integration and permissions | Backend/models do not magically become mobile. New functional, accessibility, visual and synchronization tests required |
| Trusted Web Activity | Package a verified hosted PWA inside the browser; modest UI reuse effort | Browser microphone/storage semantics; no automatic native-recording advantage | Browser permissions and playback; origin trust requires Digital Asset Links | Requires a suitable verified HTTPS origin, which the laptop-only deployment does not currently supply. Test origin verification and browser compatibility |

Capacitor can wrap an existing web project and expose custom native plugins, while its Filesystem API supplies device file access. This supports replacing narrow adapters rather than rewriting the experience. See [Capacitor overview](https://capacitorjs.com/docs) and [Filesystem documentation](https://capacitorjs.com/docs/apis/filesystem).

Android microphone foreground services have permission and start restrictions; a web wrapper alone does not provide background recording. Design explicit user controls and ongoing visibility before adding this feature. See [Android foreground-service types](https://developer.android.com/develop/background-work/services/fgs/service-types). A TWA uses browser rendering and verified origin association rather than becoming a native recorder; see [Chrome's TWA overview](https://developer.chrome.com/docs/android/trusted-web-activity).

## Implemented adapter seams

* `platform/device.ts`: capture-device factory, permission capability, suspension subscription and disabled-by-default haptic boundary. The browser implementation delegates to the existing AudioWorklet/MediaRecorder recorder.
* `platform/captureStore.ts`: `CaptureStore` and durable local recording shape. A native implementation can store files and return compatible blobs/metadata to upload.
* `platform/uploadQueue.ts`: identity, acknowledgements, retry classification/backoff and optional browser Web Locks.
* `platform/playbackFocus.ts`, `platform/useAudioSource.ts`, `audio/orchestra.ts`: audible focus, authenticated originals and authoritative multi-stem playback.

Future native work should keep UUIDs and timestamps stable across upgrades, migrate existing local captures explicitly, store credentials through an appropriate native adapter, and test source/plan provenance unchanged. No APK, Capacitor package or Kotlin application was built in this milestone.

## Laptop-to-phone deployment

Serve the built shell and `/api` from the same trusted HTTPS origin, or use a controlled reverse proxy. The existing Vite `UNHEARD_BACKEND` configuration supports local development without embedding a LAN IP in the build. A phone cannot use its own `localhost` to reach the laptop. Follow the repository's existing `local-https.md` certificate procedure, configure the actual reachable host at deployment, and enable the backend bearer token when binding to the LAN. Do not open a public tunnel without separate authorization.

The shell can reopen offline after its initial successful cache installation. Recordings remain on the phone until explicitly uploaded. Inference and composition require the laboratory. Service-worker caches contain the application shell/icons/assets only, never API data or audio. Installation requires browser eligibility and HTTPS (localhost is a development exception); see [MDN's installation guide](https://developer.mozilla.org/en-US/docs/Web/Progressive_web_apps/Guides/Making_PWAs_installable). Real-device installation is still an outstanding manual check.
