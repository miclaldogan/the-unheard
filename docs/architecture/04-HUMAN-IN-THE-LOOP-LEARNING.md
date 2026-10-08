# 04 — Human-in-the-Loop Learning

## 1. What changes, what doesn't
| Layer | Changes at runtime? | Name used in UI |
|---|---|---|
| Foundation model weights | **Never** (MVP) | "ears" |
| Base prediction (inference) | Per recording | "first impression" |
| Personalized memory (exemplars + prototypes) | **Yes** | "memory" |
| Category taxonomy | Yes (create/merge/rename) | "names" |
| Optional head retraining (logistic regression on embeddings) | Deferred | — |

Copy rule: UI/ECHO-0 may say *remember, recognize, mistake*. It may not say *fine-tuned, retrained, updated weights*.

## 2. Memory structure
- **Exemplar:** `(recording_id, window_idx?, embedding, label_id, weight, status, created_at)`. `status ∈ {active, retracted, quarantined}`.
- **Prototype per label:** weighted mean of active exemplar embeddings, L2-normalised; recomputed on change; carries `n_eff` and intra-class spread σ_c (mean cosine distance to prototype).
- `memory_version` increments on every mutation; every Prediction stores the version it used (reproducible, and enables "re-score past recordings" diffs).

## 3. Prediction fusion
Let `s_base(c)` be base score (CLAP zero-shot, calibrated with per-class Platt-like temperature when ≥ 10 labelled eval examples exist; otherwise raw softmax temp τ_b fixed from M0).
Memory score via kernel kNN over exemplars of class c:

`s_mem(c) = Σ_{i∈kNN(x), y_i=c} w_i · exp(cos(x,e_i)/T)  /  Σ_{i∈kNN(x)} w_i · exp(cos(x,e_i)/T)`  (k=7, T=0.07 [H — tuned on eval])

Log-linear (product-of-experts) fusion:

`log p(c|x) ∝ (1−λ_c)·log s_base(c) + λ_c·log s_mem(c)`, with `λ_c = n_eff,c / (n_eff,c + κ)`, κ=3.

Rationale: with 0 exemplars λ=0 → pure base model; evidence moves trust monotonically to memory; no hand-set "confidence". For multi-label output, apply the same fusion per label on independent scores (replace normalisation by a per-label logistic).

**Disagreement policy:** if argmax_base ≠ argmax_mem and both individually ≥0.5, present *both* ("my ears say X, my memory says Y") and ask; this is the primary active-learning prompt. Memory wins ties only when the closest exemplar cosine ≥ 0.85 [H].

## 4. Novelty / open-set
`novel(x) = [max_i cos(x,e_i) < τ_n] ∧ [fused margin (top1−top2) < τ_m] ∧ [base entropy > τ_e]`.
τ_n is set per install as the 5th percentile of leave-one-out nearest-same-class cosine; until ≥ 20 exemplars exist it uses an M0-derived default. Novel ⇒ ECHO-0 displays *"I have no name for this"* with nearest known sounds, not a guess. This is the **Act V** mechanism: user creates label → `LabelCreated` + exemplar → atlas/composition events fire.

## 5. Active learning (what to ask)
Priority score = `margin_low + disagreement + novelty + cluster_gap` — the recording whose answer would most change memory. One question at a time; ≤ 3 pending questions.

## 6. Hard cases
| Case | Handling |
|---|---|
| Class imbalance | Per-class weights cap the exemplar contribution; top-k per class by recency+diversity (farthest-point) keeps ≤ 50 exemplars/class |
| Contradictory labels | Label edit never deletes history: old annotation → `superseded`; exemplar re-pointed; nearest-neighbour conflicts (same embedding, different label) flagged `quarantined` and surfaced as a question |
| Duplicates | Content hash equality blocks insert; near-dup (cos>0.995, same label) collapsed into one exemplar with weight sum capped |
| Misleading / noisy labels | Leave-one-out check at insert: if the exemplar disagrees with its own k-neighbours' consensus and base model strongly agrees with them, mark "suspect" and ask for confirmation |
| Merge categories | Reassign exemplars, keep alias row, bump version; prediction history keeps original label ids |
| Delete recording | Cascade exemplar removal, recompute prototypes, record `MemoryUpdated(reason=delete)` |
| Decay | Not in MVP; exemplar `weight` field exists for future decay |
| Multiple users | MVP is single anonymous install; schema has `install_id` so exports can later merge with namespace-by-install |

## 7. Evaluation (see doc 11)
Split by **recording session**, not by clip, so near-identical consecutive clips don't leak. Report macro-F1, per-class P/R, top-1/3, ECE, unknown detection AUROC, and before/after personalization with 0/1/3/5 exemplars per class. Recalling a recording already in memory is explicitly excluded from the headline number.

## 8. Optional later: lightweight retraining
Periodic multinomial logistic regression over embeddings (sklearn) replacing the kNN term, only if it beats kNN on the held-out set; still would not touch the foundation model.
