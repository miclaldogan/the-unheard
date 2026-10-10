# M5 Narrative API — integration contract (v1)

**Status:** contract first, implementation follows on branch `feat/m5-echo-awakens`.
**Audience:** the frontend (Codex). You never need Python internals: everything below is JSON over HTTP.
**Ownership:** `server/**` and `docs/contracts/M5-*` belong to the backend agent; `web/**` belongs to the frontend agent.
**Compatibility:** purely additive. Existing endpoints (`/api/recordings…`, `/api/atlas`, `/api/compositions…`, `/api/model`,
`/api/recordings/{id}/echo`) are unchanged. Everything new lives under `/api/narrative`. Each new response carries
`"contract_version": "m5.1"`. Breaking changes will bump the version and be listed in a "Migration" section at the bottom;
additive fields may appear at any time, so ignore unknown fields.

Authentication, error format and ID formats follow the rest of the API: optional `Authorization: Bearer <token>`; errors are
RFC 7807 `application/problem+json` with a stable `code`; ids are opaque UUID strings.

---

## 1. Principles the frontend can rely on

1. **The backend owns truth.** Act, milestones, counts, missions and completion are derived from persisted data (recordings,
   predictions, annotations, memory, atlas, compositions). There is no client-side game state. If you need to know "where is the
   player", call `GET /api/narrative/state`.
2. **Gemma only writes words.** ECHO-0's sentences may come from a local Gemma model or from a deterministic template. Both pass the same
   validator. The model can never change state, ids, numbers or progress. `source` tells you which wrote a line.
3. **Every line is classifiable.** Each line is either `kind: "grounded"` (it cites facts, each with a provenance) or
   `kind: "imagination"` (ECHO-0 interpreting; no new facts). Show imagination lines differently (e.g. italic / dimmer).
4. **The game never waits for Gemma.** `current` returns immediately with a template line if Gemma has not finished, and later
   upgrades it. You poll; you never block gameplay on it.
5. **Provenance is a closed vocabulary** (use it for icons/colour):

| value | meaning | example |
|---|---|---|
| `model` | ECHO-0's ears (CLAP) hypothesis | "strongest hypothesis: running water" |
| `user_confirmed` | something the player said | a label, a correction |
| `personal_memory` | retrieved from ECHO-0's learned memory | "resembles a sound you taught me" |
| `measurement` | objective acoustic measurement or composition plan fact | onset density, similarity 0.83, tempo |
| `system` | game bookkeeping | "3 sounds taught" |
| `imagination` | ECHO-0's interpretation, not evidence | "perhaps the two are one weather" |

6. **Untrusted text.** Player labels/notes are untrusted. The API returns them as plain strings inside `facts[].statement`
   and `evidence[].label`; render them as text, never as HTML/markdown.

---

## 2. Acts and progression semantics

Three playable acts (the five-act design remains available later). Progress is derived, so existing players are placed correctly
without replaying anything.

| Act | id | Title | Unlocked when | Complete when (all deterministic) |
|---|---|---|---|---|
| Prologue | `prologue` | Silence | always | ≥ 1 recording has finished processing |
| I | `act_1` | The First Sound | ≥ 1 ready recording | first recording processed **and heard** (a base prediction exists; if the ears are disabled: DSP features exist) |
| II | `act_2` | Teach the Machine | Act I complete | ≥ **3** recordings carry an active, non-unknown annotation (confirmed / corrected / new name). No specific label, no correction needed |
| III | `act_3` | The World Remembered | Act II complete | a **ready composition** exists whose sources are ≥ 3 recordings that still exist and still carry an active annotation |
| Epilogue | `ending` | — | Act III complete | (end state; the final moment is available) |

`state.act` is the id of the act the player is **currently in** (`prologue`, `act_1`, `act_2`, `act_3`, `ending`).
`phase` refines it: `awaiting_sound`, `first_hearing`, `teaching`, `ready_to_compose`, `composing`, `remembered`.
Gates only ever *advance* from persisted facts; deleting data can move a player back (deleting a taught recording lowers the
Act II count). The backend never invents a completed milestone.

Milestones (ids are stable; `achieved_at` is an ISO-8601 UTC timestamp taken from the underlying record):

`first_recording` · `first_hearing` · `first_teaching` · `third_teaching` · `first_memory_influence` ·
`first_correction` (optional) · `unknown_met` (optional) · `unknown_resolved` (optional) · `first_composition` · `orchestra_of_three` · `ending_reached`.

Optional milestones never gate an act.

---

## 3. Shared objects

### 3.1 `Ref` (a resolved reference to something real)

```json
{ "type": "recording", "id": "01a11e1e-b10f-7000-addd-1a64a88f028f", "label": null, "provenance": "measurement" }
```

