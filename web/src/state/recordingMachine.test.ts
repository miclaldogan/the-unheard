import { describe, expect, it } from 'vitest';
import { canStart, canStop, canSubmit, initialState, reducer, type Action, type RecordingState } from './recordingMachine';

const preview = { url: 'blob:x', durationMs: 4000, method: 'audioworklet-wav', mimeType: 'audio/wav', sizeBytes: 100 };

function run(actions: Action[], from: RecordingState = initialState): RecordingState {
  return actions.reduce(reducer, from);
}

describe('recording state machine', () => {
  it('walks the happy path', () => {
    let s = run([{ type: 'REQUEST_PERMISSION' }, { type: 'PERMISSION_GRANTED' }]);
    expect(s.phase).toBe('armed');
    s = run([{ type: 'START', now: 1000 }, { type: 'TICK', now: 2500 }, { type: 'LEVEL', level: 0.2, peak: 0.6 }], s);
    expect(s.phase).toBe('recording');
    expect(s.elapsedMs).toBe(1500);
    expect(s.peak).toBe(0.6);
    s = run([{ type: 'STOPPED', preview }], s);
    expect(s.phase).toBe('recorded');
    expect(canSubmit(s, 3000)).toBe(true);
    s = run([{ type: 'SUBMIT' }, { type: 'UPLOADED', recordingId: 'r1' }, { type: 'PROCESSED', recordingId: 'r1' }], s);
    expect(s.phase).toBe('done');
    expect(s.recordingId).toBe('r1');
    expect(s.preview).toBeNull();
  });

  it('never allows start and stop at the same time', () => {
    const phases: RecordingState['phase'][] = ['idle', 'requesting', 'armed', 'recording', 'recorded', 'uploading', 'processing', 'done', 'error'];
    for (const phase of phases) {
      const s = { ...initialState, phase };
      expect(canStart(s) && canStop(s)).toBe(false);
    }
  });

  it('ignores STOPPED/TICK/LEVEL when not recording', () => {
    const s = run([{ type: 'STOPPED', preview }, { type: 'TICK', now: 5 }, { type: 'LEVEL', level: 1, peak: 1 }]);
    expect(s).toEqual(initialState);
  });

  it('cannot submit a too-short or missing preview', () => {
    const s = run([{ type: 'REQUEST_PERMISSION' }, { type: 'PERMISSION_GRANTED' }, { type: 'START', now: 0 }, { type: 'STOPPED', preview: { ...preview, durationMs: 1200 } }]);
    expect(canSubmit(s, 3000)).toBe(false);
    expect(reducer({ ...s, preview: null }, { type: 'SUBMIT' }).phase).toBe('recorded');
  });

  it('cannot start while uploading or processing', () => {
    const s = run([{ type: 'REQUEST_PERMISSION' }, { type: 'PERMISSION_GRANTED' }, { type: 'START', now: 0 }, { type: 'STOPPED', preview }, { type: 'SUBMIT' }]);
    expect(s.phase).toBe('uploading');
    expect(reducer(s, { type: 'START', now: 1 }).phase).toBe('uploading');
    const p = reducer(s, { type: 'UPLOADED', recordingId: 'x' });
    expect(reducer(p, { type: 'START', now: 1 }).phase).toBe('processing');
  });

  it('permission denial lands in error and clears back to idle', () => {
    let s = run([{ type: 'REQUEST_PERMISSION' }, { type: 'PERMISSION_DENIED', message: 'no' }]);
    expect(s.phase).toBe('error');
    expect(s.permission).toBe('denied');
    s = reducer(s, { type: 'CLEAR_ERROR' });
    expect(s.phase).toBe('idle');
    expect(s.error).toBeNull();
  });

  it('upload failure keeps the preview so the user can retry', () => {
    let s = run([{ type: 'REQUEST_PERMISSION' }, { type: 'PERMISSION_GRANTED' }, { type: 'START', now: 0 }, { type: 'STOPPED', preview }, { type: 'SUBMIT' }]);
    s = reducer(s, { type: 'FAIL', code: 'NETWORK', message: 'down' });
    expect(s.phase).toBe('error');
    expect(s.preview).not.toBeNull();
    expect(canSubmit(s, 3000)).toBe(true);
    expect(reducer(s, { type: 'SUBMIT' }).phase).toBe('uploading');
    s = reducer(s, { type: 'CLEAR_ERROR' });
    expect(s.phase).toBe('recorded');
    expect(canSubmit(s, 3000)).toBe(true);
  });

  it('cancel and discard return to armed', () => {
    const rec = run([{ type: 'REQUEST_PERMISSION' }, { type: 'PERMISSION_GRANTED' }, { type: 'START', now: 0 }]);
    expect(reducer(rec, { type: 'CANCEL' }).phase).toBe('armed');
    const stopped = reducer(rec, { type: 'STOPPED', preview });
    expect(reducer(stopped, { type: 'DISCARD' }).phase).toBe('armed');
    expect(reducer(stopped, { type: 'DISCARD' }).preview).toBeNull();
  });
});
