import { ApiError, api } from "../api/client";
import {
  browserCaptureStore,
  type CaptureStore,
  type LocalCapture,
} from "./captureStore";
const active = new Map<string, Promise<string>>();
/** Acknowledge once, retain local bytes, and reuse server ID for subsequent retries.
 * Lost responses recover through the existing backend's canonical-PCM duplicate 409. */
export function uploadCapture(
  id: string,
  store: CaptureStore = browserCaptureStore,
): Promise<string> {
  const current = active.get(id);
  if (current) return current;
  const run = async () => {
    const item = (await store.list()).find((c) => c.id === id);
    if (!item) throw new Error("Local recording no longer exists.");
    if (item.serverId) return item.serverId;
    const queued: LocalCapture = {
      ...item,
      uploadRequested: true,
      error: null,
      attempts: (item.attempts ?? 0) + 1,
    };
    await store.put(queued);
    const timeout = AbortSignal.timeout(60000);
    try {
      const result = await api.upload(
        item.blob,
        item.filename,
        { ...item.meta, local_recording_id: item.id, field_label: item.label },
        item.capturedAt,
        timeout,
      );
      await store.put({ ...queued, serverId: result.recording_id });
      return result.recording_id;
    } catch (e) {
      if (
        e instanceof ApiError &&
        e.code === "DUPLICATE_RECORDING" &&
        typeof e.problem.recording_id === "string"
      ) {
        await store.put({ ...queued, serverId: e.problem.recording_id });
        return e.problem.recording_id;
      }
      const retryable =
        e instanceof ApiError &&
        (e.status === 0 ||
          e.status === 408 ||
          e.status === 429 ||
          e.status >= 500);
      await store.put({
        ...queued,
        error: e instanceof Error ? e.message : String(e),
        autoRetry: retryable && (queued.attempts ?? 0) < 5,
        nextAttemptAt:
          Date.now() +
          Math.min(300000, 15000 * 2 ** ((queued.attempts ?? 1) - 1)),
      });
      throw e;
    }
  };
  const locked = async (): Promise<string> =>
    navigator.locks
      ? navigator.locks.request(`unheard-upload-${id}`, run)
      : run();
  const promise = locked().finally(() => active.delete(id));
  active.set(id, promise);
  return promise;
}
/** Foreground only. User requests upload first. Never loops on permanently rejected audio. */
export async function retryPending(
  store: CaptureStore = browserCaptureStore,
): Promise<void> {
  for (const c of await store.list())
    if (
      c.uploadRequested &&
      !c.serverId &&
      c.autoRetry !== false &&
      (c.nextAttemptAt ?? 0) <= Date.now()
    ) {
      try {
        await uploadCapture(c.id, store);
      } catch {
        /* durable error is shown in the collection */
      }
    }
}
