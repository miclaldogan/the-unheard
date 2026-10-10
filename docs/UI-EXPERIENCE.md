# THE UNHEARD — experience implementation

The entrance is a conversation with an incomplete instrument. The player brings sounds from outside, supplies interpretations, discovers connections, and hears the collection become music. All measured information continues to come from M1–M4 APIs; M5 owns progression and narrative facts.

## Scenes and hierarchy

`App` owns scene navigation, recording selection, archive refresh, foreground upload recovery, the M5 subscription, and orchestra selection/activity. It never derives game completion. `Chamber` introduces the journey and displays actual backend acts and milestones. `EchoCore` is an abstract identity instrument, explicitly labelled as an illustration rather than measured audio. Its presence maps backend narrative phase/moment to dormant, listening, uncertain, learning, remembering or composing. On an M4 server, its fallback uses actual ready recordings and memory exemplars without claiming a narrative act.

| Scene | Main action | Technical system preserved |
| --- | --- | --- |
| Chamber | Go outside / return to Hearing | M2 memory, M5 state/current |
| Field | Record, stop, save, upload later | Existing AudioWorklet WAV / MediaRecorder capture |
| Hearing | Hear a hypothesis; teach or correct | CLAP score semantics, annotation, neighbours, waveform, spectrogram |
| Specimen | Listen and examine a discovery | Deterministic M3 geometry, measured properties, provenance, PNG/SVG export |
| Atlas | Select, pan, zoom, filter and visit specimens | Existing stable graph positions, similarity/shared-label edges, unknown nodes, orchestra reactions |
| Orchestra | Choose sounds; compose and listen | M4/M4.6 Organic/Composed plans, Web Audio clock, mute/solo, event trace, source comparison, exports |

The Chamber supplies a short invitation and four actionable steps instead of a blocking tutorial. Returning recordings and remembered labels change that entrance automatically. Zero recordings produce purposeful empty states. No fake recordings, learning scores or progression fixtures exist in production.

## Recording and connection states

The existing recording reducer remains authoritative for capture UI: idle → permission request → recording → recorded → upload → processing → done; errors preserve the preview. Clearing an upload error returns to `recorded`, making retry actionable. Permission denial never enters recording.

Stopping persists the original blob in IndexedDB before claiming it is saved. Each capture receives a UUID, original capture timestamp, method metadata and optional field note. A field note is metadata, not an authoritative annotation: the player teaches in Hearing after upload. Local storage failure provides an explicit error and original-download escape hatch; an in-memory preview is never described as durable.

Local, upload-pending, synchronized, DSP-ready and model-inference states are distinct. A synchronized local item has a server ID; that alone does not mean AI inference finished. DSP completion is polled separately, and Hearing exposes inference status. A failed connection never prevents microphone capture.

The queue retains local originals after upload. It is bounded to 64 MiB and 100 recordings, with a transaction-wide quota check. Nothing is automatically evicted. Browser quota errors remain visible. Download or delete local copies to make room. Clearing browser storage or uninstalling can remove local originals; download important recordings.

Upload requires a player action. After that action, foreground recovery runs on app reopen, connectivity return and every 30 seconds while visible. Transient failures use bounded backoff, then pause after five attempts; permanent rejection requires manual attention. Acknowledged server IDs are reused. Same-tab requests coalesce; Web Locks coordinate supported browsers. Lost acknowledgements recover through the existing backend canonical-PCM duplicate response. Background Sync is not required. Servers remain responsible for deduplication where Web Locks are absent.

Microphone-active navigation is disabled. Moving the document into the background attempts to stop and preserve the current recording; the UI still warns that browsers may suspend before this finishes. No hidden, forced-background or screen-lock recording is promised.

## Narrative and audio integrity

`api/narrative.ts` matches committed backend contract `923b4aa` (`m5.1`). `useNarrative` loads state/current/missions and polls pending wording every 1.5 seconds, otherwise every 8 seconds while visible. Missing M5 endpoints produce an unavailable state; failures show a fallback invitation. Unsupported contract versions fail explicitly. Template narration is valid backend narration, not frontend fabrication. Provenance and cited facts are accessible in `NarrativeVoice`; imagination is italic and explicitly labelled. Plain React text rendering prevents labels/notes from becoming HTML. Mission activation is a backend POST; completion is never calculated in JavaScript.

Once opened, Orchestra stays mounted across compatible scene changes. Atlas follows the same activity reference and audio-event clock. Shared playback focus pauses competing originals, previews and stems when a new source is deliberately started. Entering Field pauses listening before capture. Master volume preserves mute/solo choices. A suspended Web Audio clock cannot be ended prematurely by a wall-clock timeout. Protected originals and exports use bearer headers and revocable object URLs rather than tokenized audio URLs.

## Accessibility and responsiveness

Visible focus, a skip link, labelled controls, semantic buttons/forms and textual status accompany color. Recording buttons are large; secondary buttons have at least 44 px targets (48 px on portrait mobile). Atlas selection and zoom work through semantic controls; arrow keys pan its focused canvas. Native audio controls provide accessible playback and volume. `prefers-reduced-motion` removes presentation animations; existing M3 reduced-motion behavior is retained.

Layouts change at 1000 px and 700 px, alongside the retained specialist M3/M4 breakpoints. Mobile Field uses compact headings, safe-area padding, a prominent record control and a separate notebook below. Landscape Field can use two columns with a smaller capture instrument. Existing laboratory workflows remain reachable on the phone.

## Current limits

No offline AI inference, GPS, cloud backend, background recording, native application or private-audio service-worker cache is implemented. Recording/queue adapters are replaceable; native permission and lifecycle testing is still required. Scenes are not deep-linked. M5 timeline, model-settings and per-composition commentary endpoints remain available for a later dedicated narrative-history UI. The archive still loads the stable API's first 100 records; large-library pagination/virtualization is future work.
