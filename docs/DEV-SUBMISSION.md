<!--
DRAFT. NOT PUBLISHED. Copy everything below the line into the DEV editor (Basic/Markdown).

BEFORE YOU PUBLISH (owner):
1. Paste it into the official Week 1 submission template on https://dev.to/challenges/hf26 (the template text itself could not
   be retrieved here). Keep its required sections/headings if they differ from the ones below, and keep the tag #hf26challenge.
2. Replace every [[OWNER: ...]] marker with something true, or delete the sentence. Nothing in brackets may ship.
3. List your teammate's DEV username in "Team" (she wrote the M1-M3 commits). Teams must credit everyone.
4. Add the demo video link, screenshots (with alt text), and the repo link once the release branch is on the public default branch.
5. Set the AI disclosure control to "some_ai" (human-authored with meaningful AI assistance). Do NOT choose "no_ai".
6. Submissions are due Oct 11, 2026 11:59 PM PDT. One entry per person. The project must have been started inside the window
   (the first commit is Oct 9, 2026 local time, inside Oct 5-11). Any commit after the deadline must be noted in the README.
7. Confirm the teammate credit below is exactly how you want it stated, and re-check every number against docs/M6-FINAL-REPORT.md.
8. Read DEV's AI guidelines: the post must be checked for factual accuracy by you before publishing.
-->

---
title: The Unheard: I taught a machine what rain sounds like, and it taught me to listen
published: false
tags: hf26challenge, gemma, opensource, ai
cover_image: [[OWNER: 1000x420 cover, e.g. the Atlas screenshot; alt text in the body]]
description: A local-first game where you record real sounds, teach an AI their names, and hear them become a composition. Local CLAP, personalised memory, and a Gemma narrator that is not allowed to lie.
ai_disclosure_level: some_ai
---

ECHO-0 knows that rain exists. It has read the word ten thousand times. It can tell you that rain is water falling from
clouds, that it smells of petrichor, that it is sad in songs. It has just never *heard* any.

That is the premise of THE UNHEARD, and it is also, I think, an honest description of where I was when I started this. I
spend my days with a screen that describes the world to me, and I could not have told you what the street outside my
window sounded like at any given hour.

So the game works backwards. You do not play it on the screen. You take a phone outside, record something that is really
there, and bring it back to a machine that has lost its acoustic memory. You tell it what you heard. It gets things wrong,
you correct it, and it remembers. By the end, the sounds you collected are an orchestra.

## What I Built

THE UNHEARD is a local-first web app (a React PWA backed by a FastAPI server on your own laptop) with six scenes:

1. **Chamber.** ECHO-0 waits, and tells you honestly how much it has heard so far.
2. **Field.** Record a real sound. It is saved in your browser first (even offline), then uploaded when you choose.
3. **Hearing.** A local CLAP model proposes what the sound might be, as similarity scores rather than fake percentages. You confirm, correct, name something new, or say "I don't know."
4. **Specimen.** Every recording becomes a small visual artifact generated deterministically from its measured acoustics. Same sound, same shape, always.
5. **Atlas.** Your recordings placed by how similar they actually sound, with the names you gave them.
6. **Orchestra.** Pick three or more taught sounds and ECHO-0 composes a piece *from the recordings themselves*: motifs, phrases, call-and-response, with stems you can mute and solo and a WAV you can keep.

The ending is not scripted. It unlocks when a real composition exists, built from at least three recordings you annotated. If
you have only taught it two sounds, there is no ending to see.

![[[OWNER: screenshot of the Atlas with real labelled recordings; describe what is visible]]]([[OWNER: image url]])

## Demo

{% embed [[OWNER: demo video URL]] %}

The video shows [[OWNER: describe truthfully: the real session, which sounds, what is cut]]. Processing waits are shortened
where noted on screen and never faked.

## Code

