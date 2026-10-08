import { useCallback, useEffect, useReducer, useRef } from 'react';
import { ApiError, api, waitUntilProcessed } from '../api/client';
import { Recorder, hasGetUserMedia, isSecureForMic } from '../audio/recorder';
import { canStart, canStop, canSubmit, initialState, isBusy, reducer } from '../state/recordingMachine';
import { Echo, type EchoEvent } from './Echo';

export interface Limits {
  min_duration_s: number;
  max_duration_s: number;
}

interface Props {
  limits: Limits;
  onProcessed: (recordingId: string) => void;
  onArchiveChanged: () => void;
}

function fmt(ms: number): string {
  const s = Math.floor(ms / 1000);
  const t = Math.floor((ms % 1000) / 100);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}.${t}`;
}

export function RecordingPanel({ limits, onProcessed, onArchiveChanged }: Props) {
  const [s, dispatch] = useReducer(reducer, initialState);
  const recorder = useRef<Recorder | null>(null);
  const previewUrl = useRef<string | null>(null);
  const blobRef = useRef<{ blob: Blob; filename: string; meta: Record<string, unknown> } | null>(null);
  const secure = isSecureForMic();
  const supported = hasGetUserMedia();

  useEffect(() => {
    if (s.phase !== 'recording') return;
    const id = window.setInterval(() => dispatch({ type: 'TICK', now: performance.now() }), 100);
    return () => window.clearInterval(id);
  }, [s.phase]);

  useEffect(() => () => {
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
  }, []);

  const stop = useCallback(async () => {
    const r = recorder.current;
    if (!r) return;
    try {
      const res = await r.stop();
      if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
      previewUrl.current = URL.createObjectURL(res.blob);
      blobRef.current = {
        blob: res.blob,
        filename: res.filename,
        meta: {
          user_agent: navigator.userAgent,
          capture_method: res.method,
          mime_type: res.mimeType,
          client_sample_rate: res.sampleRate,
          constraints_honored: res.constraintsHonored,
        },
      };
      dispatch({ type: 'STOPPED', preview: { url: previewUrl.current, durationMs: res.durationMs, method: res.method, mimeType: res.mimeType, sizeBytes: res.blob.size } });
    } catch (e) {
      dispatch({ type: 'CANCEL' });
      dispatch({ type: 'FAIL', code: 'CAPTURE_FAILED', message: String(e) });
    }
  }, []);

  const start = useCallback(async () => {
    if (!supported) {
      dispatch({ type: 'PERMISSION_UNAVAILABLE', message: 'This browser does not expose a microphone API.' });
      return;
    }
    if (!secure) {
      dispatch({ type: 'PERMISSION_UNAVAILABLE', message: 'Microphone access needs a secure context (https:// or localhost). See docs/local-https.md.' });
      return;
    }
    const r = new Recorder({ maxMs: limits.max_duration_s * 1000 });
    recorder.current = r;
    r.onLevel = (p) => dispatch({ type: 'LEVEL', level: p.level, peak: p.peak });
    r.onAutoStop = () => void stop();
    dispatch({ type: 'REQUEST_PERMISSION' });
    try {
      await r.requestPermission();
      dispatch({ type: 'PERMISSION_GRANTED' });
    } catch (e) {
      const err = e as DOMException;
      const msg = err?.name === 'NotAllowedError' ? 'Microphone permission was denied.' : err?.name === 'NotFoundError' ? 'No microphone was found.' : `Microphone error: ${err?.message ?? err}`;
      dispatch({ type: 'PERMISSION_DENIED', message: msg });
      return;
    }
    try {
      dispatch({ type: 'START', now: performance.now() });
      await r.start();
    } catch (e) {
      await r.cancel();
      dispatch({ type: 'CANCEL' });
      dispatch({ type: 'FAIL', code: 'CAPTURE_FAILED', message: String(e) });
    }
  }, [limits.max_duration_s, secure, stop, supported]);

  const discard = useCallback(() => {
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = null;
    blobRef.current = null;
    dispatch({ type: 'DISCARD' });
  }, []);

  const submit = useCallback(async () => {
    const b = blobRef.current;
    if (!b) return;
    dispatch({ type: 'SUBMIT' });
    try {
      const acc = await api.upload(b.blob, b.filename, b.meta);
      dispatch({ type: 'UPLOADED', recordingId: acc.recording_id });
      onArchiveChanged();
      const d = await waitUntilProcessed(acc.recording_id);
      onArchiveChanged();
      if (d.status === 'failed') {
        dispatch({ type: 'FAIL', code: 'PROCESSING_FAILED', message: d.error?.message ?? 'processing failed' });
        return;
      }
      dispatch({ type: 'PROCESSED', recordingId: d.id });
      onProcessed(d.id);
      blobRef.current = null;
    } catch (e) {
      if (e instanceof ApiError) {
        if (e.code === 'DUPLICATE_RECORDING' && typeof e.problem.recording_id === 'string') {
          dispatch({ type: 'FAIL', code: e.code, message: 'This exact signal is already in the archive.' });
          onProcessed(e.problem.recording_id);
          return;
        }
        dispatch({ type: 'FAIL', code: e.code, message: e.message });
      } else {
        dispatch({ type: 'FAIL', code: 'UNKNOWN', message: String(e) });
      }
    }
  }, [onArchiveChanged, onProcessed]);

  const echo: EchoEvent =
    s.phase === 'recording' ? 'recording'
    : s.phase === 'recorded' ? 'recorded'
    : s.phase === 'uploading' ? 'uploading'
    : s.phase === 'processing' ? 'processing'
    : s.phase === 'done' ? 'preserved'
    : s.phase === 'error' && s.error?.code === 'PROCESSING_FAILED' ? 'failed'
    : s.phase === 'error' && (s.error?.code === 'MIC_DENIED' || s.error?.code === 'MIC_UNAVAILABLE') ? 'denied'
    : s.phase === 'error' && s.error?.code === 'NETWORK' ? 'offline'
    : s.phase === 'armed' ? 'armed'
    : 'idle';

  const minMs = limits.min_duration_s * 1000;
  const tooShort = (s.phase === 'recorded' || s.phase === 'error') && !!s.preview && s.preview.durationMs < minMs;
  const recording = s.phase === 'recording';

  return (
    <section className="panel" aria-labelledby="rec-h">
      <h2 id="rec-h">Capture</h2>
      <Echo event={echo} />

      <div className="rec-main">
        <div className={`rec-indicator ${recording ? 'live' : ''}`} aria-live="polite">
          <span className="dot" aria-hidden="true" />
          {recording ? 'Recording' : s.phase === 'armed' ? 'Microphone open' : s.phase === 'requesting' ? 'Requesting microphone' : s.phase === 'recorded' ? 'Captured' : isBusy(s) ? s.phase : 'Standby'}
        </div>
        <div className={`rec-timer ${recording ? 'live' : ''}`} aria-label="recording timer">{fmt(s.elapsedMs)}</div>
        <div className="meter" aria-hidden="true"><i style={{ width: `${Math.min(100, s.level * 300)}%` }} /></div>

        {recording ? (
          <button className="btn-record stop" onClick={() => void stop()} disabled={!canStop(s)} aria-label="stop recording">
            <span className="glyph" aria-hidden="true" />Stop
          </button>
        ) : (
          <button className="btn-record" onClick={() => void start()} disabled={!canStart(s) || isBusy(s) || s.phase === 'recorded'} aria-label="start recording">
            <span className="glyph" aria-hidden="true" />Record
          </button>
        )}

        <div className="status-line">
          {recording && <>auto-stops at <strong>{limits.max_duration_s} s</strong></>}
          {s.phase === 'idle' && <>min {limits.min_duration_s} s · max {limits.max_duration_s} s · stays on this machine</>}
          {s.phase === 'armed' && <>permission: <strong>granted</strong></>}
          {s.phase === 'uploading' && <>uploading…</>}
          {s.phase === 'processing' && <>decoding and measuring… <code>{s.recordingId?.slice(0, 8)}</code></>}
          {s.phase === 'done' && <>preserved as <code>{s.recordingId?.slice(0, 8)}</code></>}
          {s.phase === 'error' && s.preview && !tooShort && <>the captured signal is kept; fix the problem and submit again</>}
          {tooShort && <>too short: <strong>{(s.preview!.durationMs / 1000).toFixed(1)} s</strong> &lt; {limits.min_duration_s} s minimum</>}
          {s.phase === 'recorded' && !tooShort && s.preview && (
            <>{(s.preview.durationMs / 1000).toFixed(1)} s · {s.preview.method === 'audioworklet-wav' ? 'PCM WAV' : s.preview.mimeType} · {(s.preview.sizeBytes / 1024).toFixed(0)} KiB · peak {s.peak.toFixed(2)}</>
          )}
        </div>
      </div>

      {(s.phase === 'recorded' || s.phase === 'error') && s.preview && (
        <div className="preview">
          <audio controls src={s.preview.url} aria-label="recording preview" />
          <div className="row center" style={{ marginTop: 10 }}>
            <button className="btn primary" onClick={() => void submit()} disabled={!canSubmit(s, minMs)}>Submit for analysis</button>
            <button className="btn" onClick={discard}>Discard</button>
          </div>
        </div>
      )}

      {s.phase === 'error' && s.error && (
        <div className="error" role="alert">
          <span><code>{s.error.code}</code> {s.error.message}</span>
          <button className="btn small" onClick={() => dispatch({ type: 'CLEAR_ERROR' })}>Clear</button>
        </div>
      )}
      {s.phase === 'done' && (
        <div className="row center" style={{ marginTop: 10 }}>
          <button className="btn" onClick={() => dispatch({ type: 'RESET' })}>Record another</button>
        </div>
      )}
    </section>
  );
}
