import { afterEach, describe, expect, it, vi } from "vitest";
import { narrativeApi } from "./narrative";
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
});
describe("M5 contract boundary", () => {
  it("loads the three authoritative endpoints with the existing auth and abort signal", async () => {
    localStorage.setItem("unheard.token", "test-token");
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async (url) =>
        json({ contract_version: "m5.1", path: String(url) }),
      );
    const abort = new AbortController();
    const result = await narrativeApi.read(abort.signal);
    expect(result?.state.contract_version).toBe("m5.1");
    expect(fetch).toHaveBeenCalledTimes(3);
    fetch.mock.calls.forEach(([, init]) => {
      expect(init?.signal).toBe(abort.signal);
      expect(new Headers(init?.headers).get("Authorization")).toBe(
        "Bearer test-token",
      );
    });
  });
  it("falls back on M4 without manufacturing story state", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      json({ code: "NOT_FOUND", title: "not found", status: 404 }, 404),
    );
    expect(await narrativeApi.read(new AbortController().signal)).toBeNull();
  });
  it("rejects unsupported versions and preserves real connection errors", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockImplementation(async () => json({ contract_version: "m5.2" }));
    await expect(
      narrativeApi.read(new AbortController().signal),
    ).rejects.toThrow("contract has changed");
    fetch.mockRejectedValue(new TypeError("offline"));
    await expect(
      narrativeApi.read(new AbortController().signal),
    ).rejects.toMatchObject({ code: "NETWORK" });
  });
  it("activates a mission only through the backend", async () => {
    const fetch = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(json({ id: "mission", status: "active" }, 201));
    expect(
      await narrativeApi.activate("mission", new AbortController().signal),
    ).toMatchObject({ status: "active" });
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/narrative/missions/mission/activate",
    );
    expect(fetch.mock.calls[0][1]?.method).toBe("POST");
  });
});
