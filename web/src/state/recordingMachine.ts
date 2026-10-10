/**
 * Recording UI state machine (doc 09 "State diagram — recording", M1 subset).
 * A pure reducer so transitions are testable and contradictory states are impossible.
 *
 * idle → requesting → armed → recording → recorded → uploading → processing → done
 *                                      ↘ (cancel) idle           ↘ failed/error
 */

export type Phase = 'idle' | 'requesting' | 'armed' | 'recording' | 'recorded' | 'uploading' | 'processing' | 'done' | 'error';

export interface RecordingState {
  phase: Phase;
  permission: 'unknown' | 'granted' | 'denied' | 'unavailable';
  startedAt: number | null;
  elapsedMs: number;
  level: number;
  peak: number;
  preview: { url: string; durationMs: number; method: string; mimeType: string; sizeBytes: number } | null;
  recordingId: string | null;
  error: { code: string; message: string } | null;
}

export type Action =
  | { type: 'REQUEST_PERMISSION' }
  | { type: 'PERMISSION_GRANTED' }
  | { type: 'PERMISSION_DENIED'; message: string }
  | { type: 'PERMISSION_UNAVAILABLE'; message: string }
  | { type: 'START'; now: number }
  | { type: 'TICK'; now: number }
  | { type: 'LEVEL'; level: number; peak: number }
  | { type: 'STOPPED'; preview: NonNullable<RecordingState['preview']> }
  | { type: 'CANCEL' }
  | { type: 'DISCARD' }
  | { type: 'SUBMIT' }
  | { type: 'UPLOADED'; recordingId: string }
  | { type: 'PROCESSED'; recordingId: string }
  | { type: 'FAIL'; code: string; message: string }
  | { type: 'CLEAR_ERROR' }
  | { type: 'RESET' };

export const initialState: RecordingState = {
  phase: 'idle',
  permission: 'unknown',
  startedAt: null,
  elapsedMs: 0,
  level: 0,
  peak: 0,
  preview: null,
  recordingId: null,
  error: null,
};

export const canStart = (s: RecordingState): boolean => s.phase === 'armed' || s.phase === 'idle' || s.phase === 'done' || s.phase === 'error';
export const canStop = (s: RecordingState): boolean => s.phase === 'recording';
export const canSubmit = (s: RecordingState, minMs: number): boolean => (s.phase === 'recorded' || s.phase === 'error') && !!s.preview && s.preview.durationMs >= minMs;
export const isBusy = (s: RecordingState): boolean => s.phase === 'requesting' || s.phase === 'uploading' || s.phase === 'processing';

export function reducer(s: RecordingState, a: Action): RecordingState {
  switch (a.type) {
    case 'REQUEST_PERMISSION':
      if (s.phase !== 'idle' && s.phase !== 'error' && s.phase !== 'done') return s;
      return { ...s, phase: 'requesting', error: null };
    case 'PERMISSION_GRANTED':
      if (s.phase !== 'requesting') return s;
      return { ...s, phase: 'armed', permission: 'granted' };
    case 'PERMISSION_DENIED':
      return { ...s, phase: 'error', permission: 'denied', error: { code: 'MIC_DENIED', message: a.message } };
    case 'PERMISSION_UNAVAILABLE':
      return { ...s, phase: 'error', permission: 'unavailable', error: { code: 'MIC_UNAVAILABLE', message: a.message } };
    case 'START':
      if (!canStart(s)) return s;
      return { ...s, phase: 'recording', startedAt: a.now, elapsedMs: 0, level: 0, peak: 0, preview: null, recordingId: null, error: null };
    case 'TICK':
      if (s.phase !== 'recording' || s.startedAt === null) return s;
      return { ...s, elapsedMs: Math.max(0, a.now - s.startedAt) };
    case 'LEVEL':
      if (s.phase !== 'recording') return s;
      return { ...s, level: a.level, peak: Math.max(s.peak, a.peak) };
    case 'STOPPED':
      if (s.phase !== 'recording') return s;
      return { ...s, phase: 'recorded', preview: a.preview, elapsedMs: a.preview.durationMs, level: 0 };
    case 'CANCEL':
      if (s.phase !== 'recording') return s;
      return { ...s, phase: 'armed', startedAt: null, elapsedMs: 0, level: 0, peak: 0 };
    case 'DISCARD':
      if (s.phase !== 'recorded' && s.phase !== 'error') return s;
      return { ...s, phase: 'armed', preview: null, elapsedMs: 0, peak: 0, error: null };
    case 'SUBMIT':
      // allowed from 'recorded' and from 'error' (a failed upload keeps the preview)
      if ((s.phase !== 'recorded' && s.phase !== 'error') || !s.preview) return s;
      return { ...s, phase: 'uploading', error: null };
    case 'UPLOADED':
      if (s.phase !== 'uploading') return s;
      return { ...s, phase: 'processing', recordingId: a.recordingId };
    case 'PROCESSED':
      if (s.phase !== 'processing') return s;
      return { ...s, phase: 'done', recordingId: a.recordingId, preview: null };
    case 'FAIL':
      if (s.phase === 'recording') return s; // stop first; failure during capture is reported via STOPPED/CANCEL paths
      return { ...s, phase: 'error', error: { code: a.code, message: a.message } };
    case 'CLEAR_ERROR':
      if (s.phase !== 'error') return s;
      return { ...s, phase: s.preview ? 'recorded' : s.permission === 'granted' ? 'armed' : 'idle', error: null };
    case 'RESET':
      return { ...initialState, permission: s.permission };
    default:
      return s;
  }
}
