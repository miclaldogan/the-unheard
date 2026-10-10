# Human review: music and Gemma narration

**Status: PENDING.** No human has rated anything yet. This page explains how to do both reviews in about 40 minutes
and how to read the result. Nothing here is a finding; no score has been invented, and the tools below refuse to print
a conclusion from an empty sheet.

## Part 1: Listening review (Legacy vs Organic vs Composed)

### What you will hear

Three source sets, each rendered three ways from the **same recordings and seed**:

| Set | Sources (ESC-50 clips) | Character |
|---|---|---|
| Natural | rain, wind, water drops, chirping birds | atmospheric, texture-led |
| Urban | engine, clock tick, footsteps, car horn | rhythm-led, no pitched source |
| Hybrid | vacuum cleaner, rain, footsteps, church bells | mixed |

* **Legacy** is the M4.5 composer. **Organic** is source-timed atmospheric structure. **Composed** builds motifs, phrases,
  sections and call-and-response from the sources.
* Each version makes its own plan (tempo, form, length), so they are matched on what can be matched, not on content: each
  excerpt is the convergence section plus 8 s lead-in, 25 s, 48 kHz, matched to **-20.0 LUFS integrated** (measured:
  all nine excerpts landed on -20.0). Matching loudness removes the "louder sounds better" bias; it does not make the
  pieces equivalent.
* Order is **shuffled per set** and labelled X, Y, Z. The key is only in the exported CSV.

### How to run it

```bash
cd server
uv run python ../scripts/m4_6_compare.py --out data/m4_6        # renders the audio (about 2 min, git-ignored)
uv run python ../scripts/m6_listening_page.py --root data/m4_6  # writes data/m4_6/listening/index.html
xdg-open data/m4_6/listening/index.html                          # works from file://, nothing is uploaded
```

1. Listen to X, Y, Z of one set (headphones once, speakers once if you can). Do not read the file names.
2. Score each version 1 (poor) to 5 (excellent) on the six criteria below. Leave a criterion empty if you cannot judge it.
3. Choose a preferred version for the set, add notes, repeat for the other sets.
4. **Download ratings** (CSV). Then: `python3 scripts/m6_ratings.py listening-summary ~/Downloads/unheard-listening-ratings.csv`.

Ratings autosave in the browser. One listener is an anecdote: if you can, ask one or two other people to run the same page and
compare their CSVs. Do not average a single rater and call it a result.

### Rubric

| Criterion | 1 | 3 | 5 |
|---|---|---|---|
| Musical coherence | a pile of unrelated sounds | has moments of shape | one piece with a beginning, development and arrival |
| Rhythm and variation | static or chaotic | a pulse that mostly stays the same | a pulse that moves and returns in interesting ways |
| Sound clarity | muddy or harsh | okay, some masking | layers distinct, nothing fatiguing |
| Source recognizability | cannot tell what it was made from | some sources recognisable | you can follow each real-world sound |
| Emotional impact | nothing | mild | you felt something (any feeling counts) |
| Overall listening enjoyment | would skip | fine once | would listen again |

### What the objective diagnostics say (and do not say)

The automatic quality report (`data/m4_6/report.json`) uses proxies such as foreground competition, density, repetition and
fragment reuse. On this render: **Organic and Composed raised no flags in any of the three sets**; **Legacy** was flagged for
Urban (competing foreground attacks, little air, one fragment reused more than 20 times) and Hybrid (54% of foreground bars
repeat an earlier bar exactly), and clean for Natural. These flags say where to listen carefully and that the M4.6 fixes
address measurable problems. They are not a score of musical quality: whether the result is *better to a person* is
exactly what this review decides.

### Reading the outcome honestly

* If Composed is not preferred, say so; the demo can still use Organic.
* If recognisability is low for a set, prefer the other set in the video.
* Do not write "sounds better" anywhere public until at least one person has actually rated it that way.

### Licensing

These excerpts are derived from ESC-50 (CC BY-NC 3.0, with per-clip Freesound licences). **They are for private listening
only. Do not publish them, in the repo, the article, or the video.** The public demo should use sounds you recorded
yourself (see `DEMO-FINAL-SCRIPT.md`).

| | |
|---|---|
| Listening review status | **PENDING** |
| Listeners / setup | |
| Preferred mode per set | |
| Date completed | |

## Part 2: Gemma vs template narration

### What is compared

For the 19 moments of the M5 evaluation journey, each row shows the facts ECHO-0 was given and two anonymous options: the
deterministic template line and a validated `gemma3:4b` line, in shuffled order. The key is in the last column; do not
look before rating.

```bash
python3 scripts/m6_ratings.py gemma-sheet      # (re)create eval/m6/gemma_human_rating.csv, nothing pre-filled
# fill in eval/m6/gemma_human_rating.csv in a spreadsheet, then:
python3 scripts/m6_ratings.py gemma-summary
```

Rate each option 1-5:

| Criterion | Question |
|---|---|
| Factual accuracy | Does it say anything the facts do not support? (5 = nothing unsupported) |
| Grounding | Does it stay on what actually happened in the game? |
| Character | Curious, precise, uncertain, quietly poetic; never cheerful or generic? |
| Creativity | Does it say it in a fresh, memorable way? |
| Relevance | Does it fit this moment of the game? |
| Readability | Clear and the right length (10-40 words)? |

Then mark which option you prefer (1, 2 or tie) and add notes. The summary prints means per condition and says "too few"
under 10 rated rows. A single rater, 19 items, one run is a pilot, not proof.

### What has been measured, and what has not

| Measured (objective, M5) | Value |
|---|---|
| Template output valid under the same validator | 19 of 19 moments |
| Gemma first attempts valid | **84.2%** (48 of 57 calls over 19 moments x 3 seeds), reproduced on a second run |
| Gemma schema-compliant | 100% (JSON schema constrained decoding) |
| Gemma invented ids | 0 (the model cannot emit ids) |
| Warm latency | median 1.3 s, p95 1.9 s on this laptop |
| Live journey sample (M5.5) | 8 requests, 7 valid, 1 fallback; a small QA sample, not a rate |

* The 84.2% is a **first-attempt** figure on this fixed journey. Production retries once and falls back to the template on
  failure; the end-to-end fallback rate was **not** measured and must not be inferred from 84.2%.
* Validity means "passed the grounding and policy checks". It does not mean the prose is good.
* Gemma wording is **less** varied per word than the templates (distinct-1 0.20 vs 0.29), but the same moment is phrased
  differently across seeds (variety 0.93). Whether that is better is what the human sheet is for.

| | |
|---|---|
| Gemma-vs-template human rating status | **PENDING** |
| Rater(s) | |
| Rated rows | |
| Date completed | |

### Three different things, never to be confused

* **CLAP** (LAION `clap-htsat-unfused`) turns audio into a 512-dimensional embedding and scores it against text labels. It is
  the only part that "hears". It is a frozen pretrained model.
* **Personalised memory** is k-nearest-neighbour retrieval over *your* annotated embeddings, fused with CLAP's scores. When
  you teach a sound, an exemplar is stored and future predictions can cite it. **Nothing is retrained or fine-tuned.**
* **Gemma** never hears audio and never decides anything about the game. It receives short text facts, produces a short
  line, and its output is checked against those facts before display. **Gemma was not fine-tuned.** It runs locally through
  Ollama as an open-weight model, which is why the facts, labels and narration never leave the machine.
