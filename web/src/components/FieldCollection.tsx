import { useEffect, useState, useRef } from "react";
import {
  browserCaptureStore as store,
  CAPTURE_CHANGED,
  CAPTURE_LIMIT_BYTES,
  type LocalCapture,
} from "../platform/captureStore";
import { uploadCapture } from "../platform/uploadQueue";
function LocalAudio({ item }: { item: LocalCapture }) {
  const original = useRef(item.blob);
  const [url, setUrl] = useState("");
  useEffect(() => {
    const u = URL.createObjectURL(original.current);
    setUrl(u);
    return () => URL.revokeObjectURL(u);
  }, []);
  return (
    <>
      <audio
        controls
        preload="none"
        src={url}
        aria-label={`local playback ${item.id}`}
      />
      <a className="btn small" href={url} download={item.filename}>
        Download original
      </a>
    </>
  );
}
export function FieldCollection({
  onUploaded,
}: {
  onUploaded: (id: string) => void;
}) {
  const [items, setItems] = useState<LocalCapture[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    const load = () => {
      void store
        .list()
        .then((s) => {
          setItems(s.sort((a, b) => b.capturedAt.localeCompare(a.capturedAt)));
          setError(null);
        })
        .catch((e) => setError(String(e)));
    };
    load();
    window.addEventListener(CAPTURE_CHANGED, load);
    return () => {
      window.removeEventListener(CAPTURE_CHANGED, load);
    };
  }, []);
  const upload = async (id: string) => {
    setBusy(id);
    try {
      onUploaded(await uploadCapture(id));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };
  const remove = async (id: string) => {
    try {
      if (navigator.locks)
        await navigator.locks.request(`unheard-upload-${id}`, () =>
          store.remove(id),
        );
      else await store.remove(id);
    } catch (e) {
      setError(String(e));
    }
  };
  const label = async (item: LocalCapture, value: string) => {
    try {
      const save = async () => {
        const current = (await store.list()).find((c) => c.id === item.id);
        if (current) await store.put({ ...current, label: value });
      };
      if (navigator.locks)
        await navigator.locks.request(`unheard-upload-${item.id}`, save);
      else await save();
    } catch (e) {
      setError(String(e));
    }
  };
  const bytes = items.reduce((n, c) => n + c.blob.size, 0);
  return (
    <section
      className="field-collection panel"
      aria-labelledby="field-collection-title"
    >
      <div className="collection-heading">
        <h2 id="field-collection-title">Field notebook</h2>
        <span className="chip">{items.length} recordings</span>
      </div>
      <p className="caption">
        {(bytes / 1024 / 1024).toFixed(1)} / {CAPTURE_LIMIT_BYTES / 1024 / 1024}{" "}
        MiB · {items.filter((c) => c.uploadRequested && !c.serverId).length}{" "}
        pending uploads. Local copies remain until you delete them.
      </p>
      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {!items.length && (
        <p className="empty">
          Your discoveries will rest here, even when the laboratory is out of
          reach.
        </p>
      )}
      <ul className="local-captures">
        {items.map((c) => (
          <li key={c.id}>
            <div className="row">
              <strong>{c.label || "An unnamed discovery"}</strong>
              <span className="chip">
                {c.serverId
                  ? "Synchronized · analysis on server"
                  : c.autoRetry === false
                    ? "Upload needs attention"
                    : c.uploadRequested
                      ? "Pending upload"
                      : "Saved on this device"}
              </span>
            </div>
            <p className="caption">
              {new Date(c.capturedAt).toLocaleString()} ·{" "}
              {(c.durationMs / 1000).toFixed(1)} s · {c.id.slice(0, 8)}
            </p>
            <label className="field-label">
              A note for later
              <input
                className="input"
                defaultValue={c.label}
                maxLength={80}
                onBlur={(e) => void label(c, e.target.value)}
                aria-label={`quick label ${c.id}`}
                disabled={!!busy}
              />
            </label>
            <LocalAudio item={c} />
            {c.error && (
              <p className="caption">
                Upload could not complete: {c.error}. Your original is still
                here.
              </p>
            )}
            <div className="row">
              {c.serverId ? (
                <button
                  className="btn small teal"
                  onClick={() => onUploaded(c.serverId!)}
                >
                  Open in laboratory
                </button>
              ) : (
                <button
                  className="btn small primary"
                  disabled={!!busy}
                  onClick={() => void upload(c.id)}
                >
                  {busy === c.id
                    ? "Uploading…"
                    : c.uploadRequested
                      ? "Retry upload"
                      : "Upload to laboratory"}
                </button>
              )}
              <button
                className="btn small danger"
                disabled={!!busy}
                onClick={() => void remove(c.id)}
              >
                Delete local copy
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
