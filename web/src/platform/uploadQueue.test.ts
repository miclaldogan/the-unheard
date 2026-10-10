import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import {
  saveCapture,
  type CaptureStore,
  type LocalCapture,
} from "./captureStore";
import { retryPending, uploadCapture } from "./uploadQueue";
function memoryStore(): CaptureStore {
  const items = new Map<string, LocalCapture>();
  return {
    list: async () => [...items.values()],
    put: async (c) => {
      items.set(c.id, c);
    },
    remove: async (id) => {
      items.delete(id);
    },
  };
}
const input = () => ({
  blob: new Blob(["real bytes"]),
  filename: "field.wav",
  meta: { capture_method: "test" },
  durationMs: 4000,
});
afterEach(() => vi.restoreAllMocks());
describe("durable capture queue", () => {
  it("keeps stable identity and bytes when upload fails, then resumes without changing capture time", async () => {
    const store = memoryStore();
    const c = await saveCapture(input(), store);
    const upload = vi
      .spyOn(api, "upload")
      .mockRejectedValueOnce(
        new ApiError({
          type: "network",
          title: "offline",
          status: 0,
          code: "NETWORK",
          detail: "offline",
        }),
      )
      .mockResolvedValue({ recording_id: "server" } as Awaited<
        ReturnType<typeof api.upload>
      >);
    await expect(uploadCapture(c.id, store)).rejects.toThrow("offline");
    expect((await store.list())[0]).toMatchObject({
      id: c.id,
      blob: c.blob,
      uploadRequested: true,
      serverId: null,
      autoRetry: true,
    });
    expect(await uploadCapture(c.id, store)).toBe("server");
    expect(upload.mock.calls[1][3]).toBe(c.capturedAt);
    expect((await store.list())[0].blob).toBe(c.blob);
    await uploadCapture(c.id, store);
    expect(upload).toHaveBeenCalledTimes(2);
  });
  it("coalesces simultaneous uploads and treats the backend duplicate acknowledgement as success", async () => {
    const store = memoryStore();
    const c = await saveCapture(input(), store);
    const upload = vi.spyOn(api, "upload").mockRejectedValue(
      new ApiError({
        type: "duplicate",
        title: "duplicate",
        status: 409,
        code: "DUPLICATE_RECORDING",
        detail: "exists",
        recording_id: "existing",
      }),
    );
    expect(
      await Promise.all([
        uploadCapture(c.id, store),
        uploadCapture(c.id, store),
      ]),
    ).toEqual(["existing", "existing"]);
    expect(upload).toHaveBeenCalledTimes(1);
    expect((await store.list())[0].serverId).toBe("existing");
  });
  it("never auto-uploads unrequested captures or loops on permanent rejection", async () => {
    const store = memoryStore();
    const c = await saveCapture(input(), store);
    const upload = vi.spyOn(api, "upload").mockRejectedValue(
      new ApiError({
        type: "validation",
        title: "short",
        status: 422,
        code: "AUDIO_TOO_SHORT",
        detail: "too short",
      }),
    );
    await retryPending(store);
    expect(upload).not.toHaveBeenCalled();
    await expect(uploadCapture(c.id, store)).rejects.toThrow("too short");
    await retryPending(store);
    expect(upload).toHaveBeenCalledTimes(1);
    expect((await store.list())[0]).toMatchObject({
      autoRetry: false,
      blob: c.blob,
    });
  });
  it("deleting a local item prevents a later manual retry", async () => {
    const store = memoryStore();
    const c = await saveCapture(input(), store);
    await store.remove(c.id);
    const upload = vi.spyOn(api, "upload");
    await expect(uploadCapture(c.id, store)).rejects.toThrow(
      "no longer exists",
    );
    expect(upload).not.toHaveBeenCalled();
  });
});
