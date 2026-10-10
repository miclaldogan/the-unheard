import { useState } from "react";
import { narrativeApi, type Missions } from "../api/narrative";
export function FieldMission({
  missions,
  onChanged,
}: {
  missions: Missions;
  onChanged: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mission = missions.active[0] ?? missions.candidates[0];
  if (!mission) return null;
  const activate = async () => {
    setBusy(true);
    setError(null);
    try {
      await narrativeApi.activate(mission.id, new AbortController().signal);
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <aside className="mission field-mission">
      <div className="eyebrow">
        {mission.status === "active"
          ? "Your field mission"
          : "A request from ECHO-0"}
      </div>
      <h2>{mission.title}</h2>
      <p>{mission.wording.text}</p>
      <details>
        <summary>Objective and why it matters</summary>
        <p>{mission.objective}</p>
        <p className="caption">{mission.reason}</p>
        <p className="caption">Completion: {mission.completion.description}</p>
        <p className="caption">{mission.safe_fallback}</p>
        <p className="caption">{mission.safety}</p>
      </details>
      {mission.progress && (
        <p className="caption">
          {mission.progress.current} / {mission.progress.target} · evaluated by
          the laboratory
        </p>
      )}
      {mission.status === "available" && (
        <button
          className="btn small"
          disabled={busy || missions.active.length >= missions.max_active}
          onClick={() => void activate()}
        >
          {busy ? "Accepting…" : "Accept mission"}
        </button>
      )}
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
    </aside>
  );
}
