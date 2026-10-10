import { useCallback, useEffect, useState } from "react";
import { ApiError, api, waitForPrediction } from "../api/client";
import type {
  AnnotationResult,
  EchoLine,
  Neighbour,
  Prediction,
} from "../api/types";
import { EchoLog } from "./EchoLog";
import { PredictionPanel } from "./PredictionPanel";
import { TeachPanel } from "./TeachPanel";

interface Props {
  recordingId: string | null;
  onMemoryChanged: () => void;
  onNeighbours: (n: Neighbour[]) => void;
}

/** Owns the prediction/echo state for the selected recording and hosts Hearing + Teach. */
export function HearingPanel({
  recordingId,
  onMemoryChanged,
  onNeighbours,
}: Props) {
  const [prediction, setPrediction] = useState<Prediction | null>(null);
  const [echo, setEcho] = useState<EchoLine[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [formation, setFormation] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(
    async (id: string, wait: boolean) => {
      try {
        const p = wait ? await waitForPrediction(id) : await api.prediction(id);
        setPrediction(p);
        const [lines, nb] = await Promise.all([
          api.echo(id),
          api.neighbours(id).catch(() => [] as Neighbour[]),
        ]);
        setEcho(lines);
        onNeighbours(nb);
        setError(null);
      } catch (e) {
        setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
      }
    },
    [onNeighbours],
  );

  useEffect(() => {
    setPrediction(null);
    setFormation(null);
    setEcho([]);
    setError(null);
    if (!recordingId) {
      onNeighbours([]);
      return;
    }
    let cancelled = false;
    (async () => {
      const p = await api.prediction(recordingId).catch((e) => {
        setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
        return null;
      });
      if (cancelled || !p) return;
      setPrediction(p);
      if (p.state === "analyzing") await load(recordingId, true);
      else await load(recordingId, false);
    })();
    return () => {
      cancelled = true;
    };
  }, [recordingId, load, onNeighbours]);

  const infer = async () => {
    if (!recordingId) return;
    setBusy(true);
    try {
      await api.infer(recordingId);
      await load(recordingId, true);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e));
    } finally {
      setBusy(false);
    }
  };

  const onSaved = async (res: AnnotationResult) => {
    setFormation(res.memory_version);
    if (recordingId) await load(recordingId, false);
    onMemoryChanged();
  };

  if (!recordingId) return null;
  return (
    <>
      {formation !== null && (
        <div key={formation} className="memory-formation" role="status">
          A memory has taken shape. Your interpretation was saved · memory
          revision {formation}.
        </div>
      )}
      {error && (
        <div className="error" role="alert">
          <span>{error}</span>
          <button className="btn small" onClick={() => setError(null)}>
            Clear
          </button>
        </div>
      )}
      <EchoLog
        lines={echo}
        fallback={
          prediction?.state === "analyzing"
            ? "Listening with my ears."
            : undefined
        }
      />
      <PredictionPanel
        prediction={prediction}
        onInfer={() => void infer()}
        busy={busy}
      />
      {prediction &&
        prediction.state !== "analyzing" &&
        prediction.state !== "not_run" && (
          <TeachPanel
            key={`${prediction.recording_id}-${prediction.annotation?.id ?? "none"}`}
            prediction={prediction}
            onSaved={(r) => void onSaved(r)}
          />
        )}
    </>
  );
}
