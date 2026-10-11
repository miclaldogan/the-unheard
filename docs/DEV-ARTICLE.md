<!--
DRAFT, NOT PUBLISHED. Copy everything below the closing line of this comment into the DEV editor.

Before you publish:
1. Open the official Week 1 template on https://dev.to/challenges/hf26 and keep its required headings if they differ.
2. Upload video/out/the-unheard-demo.mp4 (to YouTube/Vimeo, or DEV's uploader) and replace VIDEO_URL below.
3. The image links use raw.githubusercontent.com paths on `main`; they work once this branch is merged. Otherwise upload docs/m8-review/*.jpg in the editor.
4. Add Melike's DEV username next to her name if she has one.
5. Keep ai_disclosure_level: some_ai. Tags are limited to four.
6. Deadline: Oct 11, 2026 11:59 PM PDT.
-->

---
title: THE UNHEARD: a game that sends you outside, teaches a machine to listen, and keeps it honest
published: false
tags: hf26challenge, gemma, opensource, ai
cover_image: https://raw.githubusercontent.com/miclaldogan/the-unheard/main/docs/m8-review/05-hearing-desktop.jpg
description: A local-first audio-learning game. A local CLAP model hears, retrieval memory remembers what you teach it, and Gemma narrates under a validator that is not allowed to lie.
ai_disclosure_level: some_ai
---

ECHO-0 knows the name of every sound. It has never heard one.

That sentence is the whole game. You open THE UNHEARD and meet a machine that has read about rain, bells and footsteps
and has no acoustic memory of any of them. You give it sounds, you tell it what they are, and it slowly builds a memory
that is yours. At the end, the sounds you gave it are an orchestra.

## What We Built

THE UNHEARD is a local-first web app: a React PWA, a FastAPI server, SQLite, a CPU audio model and a local Gemma. Nothing
leaves your machine. It has six scenes.

1. **Chamber.** ECHO-0 waits and says honestly how much it has heard.
2. **Field.** Record a sound. It is stored in the browser first, even offline, and uploaded when you choose.
3. **Hearing.** A local CLAP model proposes what the sound might be, as similarity scores, never fake probabilities. You confirm, correct, rename, or say you do not know.
4. **Specimen.** Every recording becomes a visual artifact generated deterministically from its measured acoustics. Same sound, same shape.
5. **Atlas.** Your recordings placed by how alike they actually sound.
6. **Orchestra.** Pick three or more taught sounds and ECHO-0 composes from the recordings themselves, with stems you can mute and solo and a WAV you can keep.

The ending is not scripted. It unlocks only when a real composition exists, built from at least three recordings you named.

![The Hearing Room on a real run: CLAP's own top guess is "Church bells" at 0.367, while the name the player taught, "Bells", is first through memory at 0.844](https://raw.githubusercontent.com/miclaldogan/the-unheard/main/docs/m8-review/05-hearing-desktop.jpg)

*The Hearing Room. CLAP's own ears put "Church bells" at cosine 0.367. The name the player taught, "Bells", has a memory similarity of 0.844 from two remembered examples, so memory ranks it first. These are scores, not probabilities.*

## Demo

{% embed VIDEO_URL %}

The video is 50 seconds, narrated and scored. **Read this part before you trust it:** the sounds in the demo were generated with
the ElevenLabs sound-effects API, the narration is an ElevenLabs voice, and the music is the app's own Composed render of
those generated sounds. They are not field recordings. We did not get a physical outdoor session in before the deadline, and
we say so on screen.

## Code

{% embed https://github.com/miclaldogan/the-unheard %}

MIT licensed. Model weights are downloaded locally and are never in the repository.

Built by **Iclal Dogan** and **Melike Zaman**. Melike wrote the audio ingestion, the hearing and memory layer and the first versions of the acoustic atlas; Iclal built the narrative engine, the composer integration, the release engineering and the demo.

## How We Built It

### The part that hears: CLAP

[LAION-CLAP](https://huggingface.co/laion/clap-htsat-unfused) turns audio into a 512-dimensional embedding and scores it against text labels, on CPU. It is a frozen pretrained model. Nothing in this project trains it.

### The part that learns: memory, not training

When you name a sound, the app stores that recording's embedding as an exemplar of your label. Later predictions fuse CLAP's scores with nearest-neighbour similarity to your exemplars, and the interface shows which one is speaking. It is retrieval, not retraining, and we want to be exact about that because it is the easiest line to blur.

On the demo set, I taught the app two "Roof gutter" clips. On a third clip it had never heard, the name was absent from the top three before teaching (Rain, Bicycle, Lawn mower) and **first** afterwards, with two exemplars behind it. The model did not change. The memory did.

We also found a real bug here. If you named a sound *before* its analysis finished, the name was saved but never became an exemplar, so the sound looked taught and was not. The fix attaches the stored name to the embedding when inference completes, exactly once, and the interface says "memory has not changed yet" until that is true. A test with real CLAP reaches the same similarity (0.837) whether you teach before or after.

### The part that composes

The orchestra is an offline NumPy and SciPy renderer. There is no music model. It cuts motifs out of your recordings, finds which are pitched or percussive, builds phrases and sections, and lets one source answer another. Every event in the output traces back to a window of a recording, and the plan records which. The piece in the video has 47 such events.

![The Impossible Orchestra: a Composed render from three taught recordings, with stems, a timeline and the ECHO-0 lines about it](https://raw.githubusercontent.com/miclaldogan/the-unheard/main/docs/m8-review/11-orchestra-desktop.jpg)

### The part that speaks: Gemma, on a leash

ECHO-0's voice is a local `gemma3:4b` through Ollama (4.3B parameters, Q4_K_M). We did not want a chatbot bolted onto a game. Gemma has three narrow jobs: interpret memory changes, reason about missions, and comment on a composition. The backend finds real gaps in your sound memory and Gemma can only choose among them and word them. It cannot invent one, and it cannot decide whether you completed it. Plain code does that.

Gemma never sees ids, audio or your notes. It sees short fact lines and must answer in a JSON schema, citing the facts it used. Then a deliberately suspicious validator checks the answer: every number must appear in a cited fact, every quoted name must be one the player gave, no source may be mentioned that is not in the evidence, no claims of having seen anything, no "I was retrained", no markup. If anything fails, a deterministic template says the line instead and the reason is recorded.

The numbers, stated exactly: in an evaluation over 19 moments of a real journey, three seeds each (57 calls), **84.2% of first attempts passed the validator** (48 of 57), and it reproduced on a second run. The other 15.8% were rejected, for example when the model wrote an internal handle like "F1" into prose. One of the rejections was our own bug: the validator read the apostrophe in "the ears' strongest guess" as a quote, and fixing it moved the rate from 71.9% to 84.2%. Median warm latency is about 1.3 seconds, and the game shows its template line first and swaps in Gemma's when it arrives.

What we have **not** measured: the end-to-end fallback rate after the single retry, and whether people prefer Gemma's lines to the templates. We built a blind rating sheet for that; nobody has filled it in yet, so we make no claim that Gemma's wording is better. In the final demo run, Gemma was called twice and one answer was rejected (`invalid_json`), which is too few calls to call a rate. Gemma is a validated narrator. It does not hear audio, it was not fine-tuned, and it owns no game state.

## Why Open Innovation Matters

* **The recordings are yours.** A sound from your kitchen or street is exactly what you do not want on someone else's server. CLAP, the memory, the composer and Gemma all run on your machine. The phone only captures.
* **We could constrain the model.** Because Gemma runs locally, we could force a JSON schema, measure its failures honestly and put a validator between it and the player. That is why we know the number is 84.2% and not "it seemed fine".
* **Parts are swappable.** The narrator is a setting. The listening model sits behind a small interface and can be replaced without touching the game.
* **It costs nothing to run** after the weights are downloaded. To be precise: capture works offline on the phone, but inference, Gemma and composition need the laptop. This is not an on-device AI app.

## Prize Categories

* **Overall:** entered through this challenge submission.
* **Best Use of Gemma:** Gemma is the narrative intelligence with three separate, testable jobs, grounded evidence packets, strict validation and a deterministic fallback.

## Taking It Outside

The point of the challenge is to make the screen the shortest part, and this is where we owe you honesty. The game is built around going outside with a phone and bringing something back. For this submission we did not complete that outing: the Android field test is written up (`docs/ANDROID-FIELD-TEST.md`) but not performed, and the demo uses AI-generated sounds so that we could publish audio we are allowed to show. Treat our automated browser runs (a desktop Chrome with a simulated microphone) as exactly that, and not as evidence about phones.

## My Agent Session

We built this with AI coding assistants (Claude Code for the backend, narrative engine, release engineering and this video's tooling, and Codex for the interface), so the post is disclosed as AI-assisted.

## What It Cannot Do Yet

* **Human review is missing.** The musical quality has not been rated by people. Automatic checks say the refined composer fixes measurable problems such as repeated bars; they do not say it is beautiful. A blind listening page exists for that.
* **Novelty detection is a heuristic.** CLAP's top guess for a quiet or mixed sound is often wrong. That is the point of the game, and why it asks you.
* **Recording can stop when a phone locks.** We did not claim background capture.
* **Generated sounds are easier than real ones.** Variants generated by one model are more similar to each other than real field recordings, so the demo shows the mechanism, not field performance.
* **Tests:** 283 backend tests, 78 frontend tests, plus gated real-CLAP and real-Gemma tests.

The strangest thing we learned is that teaching the machine is the quickest way to notice what you never listened to. If you build anything like this, take it outside.
