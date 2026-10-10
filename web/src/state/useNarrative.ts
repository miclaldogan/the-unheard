import { useCallback, useEffect, useState } from "react";
import {
  narrativeApi,
  type NarrativeAdapter,
  type NarrativeSnapshot,
} from "../api/narrative";
export function useNarrative(
  version: number,
  adapter: NarrativeAdapter = narrativeApi,
) {
  const [snapshot, setSnapshot] = useState<NarrativeSnapshot | null>(null);
  const [status, setStatus] = useState<
    "loading" | "ready" | "unavailable" | "error"
  >("loading");
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const reload = useCallback(() => setRevision((v) => v + 1), []);
  useEffect(() => {
    const controller = new AbortController();
    let timer: number;
    let previous: NarrativeSnapshot | null = null;
    const read = async () => {
      if (document.visibilityState === "hidden") {
        timer = window.setTimeout(read, 8000);
        return;
      }
      try {
        const s = await adapter.read(controller.signal);
        if (controller.signal.aborted) return;
        previous = s;
        setSnapshot(s);
        setStatus(s ? "ready" : "unavailable");
        setError(null);
      } catch (e) {
        if (controller.signal.aborted) return;
        setSnapshot(null);
        setStatus("error");
        setError(e instanceof Error ? e.message : String(e));
      }
      timer = window.setTimeout(
        read,
        previous?.current.utterance.generation.status === "pending"
          ? 1500
          : 8000,
      );
    };
    void read();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [adapter, version, revision]);
  return { snapshot, status, error, reload };
}
