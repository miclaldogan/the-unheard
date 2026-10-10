import type { Utterance } from "../api/narrative";
export function NarrativeVoice({
  utterance,
  compact = false,
}: {
  utterance: Utterance;
  compact?: boolean;
}) {
  return (
    <div
      className={`narrative-voice ${compact ? "compact" : ""}`}
      aria-label="ECHO-0 narrative"
    >
      <div className="eyebrow">
        ECHO-0 / {utterance.moment.kind.replaceAll("_", " ")}
      </div>
      {utterance.lines.map((line, i) => (
        <p
          key={`${utterance.id}-${utterance.revision}-${i}`}
          className={line.kind === "imagination" ? "imagination" : "grounded"}
        >
          {line.text}
          <small>
            {line.kind === "imagination"
              ? "Interpretation · imagination"
              : line.provenance.map((p) => p.replaceAll("_", " ")).join(" · ")}
          </small>
        </p>
      ))}
      <details>
        <summary>What this voice is grounded in</summary>
        {utterance.facts.map((f) => (
          <p className="caption" key={f.handle}>
            {f.statement}{" "}
            <span className="chip">{f.provenance.replaceAll("_", " ")}</span>
          </p>
        ))}
        <p className="caption">
          {utterance.source === "gemma"
            ? `Local narrative model · ${utterance.model}`
            : "Grounded template"}
          {utterance.generation.status === "pending"
            ? " · wording is still being refined"
            : ""}
        </p>
        {utterance.generation.status === "fallback" && (
          <p className="caption">
            Preserved facts are speaking ·{" "}
            {utterance.generation.fallback_reason?.replaceAll("_", " ") ??
              "template fallback"}
          </p>
        )}
      </details>
    </div>
  );
}
