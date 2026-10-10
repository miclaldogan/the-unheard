/** Durable browser adapter. Native implementations can implement CaptureStore unchanged. */
export interface LocalCapture {
  id: string;
  blob: Blob;
  filename: string;
  meta: Record<string, unknown>;
  capturedAt: string;
  durationMs: number;
  label: string;
  uploadRequested: boolean;
  attempts?: number;
  nextAttemptAt?: number;
  autoRetry?: boolean;
  serverId: string | null;
  error: string | null;
}
export interface CaptureStore {
  list(): Promise<LocalCapture[]>;
  put(item: LocalCapture): Promise<void>;
  remove(id: string): Promise<void>;
}
export const CAPTURE_LIMIT_BYTES = 64 * 1024 * 1024;
export const CAPTURE_LIMIT_COUNT = 100;
export const CAPTURE_CHANGED = "unheard:capture-changed";
const changed = () => window.dispatchEvent(new Event(CAPTURE_CHANGED));
let opening: Promise<IDBDatabase> | null = null;
function open(): Promise<IDBDatabase> {
  if (!opening)
    opening = new Promise<IDBDatabase>((resolve, reject) => {
      if (!globalThis.indexedDB) {
        reject(
          new Error(
            "Local storage is unavailable. Keep this page open and download your recording.",
          ),
        );
        return;
      }
      const request = indexedDB.open("unheard-field", 1);
      request.onupgradeneeded = () =>
        request.result.createObjectStore("captures", { keyPath: "id" });
      request.onsuccess = () => {
        const db = request.result;
        db.onversionchange = () => {
          db.close();
          opening = null;
        };
        resolve(db);
      };
      request.onerror = () => reject(request.error);
      request.onblocked = () =>
        reject(new Error("Close other UNHEARD tabs to open local storage."));
    }).catch((e) => {
      opening = null;
      throw e;
    });
  return opening;
}
async function transaction<T>(
  mode: IDBTransactionMode,
  run: (store: IDBObjectStore) => IDBRequest<T>,
): Promise<T> {
  const db = await open();
  return new Promise((resolve, reject) => {
    const tx = db.transaction("captures", mode);
    const request = run(tx.objectStore("captures"));
    tx.oncomplete = () => resolve(request.result);
    tx.onerror = () => reject(tx.error ?? request.error);
    tx.onabort = () => reject(tx.error ?? new Error("Local save interrupted."));
  });
}
export const browserCaptureStore: CaptureStore = {
  list: () => transaction("readonly", (s) => s.getAll()),
  put: async (item) => {
    // Quota check and write share a transaction so simultaneous tabs cannot exceed the bound.
    const db = await open();
    await new Promise<void>((resolve, reject) => {
      const tx = db.transaction("captures", "readwrite");
      const store = tx.objectStore("captures");
      const all = store.getAll();
      let error: Error | null = null;
      all.onsuccess = () => {
        const others = (all.result as LocalCapture[]).filter(
          (c) => c.id !== item.id,
        );
        if (
          others.length >= CAPTURE_LIMIT_COUNT ||
          others.reduce((n, c) => n + c.blob.size, item.blob.size) >
            CAPTURE_LIMIT_BYTES
        ) {
          error = new Error(
            "Field storage is full (64 MiB / 100 recordings). Download or delete a local copy before saving.",
          );
          tx.abort();
        } else store.put(item);
      };
      tx.oncomplete = () => resolve();
      tx.onerror = tx.onabort = () =>
        reject(
          error ??
            tx.error ??
            new Error("Local save failed. Check available device storage."),
        );
    });
    changed();
  },
  remove: async (id) => {
    await transaction("readwrite", (s) => s.delete(id));
    changed();
  },
};
export async function saveCapture(
  input: Pick<LocalCapture, "blob" | "filename" | "meta" | "durationMs">,
  store: CaptureStore = browserCaptureStore,
): Promise<LocalCapture> {
  const item: LocalCapture = {
    ...input,
    id: crypto.randomUUID(),
    capturedAt: new Date().toISOString(),
    label: "",
    uploadRequested: false,
    serverId: null,
    error: null,
  };
  await store.put(item);
  return item;
}
