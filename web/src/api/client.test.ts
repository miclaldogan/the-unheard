import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api, waitUntilProcessed } from './client';

function jsonResponse(body: unknown, status = 200, contentType = 'application/json'): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': contentType } });
}

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});

describe('api client', () => {
  it('parses problem+json into ApiError with the stable code', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      jsonResponse({ type: 'urn:x', title: 'Audio Too Short', status: 422, detail: 'too short', code: 'AUDIO_TOO_SHORT' }, 422, 'application/problem+json'),
    );
    await expect(api.get('abc')).rejects.toMatchObject({ code: 'AUDIO_TOO_SHORT', status: 422 });
  });

  it('wraps network failures as NETWORK', async () => {
    vi.spyOn(globalThis, 'fetch').mockRejectedValue(new TypeError('Failed to fetch'));
    const err = await api.list().catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('NETWORK');
  });

  it('sends multipart upload with captured_at and device_info', async () => {
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ recording_id: 'r1', status: 'uploaded', duration_s: 4, quality: {}, links: {} }, 202));
    const res = await api.upload(new Blob([new Uint8Array(10)], { type: 'audio/wav' }), 'a.wav', { ua: 'test' });
    expect(res.recording_id).toBe('r1');
    const [url, init] = spy.mock.calls[0];
    expect(url).toBe('/api/recordings');
    const form = (init as RequestInit).body as FormData;
    expect(form.get('file')).toBeInstanceOf(Blob);
    expect(JSON.parse(form.get('device_info') as string)).toEqual({ ua: 'test' });
    expect(form.get('captured_at')).toMatch(/^\d{4}-/);
  });

  it('adds a bearer token when one is stored', async () => {
    localStorage.setItem('unheard.token', 'tok');
    const spy = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ items: [], total: 0, limit: 100, offset: 0 }));
    await api.list();
    const headers = (spy.mock.calls[0][1] as RequestInit).headers as Headers;
    expect(headers.get('Authorization')).toBe('Bearer tok');
  });

  it('polls until the recording is ready', async () => {
    const seq = [{ id: 'r', status: 'uploaded' }, { id: 'r', status: 'processing' }, { id: 'r', status: 'ready' }];
    let i = 0;
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => jsonResponse(seq[Math.min(i++, seq.length - 1)]));
    const d = await waitUntilProcessed('r', { intervalMs: 1 });
    expect(d.status).toBe('ready');
    expect(i).toBe(3);
  });
});
