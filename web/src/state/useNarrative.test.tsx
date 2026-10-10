import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useNarrative } from "./useNarrative";
import type { NarrativeAdapter, NarrativeSnapshot } from "../api/narrative";
const snapshot = (id: string) =>
  ({
    current: { utterance: { id, generation: { status: "pending" } } },
  }) as NarrativeSnapshot;
describe("authoritative narrative refresh", () => {
  it("hides old evidence immediately and ignores a late aborted read", async () => {
    let late!: (value: NarrativeSnapshot) => void;
    const adapter: NarrativeAdapter = {
      read: vi
        .fn()
        .mockResolvedValueOnce(snapshot("old"))
        .mockImplementationOnce(
          () =>
            new Promise((resolve) => {
              late = resolve;
            }),
        )
        .mockResolvedValue(snapshot("new")),
      activate: vi.fn(),
    };
    const { result, rerender, unmount } = renderHook(
      ({ version }) => useNarrative(version, adapter),
      { initialProps: { version: 0 } },
    );
    await waitFor(() =>
      expect(result.current.snapshot?.current.utterance.id).toBe("old"),
    );
    rerender({ version: 1 });
    expect(result.current.snapshot).toBeNull();
    rerender({ version: 2 });
    await waitFor(() =>
      expect(result.current.snapshot?.current.utterance.id).toBe("new"),
    );
    await act(async () => late(snapshot("deleted")));
    expect(result.current.snapshot?.current.utterance.id).toBe("new");
    unmount();
  });
  it("refreshes a pending template to a ready model line without interaction state changes", async () => {
    const adapter: NarrativeAdapter = {
      read: vi
        .fn()
        .mockResolvedValueOnce(snapshot("template"))
        .mockResolvedValue(snapshot("gemma")),
      activate: vi.fn(),
    };
    const { result, unmount } = renderHook(() => useNarrative(0, adapter));
    await waitFor(() =>
      expect(result.current.snapshot?.current.utterance.id).toBe("template"),
    );
    await act(async () => result.current.reload());
    await waitFor(() =>
      expect(result.current.snapshot?.current.utterance.id).toBe("gemma"),
    );
    unmount();
  });
});
