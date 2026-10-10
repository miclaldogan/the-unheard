import { useEffect, useState } from "react";
import { getToken } from "../api/client";
/** Audio elements cannot attach bearer headers. Keep credentials out of audio URLs. */
export function useAudioSource(path: string | null): {
  src: string | undefined;
  error: string | null;
} {
  const [source, setSource] = useState<{ path: string; src: string } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const token = getToken();
  useEffect(() => {
    setSource(null);
    setError(null);
    if (!path || !token) return;
    const abort = new AbortController();
    let url: string | null = null;
    void fetch(path, {
      signal: abort.signal,
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error(
            `Audio unavailable (${response.status}). Check the laboratory connection.`,
          );
        const blob = await response.blob();
        if (abort.signal.aborted) return;
        url = URL.createObjectURL(blob);
        setSource({ path, src: url });
      })
      .catch((e) => {
        if (!abort.signal.aborted)
          setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      abort.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [path, token]);
  return {
    src: path
      ? token
        ? source?.path === path
          ? source.src
          : undefined
        : path
      : undefined,
    error,
  };
}
