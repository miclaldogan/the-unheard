import { useCallback, useEffect, useState } from "react";
import {
  narrativeApi,
  type NarrativeAdapter,
  type NarrativeSnapshot,
} from "../api/narrative";
export function useNarrative(
  version: number | string,
  adapter: NarrativeAdapter = narrativeApi,
) {
  const [result, setResult] = useState<{
    snapshot: NarrativeSnapshot | null;
    version: number | string;
    revision: number;
  } | null>(null);
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
        setResult({ snapshot: s, version, revision });
        setStatus(s ? "ready" : "unavailable");
        setError(null);
      } catch (e) {
        if (controller.signal.aborted) return;
        setResult({ snapshot: null, version, revision });
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
  const current = result?.version === version && result?.revision === revision;
  return {
    snapshot: current ? result.snapshot : null,
    status: current ? status : ("loading" as const),
    error: current ? error : null,
    reload,
  };
}
