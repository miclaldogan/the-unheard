import type { MemoryOverview, RecordingSummary } from "../api/types";
import { narrativePresence, type NarrativeSnapshot } from "../api/narrative";
import { NarrativeVoice } from "./NarrativeVoice";
import { EchoCore } from "./EchoCore";
interface Props {
  items: RecordingSummary[];
  memory: MemoryOverview | null;
  connected: boolean;
  onField: () => void;
  onHear: (id?: string) => void;
  onAtlas: () => void;
  onCompose: () => void;
  snapshot: NarrativeSnapshot | null;
  narrativeStatus: "loading" | "ready" | "unavailable" | "error";
}
export function Chamber({
  items,
  memory,
  connected,
  onField,
  onHear,
  onAtlas,
  onCompose,
  snapshot,
  narrativeStatus,
}: Props) {
  const story = snapshot?.current.utterance;
  const ready = items.filter((r) => r.status === "ready");
  const known = memory?.labels.filter((l) => l.n_exemplars > 0) ?? [];
  const presence =
    (snapshot
      ? narrativePresence(snapshot.state, snapshot.current.utterance)
      : null) ??
    (memory?.exemplars
      ? "remembering"
      : ready.length
        ? "uncertain"
        : "dormant");
  return (
    <main id="main-content" className="chamber">
      <section className="chamber-hero" aria-labelledby="chamber-title">
        <div className="chamber-copy">
          <div className="eyebrow">
            <span className="signal-mark" /> THE CHAMBER / ECHO-0
          </div>
          <h2 id="chamber-title">
            {ready.length ? (
              <>
                The world returns,
                <br />
                <em>one sound at a time.</em>
              </>
            ) : (
              <>
                A world forgotten.
                <br />
                <em>A sound away.</em>
              </>
            )}
          </h2>
          {story ? (
            <NarrativeVoice utterance={story} compact />
          ) : (
            <p className="hero-story">
              I know the names of things. But I have forgotten how the world
              sounds. Will you become my ears?
            </p>
          )}
          <p className="hero-instruction">
            {ready.length
              ? "Bring another sound, teach me what it means, or listen to the memories we have gathered."
              : "Step outside. Find a small sound you would otherwise pass by. Bring it back, and give it a name."}
          </p>
          <div className="row hero-actions">
            <button className="btn primary" onClick={onField}>
              Go outside <span aria-hidden="true">↗</span>
            </button>
            <button className="btn ghost" onClick={() => onHear(ready[0]?.id)}>
              {ready.length
                ? "Return to the hearing room"
                : "Enter the laboratory"}{" "}
              <span aria-hidden="true">→</span>
            </button>
          </div>
          <div className="hero-provenance">
            {story
              ? `${snapshot?.state.acts.find((a) => a.status === "active")?.title ?? "The world remembered"} · ${story.source === "gemma" ? "Local narrative model" : "Grounded template"}`
              : narrativeStatus === "loading"
                ? "Connecting to the narrative…"
                : narrativeStatus === "error"
                  ? "Narrative unavailable. Your acoustic tools are ready."
                  : "An invitation · story progression awaits the narrative connection"}
          </div>
        </div>
        <div className="chamber-instrument">
          <div className="instrument-caption">
            <span>MEMORY OBSERVATORY</span>
            <span>NO. 000 / ECHO</span>
          </div>
          <EchoCore presence={presence} memories={ready.length} />
          <div className="instrument-caption">
            <span>
              {connected
                ? `${ready.length} preserved signals`
                : "Laboratory connection unavailable"}
            </span>
            <span>{presence.toUpperCase()}</span>
          </div>
        </div>
      </section>
      {snapshot && (
        <section className="story-progress" aria-label="Narrative progression">
          {snapshot.state.acts.map((act) => (
            <div key={act.id} className={`act act-${act.status}`}>
              <span className="eyebrow">{act.status}</span>
              <strong>{act.title}</strong>
              <span>
                {act.progress.current} / {act.progress.target}
              </span>
            </div>
          ))}
          <details>
            <summary>The discoveries that brought us here</summary>
            {snapshot.state.milestones
              .filter((m) => m.achieved)
              .map((m) => (
                <p key={m.id} className="caption">
                  ✓ {m.title}
                  {m.achieved_at
                    ? ` · ${new Date(m.achieved_at).toLocaleDateString()}`
                    : ""}
                </p>
              ))}
          </details>
        </section>
      )}
      <section className="journey" aria-label="The journey">
        <button onClick={onField}>
          <span className="step-no">01 / FIELD</span>
          <strong>Borrow the world.</strong>
          <span>A recording begins outside.</span>
          <i aria-hidden="true">↗</i>
        </button>
        <button onClick={() => onHear(ready[0]?.id)}>
          <span className="step-no">02 / HEARING</span>
          <strong>Give it meaning.</strong>
          <span>Your interpretation shapes memory.</span>
          <i aria-hidden="true">→</i>
        </button>
        <button onClick={onAtlas}>
          <span className="step-no">03 / MEMORY</span>
          <strong>Find the connections.</strong>
          <span>Explore an acoustic inner world.</span>
          <i aria-hidden="true">→</i>
        </button>
        <button onClick={onCompose}>
          <span className="step-no">04 / ORCHESTRA</span>
          <strong>Listen to it become.</strong>
          <span>Real sounds. An impossible ensemble.</span>
          <i aria-hidden="true">→</i>
        </button>
      </section>
      {ready.length > 0 && (
        <section className="memory-strip" aria-label="Remembered world">
          <div>
            <div className="eyebrow">The world so far</div>
            <h3>
              {known.length
                ? "Some things have names again."
                : memory && memory.annotations > memory.unknown_annotations
                  ? "Your interpretations are preserved."
                  : "These sounds are waiting for meaning."}
            </h3>
          </div>
          <div className="row">
            {known.slice(0, 6).map((l) => (
              <span key={l.label_id} className="memory-name">
                {l.name} <small>{l.n_exemplars}</small>
              </span>
            ))}
            <button className="btn small" onClick={onAtlas}>
              Explore {ready.length} signals →
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
