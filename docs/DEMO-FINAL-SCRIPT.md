# Final demo script (about 110 seconds)

Supersedes the timing in `DEMO-RECORDING-PLAN.md`; keep that file's capture checklist. Everything on screen must be
real: real recordings, real predictions, a real correction, a real composition, a real narrator line. If a shot cannot be
captured truthfully, cut it and shorten the video. A clear 80-second video beats a cinematic 120-second one.

**Status: SCRIPT ONLY. Nothing has been filmed or recorded.** The recording session requires you (outdoors, phone, voice).

## Ground rules

1. **Your own sounds only.** Do not use ESC-50 clips or their derived compositions (CC BY-NC, per-clip licences unchecked).
   Record three sounds yourself with consent, in safe public places, not people's voices. Candidates that work for the
   theme: wind in leaves, a street crossing, water, birds, a bicycle bell, your own footsteps on gravel.
2. **No fake interactions.** No scripted predictions, no staged "AI" replies. If CLAP gets the first sound wrong, show that.
3. **Disclose cuts.** Processing waits may be shortened with an on-screen "shortened" tag. Never show an instant result that was not.
4. **Phone claims follow evidence.** Only show the phone UI as "recorded on a phone" if the Android test in
   `ANDROID-FIELD-TEST.md` is done. Otherwise film the laptop and the responsive layout, labelled as such.
5. **Hide secrets.** No pairing token in the URL bar, no file paths, no personal labels you do not want public.
6. **Audio is the feature.** Record the app's actual audio output (not the microphone in the room).

## Pre-flight (the day before)

* Fresh disposable profile (`UNHEARD_DATA_DIR=...`) for the opening empty Chamber; a second profile with your three
  real, taught recordings and a rendered composition ready, so the orchestra shot does not wait.
* `ollama list` shows `gemma3:4b`. Warm Gemma once so the first narrator line is not a cold load (cold load can take ~14 s).
* Rehearse the correction: choose a recording where CLAP's first guess is wrong or incomplete, so the memory change is visible.
  Do not fabricate one. If all guesses are right, teach a custom name (that is still a real memory change).
* Run `uv run pytest -m real_gemma` and `-m real_model` once before filming so you know both models work today.
* Screen record at 1080p, 30 fps, system audio on; phone footage vertical, a second shot landscape for the edit.

## Timeline

| Time | Scene | Visual (all real) | Narration (English) | On-screen text |
|---|---|---|---|---|
| 0:00-0:12 | **Opening** | Empty Chamber. ECHO-0's first line, unedited, appears. Slow push in on the empty atlas. | "ECHO-0 knows the name of every sound. It has just never heard one." | `ECHO-0 has no acoustic memory.` |
| 0:12-0:32 | **Field** | Real footage: you outdoors, phone in hand, recording one safe sound; the Field screen showing Record, then Saved. Quick second location. (If phone test is not done: show laptop recorder and say so in text.) | "The screen is the shortest part. I go outside and bring something back." | `Recorded locally. Nothing leaves my machine.` |
| 0:32-0:52 | **Teaching** | Upload and the waveform/spectrogram. CLAP hypotheses with scores. You correct or name the sound. The banner confirms memory changed. | "A local audio model guesses, in similarity scores, not certainty. I tell it what I actually heard. It keeps that." | `CLAP, on CPU. Memory = retrieval, not retraining.` |
| 0:52-1:15 | **Reconstruction** | The specimen for your recording playing its original sound; then the Atlas with three real nodes and their labels; select two to show a relationship. | "Every shape is measured from its own sound. The Atlas places them by how they actually sound." | `Deterministic. Same sound, same shape.` |
| 1:15-1:40 | **The Orchestra** | Select three taught sounds, Composed mode, render (shortened tag if needed), press play. Specimens react to the timeline. Solo one source to show it is yours. | "Then ECHO-0 makes something from what I brought back. Every note comes from a recording I made." | `Composed from 3 recordings. Solo a source.` |
| 1:40-1:55 | **Conclusion** | The ending state persisted after reload. Open the narrator line's facts (the provenance disclosure). Cut to the repository page. | "Gemma speaks, and it can only say what is true. The backend earns the ending. Go outside and listen." | `Local Gemma 3 4B. Every line checked against facts.` then repo URL |

Narration is ~130 words at a calm pace. Leave pauses; the composition should be allowed to play for at least 12 seconds
uninterrupted, because it is the proof.

### The Gemma moment (important for Best Use of Gemma)

Show these three things in the 1:40-1:55 beat, in one continuous screen capture:

1. The line as the player sees it.
2. The provenance disclosure expanded, listing the facts it was built from.
3. If you have it: the template line appearing first and the Gemma line replacing it. If Gemma fell back, show the fallback reason
   instead; do not hide it. The honest version is the stronger version.

Do **not** claim "Gemma learned your sounds", "fine-tuned", "retrained" or "understands audio". Say: CLAP hears, memory
remembers, Gemma narrates.

## Music and sound cues

* No stock music. The composition *is* the soundtrack, and it should enter only at 1:15 so it lands.
* 0:00-1:15: only real ambience: your field recordings, the app's own UI sounds if any, quiet room tone. Duck the recordings by
  about 6 dB under narration.
* Fade the composition in over 2 s at 1:15; keep it at full level for the unnarrated seconds of the Orchestra scene; duck about
  6 dB under the final narration lines.
* Export at -16 LUFS integrated for the video (a loudness target for platform playback; unrelated to the -20 LUFS listening-test
  excerpts).

## Editing guidance

* Cut on action. Hold each screen long enough to read its key text (about 2.5 s for one line).
* Use the captured screens at native size; zoom only to emphasise a number (the similarity score, the memory banner).
* Burn in captions for narration (accessibility and silent autoplay).
* Keep a 0.5 s "shortened" tag on any trimmed wait.
* Add credits: models (LAION-CLAP, Gemma), tools, teammate's DEV handle, project licence, "recordings by the author".
* Final check frame by frame: no token, no path, no private label, no ESC-50 audio.

## Shot checklist

- [ ] Opening Chamber, empty profile
- [ ] Outdoor recording 1 (and 2)
- [ ] Saved locally
- [ ] Upload and hypotheses (scores visible)
- [ ] Correction/teaching and the memory banner
- [ ] Specimen playing original audio
- [ ] Atlas with 3 labelled nodes, selection
- [ ] Composed render, playback, solo
- [ ] Ending after reload
- [ ] Narrator line with facts expanded
- [ ] Repo page and licence
- [ ] Final export checked on speakers and headphones

## Fallback versions

* **No phone test:** replace the Field scene with the laptop recorder, caption "recorded on laptop microphone"; keep outdoors
  footage only if you actually recorded outdoors with it.
* **No outdoor session:** record indoors (a kettle, a door, your hands in water) and say so. Do not imply outdoors.
* **Gemma unavailable on the day:** show the template line and the `fallback_reason`. State it. Do not edit in a Gemma line.