{% embed https://github.com/miclaldogan/the-unheard %}

MIT licensed. The README has install steps; model weights are downloaded locally and are never in the repository.
*Team: built with [[OWNER: teammate's DEV username]], who wrote the audio ingestion, the hearing and memory layer, and the
first versions of the acoustic atlas.*

## How I Built It

### The part that hears: CLAP

[LAION-CLAP](https://huggingface.co/laion/clap-htsat-unfused) turns 48 kHz audio into a 512-dimensional embedding and
scores it against text labels, entirely on CPU. On my 15 GB laptop the first load takes about 7 seconds and a 5-second
clip takes roughly a quarter of a second. It is a frozen pretrained model. Nothing in this project trains it.

### The part that learns: memory, not training

When you name a sound, the app stores that recording's embedding as an *exemplar* of your label. Later predictions are a fusion
of CLAP's scores and nearest-neighbour similarity to your exemplars, and the interface shows which is speaking. It is
retrieval, not retraining, and I want to be exact about that because it is the line most easily blurred.

Here is a real result from my test run, with real rain recordings. I taught the app two rain clips and called them "Roof gutter."
On a third rain clip it had never seen, "Roof gutter" had not been among the top three guesses before. Afterwards it was
second, with a memory similarity of 0.837 to the exemplars. The model did not change. The memory did.

There was a nasty bug in this part, and I think it is worth admitting. If you named a sound *before* its analysis finished,
the name was saved but never became an exemplar. The sound looked taught and was not. The fix attaches the stored name to
the embedding the moment inference completes, exactly once, and the interface now says "memory has not changed yet" until
that is true. The same test with real CLAP now reaches the same 0.837 whether you teach before or after.

### The part that composes

The orchestra is an offline NumPy/SciPy renderer. It does not use a music model. It cuts motifs out of your actual recordings,
finds which ones are pitched or percussive, builds phrases and sections, and lets one source answer another in the gaps.
Every note in the output is traceable to a window of a recording you made, and the plan records which.

### The part that speaks: Gemma, on a leash

ECHO-0's voice is a local Gemma model (`gemma3:4b` through Ollama, about 3.3 GB). I did not want a chatbot bolted onto a
game. I wanted it to have three narrow jobs, and to be unable to do anything else:

* **Interpret memory.** Given a handful of facts ("you corrected the ears from Wind to Rain"), say one or two lines about
  what that means.
* **Reason about missions.** The backend finds real gaps in your sound memory (a name with one example, a sound nobody could
  name, nothing pitched yet). Gemma picks among them and words them. It cannot invent one, and it cannot decide whether you
  completed it. Plain code does that.
* **Comment on the composition**, using the real source roles and the real plan.

Gemma never sees ids, audio, your notes or your mood. It sees short fact lines with handles, and must answer in a JSON
schema, citing the facts it used. Then a validator, written as deliberately suspicious code, checks the answer: every number
must appear in a cited fact, every quoted name must be one the player gave, no sound source may be mentioned that is not in the
evidence, no claims of having visited or seen anything, no "I was retrained," no markup, no ids. If anything fails, a
deterministic template says the line instead and the reason is recorded.

This is not hypothetical. In my evaluation (19 moments of a real journey, three seeds each, 57 real calls), **84.2% of Gemma's
first attempts passed the validator**. The other 15.8% were rejected: the model wrote an internal handle like "F1" into prose,
or repeated a number it should not have. One of my own bugs hid in there too: the validator treated the apostrophe in "the
ears' strongest hypothesis" as an opening quote, and fixing that moved the rate from 71.9% to 84.2%. I tried telling the model
not to write handles, and in that run it wrote *more* of them (14 rejections against 9), so I reverted the change. Median warm latency is about 1.3 seconds, and the game
shows its template line immediately and swaps in Gemma's when it arrives, so nothing ever waits on the model.

What I have **not** measured: the end-to-end fallback rate after the single retry, and whether people actually prefer
Gemma's lines to the templates. I built a blind rating sheet for that. As of writing, nobody has rated it, so I make no claim that Gemma's lines are better than the templates. The templates are not a fallback of shame. They are the baseline the model has
to be worth having beside.

### Tests

283 backend tests, 78 frontend tests, plus gated real-CLAP (2) and real-Gemma (1) tests, and a scripted browser walkthrough in sandboxed
Chrome 148 with a simulated microphone. *The phone is the thing I cannot claim.* As of writing it has not been run on a physical Android phone; the scripted run only simulates the microphone.

## Taking it outside

[[OWNER: this section is the heart of the challenge theme ("make the screen the shortest part"). Write what actually happened
when you went outside: where, what you recorded, what ECHO-0 got wrong, what surprised you, how the composition felt. Two honest
paragraphs beat six invented ones. If you did not get to test outdoors, delete this section and say so in the limits below.]]

## Why Open Innovation Matters

I could not have built this on a closed API, and the reasons are specific.

* **The recordings are mine.** A sound from my own kitchen, my own street, my own voice is exactly the kind of data I do not
  want on a server I do not control. CLAP, the memory, the composer and Gemma all run on my machine. The phone only captures.
* **I could inspect and constrain the model.** Because Gemma runs locally behind Ollama, I could force a JSON schema, measure
  its failures honestly, and put a validator between it and the player. That exercise is why I know the number is 84.2% and
  not "it seemed fine."
* **Swapping parts is trivial.** The narrator is a setting. The listening model sits behind a small interface. When a better open
  audio-text model appears, it replaces CLAP without touching the game.
* **It costs nothing to run** once the weights are downloaded, and no network is needed beyond your own devices talking to
  each other. I want to be careful here: capture works offline on the phone; inference, Gemma and composition need the
  laptop. This is not an on-device AI app.

## Prize Categories

* **Overall:** entered through this challenge submission.
* **Best Use of Gemma:** Gemma is the narrative intelligence, with three separate, testable responsibilities, grounded
  evidence packets, strict validation, and a deterministic fallback. It was **not** fine-tuned, it does not hear audio, and it
  does not own any game state. Its value is in saying true, specific, characterful things about what the player actually did,
  and being unable to say false ones.

## My Agent Session

I built this with AI coding assistants (Claude Code for the backend, narrative engine and release engineering, and Codex for the
interface), so the post is disclosed as AI-assisted. [[OWNER: if you saved the session with DevRelay, add
`{% agent_session <id_or_slug> %}` here and open it in Make Public. Read the transcript first: it can contain local paths and
anything typed in the terminal, and nothing with keys or personal data should be shared.]]

## What it cannot do (yet)

* The musical quality is unrated by humans. The automatic checks say the refined composer fixes measurable problems (repeated
  bars, competing foreground sounds); they do not say it is beautiful. I made a blind listening page so that question has an
  answer from ears that are not mine.
* Novelty detection is a heuristic, and CLAP's top guess for a quiet or mixed sound is often wrong. That is the point of the game,
  and also the reason it asks you.
* Recording can stop when a phone locks. I did not claim background capture, and the app asks you to keep the screen awake.
* The ESC-50 clips I used to test are for private evaluation. The public demo uses sounds I recorded myself.

The strangest thing I learned is that teaching the machine was the quickest way to notice what I had never listened to. If you build
anything like this, take it outside.
