import type { EchoLine } from '../api/types';

/** ECHO-0 lines returned by the server; every line is derived from persisted events. */
export function EchoLog({ lines, fallback }: { lines: EchoLine[]; fallback?: string }) {
  if (!lines.length) {
    return fallback ? (
      <p className="echo" role="status"><span className="tag">ECHO-0</span>{fallback}</p>
    ) : null;
  }
  return (
    <div className="echo-log" aria-label="ECHO-0 log">
      {lines.map((l, i) => (
        <p className="echo" key={`${l.template}-${i}`} role={i === lines.length - 1 ? 'status' : undefined}>
          <span className="tag">ECHO-0</span>
          {l.text}
          <span className="prov">{l.tags.join(' · ')}</span>
        </p>
      ))}
    </div>
  );
}
