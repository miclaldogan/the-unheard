import { useState, type ReactNode } from "react";
import { getToken } from "../api/client";
export function ProtectedDownload({
  href,
  filename,
  children,
}: {
  href: string;
  filename: string;
  children: ReactNode;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const download = async (e: React.MouseEvent<HTMLAnchorElement>) => {
    const token = getToken();
    if (!token) return;
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await fetch(href, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!response.ok)
        throw new Error(`Export unavailable (${response.status}).`);
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };
  return (
    <>
      <a
        className="btn small"
        href={href}
        download={filename}
        aria-disabled={busy}
        onClick={(e) => {
          if (busy) e.preventDefault();
          else void download(e);
        }}
      >
        {busy ? "Exporting…" : children}
      </a>
      {error && (
        <span role="alert" className="caption">
          {error}
        </span>
      )}
    </>
  );
}