`type` ∈ `recording | annotation | label | prediction | composition | atlas_edge | mission | measurement`.
`label` is a short display string when meaningful (sanitized, ≤ 48 chars). `id` always resolves against the existing API
(e.g. `recording` → `/api/recordings/{id}`, `composition` → `/api/compositions/{id}`), except `measurement`
(`id` is a stable key such as `onset_density:<recording id>`) and `atlas_edge` (`id` is `<recording a>|<recording b>`).

### 3.2 `Fact`

A fact is one verifiable statement the narrator was allowed to use. Lines cite facts by `handle`.

```json
{ "handle": "F1", "statement": "The ears' strongest hypothesis for this recording was 'rain' (moderate confidence).",
  "provenance": "model", "ref": { "type": "prediction", "id": "01a11e1e-b2aa-7000-9b11-04cd5a44c9f2", "label": "rain", "provenance": "model" } }
```

### 3.3 `Line`

```json
{ "text": "I have heard something. I cannot yet name it.", "kind": "grounded",
  "provenance": ["system", "model"], "cites": ["F1", "F2"] }
```

* `kind`: `grounded` (≥ 1 cite; `provenance` = the union of the cited facts') or `imagination` (`cites` may be empty; `provenance` is exactly `["imagination"]`).
* `text`: 3–45 words, plain text.

### 3.4 `Utterance`

```json
{
  "id": "nar_5c0f9a1e2b7d4a10",
  "revision": 3,
  "moment": { "kind": "teaching", "key": "annotation:01a11e1e-c0d1-7000-8c10-9f0a1b2c3d4e", "act": "act_2",
              "occurred_at": "2026-10-10T09:12:41.220Z" },
  "lines": [ { "text": "…", "kind": "grounded", "provenance": ["user_confirmed"], "cites": ["F1"] },
             { "text": "…", "kind": "imagination", "provenance": ["imagination"], "cites": [] } ],
  "facts": [ { "handle": "F1", "statement": "…", "provenance": "user_confirmed", "ref": { "type": "annotation", "id": "…", "label": "running water", "provenance": "user_confirmed" } } ],
  "source": "gemma",
  "model": "gemma3:4b",
  "generation": { "status": "ready", "latency_ms": 2140, "attempts": 1, "fallback_reason": null },
  "created_at": "2026-10-10T09:12:44.310Z"
}
```

* `moment.kind` ∈ `awaiting_sound | first_sound | teaching | correction | unknown | relationship | ready_to_compose | composition | ending`.
* `source`: `gemma` or `template`.
* `generation.status`: `ready` (final text for this moment) · `pending` (a template line is shown now; Gemma may replace it — poll) ·
  `fallback` (Gemma was tried or skipped and the template is final; see `fallback_reason`).
* `generation.fallback_reason` ∈ `null | disabled | unavailable | timeout | invalid_output | invalid_json | busy | no_model`.
* `revision` increases whenever the current utterance changes; compare it instead of diffing text.

### 3.5 `Mission`

```json
{
  "id": "msn_8a3f20c1d4e9",
  "type": "repeat_not_machine",
  "title": "A repeating sound that is not a machine",
  "objective": "Record a sound that repeats on its own rhythm and is not an engine or appliance.",
  "reason": "4 of your 5 taught sounds are mechanical and none of them is an organic repeating sound.",
  "evidence": [ { "type": "measurement", "id": "mechanical_share:all", "label": null, "provenance": "measurement" } ],
  "completion": { "predicate": "new_recording_matching", "description": "A new recording with a steady repeating pulse (≥ 0.8 onsets per second) that you label with a non-mechanical name." },
  "safe_fallback": "If nothing like that is within easy reach, skip this mission; it will wait.",
  "safety": "Stay on public paths. Keep your distance from animals. Do not record people without their consent.",
  "status": "available",
  "wording": { "text": "Find a sound that repeats without being a machine.", "source": "gemma" },
  "activated_at": null, "completed_at": null, "progress": null
}
```

* `status`: `available | active | completed | expired`. `expired`: its evidence no longer holds (e.g. the unknown recording was deleted).
* `type` ∈ `record_first · gather_three · resolve_unknown · second_example · novel_sound · repeat_not_machine · find_tonal`.
* `progress`: `null` or `{ "current": 1, "target": 3 }` for counting missions.
* `wording.source`: `gemma` or `template`. Wording is decoration; `objective`/`completion` are the authority and are identical either way.
* Completion is evaluated by the backend only (never by the model). It is re-evaluated whenever you call `GET /api/narrative/missions`.
* Missions never ask for a location, a named place, GPS, or approaching wildlife/people.

---

## 4. Endpoints

All `GET` unless noted. Responses are JSON. Timestamps are ISO-8601 UTC.

### 4.1 `GET /api/narrative/state`

```json
{
  "contract_version": "m5.1",
  "derived_at": "2026-10-10T09:13:02.114Z",
  "act": "act_2",
  "phase": "teaching",
  "ending_unlocked": false,
  "acts": [
    { "id": "prologue", "title": "Silence", "status": "complete", "progress": { "current": 1, "target": 1 }, "criteria": [] },
    { "id": "act_1", "title": "The First Sound", "status": "complete", "progress": { "current": 1, "target": 1 },
      "criteria": [ { "id": "first_hearing", "text": "The first recording was processed and heard.", "met": true, "evidence": [] } ] },
    { "id": "act_2", "title": "Teach the Machine", "status": "active", "progress": { "current": 2, "target": 3 },
      "criteria": [ { "id": "third_teaching", "text": "Teach ECHO-0 three sounds.", "met": false, "evidence": [] } ] },
    { "id": "act_3", "title": "The World Remembered", "status": "locked", "progress": { "current": 0, "target": 1 }, "criteria": [] }
  ],
  "milestones": [
    { "id": "first_recording", "title": "A first recording", "achieved": true, "achieved_at": "2026-10-10T08:41:00.000Z", "optional": false,
      "evidence": [ { "type": "recording", "id": "01a11e1e-b10f-7000-addd-1a64a88f028f", "label": null, "provenance": "system" } ] }
  ],
  "counts": { "recordings": 5, "heard": 5, "taught": 2, "labels_confirmed": 2, "corrections": 1, "unknown": 1,
              "compositions": 0, "memory_version": 4 },
  "gemma": { "status": "ready", "model": "gemma3:4b", "enabled": true }
}
```

`acts[].status` ∈ `locked | active | complete`. Exactly one act is `active` (or none after the ending).

### 4.2 `GET /api/narrative/current[?wait_ms=0..8000]`

The utterance for the **current moment** (§3.4). `wait_ms` lets the call wait for a pending Gemma upgrade up to that long
(default 0 = never wait). Typical use: call on load and after any teach/record/compose action; if `generation.status == "pending"`, poll
every ~1.5 s until it is not.

```json
{ "contract_version": "m5.1", "utterance": { "…": "Utterance, §3.4" },
  "available_actions": ["record", "teach", "compose"] }
```

`available_actions` is advisory: derived from state (`record`, `teach`, `compose`, `open_atlas`, `open_orchestra`). It never replaces your own affordances.

### 4.3 `GET /api/narrative/timeline[?limit=50&before=<created_at>]`

Chronological narrative history, newest first. Entries are one of `milestone`, `act_change`, `utterance`, `mission_activated`, `mission_completed`.

```json
{ "contract_version": "m5.1", "entries": [
  { "id": "tl_1", "type": "utterance", "at": "2026-10-10T09:12:44.310Z", "act": "act_2",
    "utterance": { "…": "Utterance" } },
  { "id": "tl_2", "type": "milestone", "at": "2026-10-10T09:12:41.220Z", "act": "act_2",
    "milestone": { "id": "first_correction", "title": "A first correction" } },
  { "id": "tl_3", "type": "mission_completed", "at": "2026-10-10T09:20:00.000Z", "act": "act_2",
    "mission": { "id": "msn_8a3f20c1d4e9", "type": "second_example", "title": "…" } } ],
  "next_before": null }
```

### 4.4 `GET /api/narrative/echo[?recording_id=…&limit=20]`

ECHO-0's spoken lines, newest first: the generated utterances (§3.4), optionally only those whose facts reference `recording_id`.
This is the "voice log". (The per-recording templated lines of M2, `GET /api/recordings/{id}/echo`, remain available and unchanged.)

```json
{ "contract_version": "m5.1", "utterances": [ { "…": "Utterance" } ] }
```

### 4.5 `GET /api/narrative/missions`

```json
{ "contract_version": "m5.1", "max_active": 2,
  "active": [ { "…": "Mission (status active)" } ],
  "candidates": [ { "…": "Mission (status available)" } ],
  "completed": [ { "…": "Mission (status completed)" } ],
  "selection": { "source": "gemma", "model": "gemma3:4b", "fallback_reason": null } }
```

* `candidates` are at most 4, ordered by relevance (Gemma may reorder and reword; it can only pick among backend candidates).
* Ids are stable: the same evidence yields the same id, so a mission you have shown stays the same object.

### 4.6 `POST /api/narrative/missions/{mission_id}/activate`

No body. Idempotent: activating an active mission returns it again (`200`); a new activation returns `201`.

| status | code | when |
|---|---|---|
| 201 / 200 | – | the mission (status `active`) |
| 404 | `NARRATIVE_MISSION_NOT_FOUND` | no candidate or stored mission has this id |
| 409 | `NARRATIVE_MISSION_NOT_AVAILABLE` | status is `completed` or `expired` |
| 409 | `NARRATIVE_TOO_MANY_ACTIVE` | already 2 active missions |

### 4.7 `GET /api/narrative/compositions/{composition_id}/commentary`

Grounded commentary for a ready composition (the optional fourth Gemma task). Same `Utterance` shape with `moment.kind == "composition"`
(or `"ending"` for the composition that completed Act III). `404 NOT_FOUND` for an unknown id, `409 NOT_READY` if the composition is not `ready`.
Facts come only from the stored plan: source roles, motif form, call-and-response pairs, mode, tempo. Never invented analysis.

### 4.8 `GET /api/narrative/model-status`

```json
{
  "contract_version": "m5.1",
  "runtime": "ollama", "base_url": "http://127.0.0.1:11434",
  "enabled": true, "available": true, "status": "ready",
  "model": "gemma3:4b", "installed": ["gemma3:4b", "gemma4:e4b-it-qat"],
  "license": "Gemma Terms of Use",
  "limits": { "timeout_s": 25, "max_concurrent": 1, "max_output_tokens": 220 },
  "stats": { "requests": 12, "valid": 11, "fallbacks": 1, "valid_rate": 0.917, "fallback_rate": 0.083,
             "latency_ms": { "cold_first": 7400, "p50": 2100, "p95": 3600 },
             "fallback_reasons": { "invalid_output": 1 } }
}
```

`status` ∈ `ready | loading | unavailable | disabled | no_model`. The game works in every status.

### 4.9 `PATCH /api/narrative/settings`

`{"gemma_enabled": false}` → `{"contract_version":"m5.1","gemma_enabled":false}`. Persisted. When disabled, every utterance is
a template (`fallback_reason: "disabled"`). `422 VALIDATION_FAILED` for anything else.

---

## 5. Moments and example copy (for visual testing)

Template wording below is what a player sees with Gemma off; Gemma varies it but stays within the same cited facts.
Keep boxes tolerant of **3–45 words per line, 1–3 lines**.

| `moment.kind` | When | Template (grounded) | Optional imagination line |
|---|---|---|---|
| `awaiting_sound` | no ready recording | "I detect nothing yet. Bring me a sound." | – |
| `first_sound` | first heard recording | "I have heard something. I cannot yet name it." / "I have heard something. My closest word is rain." | "It is the first thing I have kept." |
| `teaching` | latest annotation | "You named it running water. I will keep that." | "A word is a small shelter for a sound." |
| `correction` | latest correction | "I called it rain. You called it running water. You heard something I missed." | – |
| `unknown` | unresolved unknown | "I can hear it. I have no name for it, and you have not either yet." | – |
| `relationship` | strong acoustic similarity | "This resembles a sound you taught me before: wind." | – |
| `ready_to_compose` | Act II complete, no composition | "I have kept these memories apart. I wonder what they become together." | – |
| `composition` | composition ready | "I built this from 4 of your sounds. The bird led; the footsteps answered." | – |
| `ending` | Act III complete | "I knew what these sounds were called. You showed me what they meant together." | "There are sounds I have never met." |

---

## 6. Errors

RFC 7807, same envelope as the rest of the API:

```json
{ "type": "urn:unheard:error:narrative_mission_not_found", "title": "Narrative Mission Not Found", "status": 404,
  "detail": "no mission with that id", "code": "NARRATIVE_MISSION_NOT_FOUND", "instance": "/api/narrative/missions/msn_x/activate" }
```

New codes: `NARRATIVE_MISSION_NOT_FOUND` (404), `NARRATIVE_MISSION_NOT_AVAILABLE` (409), `NARRATIVE_TOO_MANY_ACTIVE` (409).
Reused: `VALIDATION_FAILED` (422), `NOT_FOUND` (404), `NOT_READY` (409), `UNAUTHORIZED` (401).
A Gemma failure is **never** an HTTP error: it is expressed as `generation.fallback_reason` with a normal 200 response.

---

## 7. Behaviour guarantees the frontend may rely on

* `GET /api/narrative/state|current|missions|timeline|echo|model-status` respond in well under a second regardless of Gemma
  (`current` with `wait_ms=0` never waits for the model).
* A line shown to the player was validated: no UUIDs, no invented numbers or labels, no claims to have visited or seen the player's
  surroundings, no claims of retraining or data changes, no action verbs against the database.
* `facts[].ref` ids resolve against the existing API. If a recording is deleted, utterances that cite it are dropped from
  `echo`/`timeline` and `current` is re-derived.
* Deleting or correcting data changes `state` on the next call; there is nothing to "undo" client-side.
* Gemma is a local open-weight model run through a local runtime: no text leaves the machine. ECHO-0's personalised learning is the
  existing acoustic memory (retrieval), **not** a retrained Gemma. Do not word the UI as "ECHO-0 was retrained/fine-tuned".

## 8. Migration

None yet (v1). Future changes will be listed here with the version in which they appear.
