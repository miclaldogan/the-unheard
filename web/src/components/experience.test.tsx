import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "../App";
import { api } from "../api/client";
import { Chamber } from "./Chamber";
import { NarrativeVoice } from "./NarrativeVoice";
import type { Utterance } from "../api/narrative";
vi.mock("./Atlas", () => ({
  Atlas: ({ onOpenSpecimen }: { onOpenSpecimen: (id: string) => void }) => (
    <button onClick={() => onOpenSpecimen("real-id")}>
      Open real atlas specimen
    </button>
  ),
}));
vi.mock("./Specimen", () => ({
  Specimen: () => <div>Measured specimen view</div>,
}));
vi.mock("./Orchestra", () => ({
  Orchestra: () => <div>Persistent orchestra</div>,
}));
vi.mock("../platform/captureStore", () => ({
  browserCaptureStore: { list: async () => [] },
  CAPTURE_CHANGED: "test-change",
  CAPTURE_LIMIT_BYTES: 67108864,
}));
const callbacks = {
  onField: vi.fn(),
  onHear: vi.fn(),
  onAtlas: vi.fn(),
  onCompose: vi.fn(),
};
afterEach(() => vi.restoreAllMocks());
function backend() {
  vi.spyOn(api, "list").mockResolvedValue({
    items: [],
    total: 0,
    limit: 100,
    offset: 0,
  } as Awaited<ReturnType<typeof api.list>>);
  vi.spyOn(api, "health").mockResolvedValue({
    limits: { min_duration_s: 3, max_duration_s: 30 },
    recordings: 0,
  } as Awaited<ReturnType<typeof api.health>>);
  vi.spyOn(api, "memory").mockResolvedValue({
    labels: [],
    memory_version: 0,
    model_version_id: null,
    exemplars: 0,
    annotations: 0,
    unknown_annotations: 0,
    custom_labels: 0,
    label_names: {},
  } as Awaited<ReturnType<typeof api.memory>>);
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async () =>
      new Response(JSON.stringify({ code: "NOT_FOUND", status: 404 }), {
        status: 404,
        headers: { "content-type": "application/json" },
      }),
  );
}
describe("experience navigation", () => {
  it("opens with an intentional first-use invitation, then reaches Field and Hearing", async () => {
    backend();
    render(<App />);
    expect(
      screen.getByRole("heading", { name: /A world forgotten/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Go outside/ }));
    expect(
      screen.getByRole("heading", { name: "The world outside" }),
    ).toBeInTheDocument();
    expect(
      screen
        .getAllByLabelText("recording timer")
        .some((e) => !e.closest("[hidden]")),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Hearing" }));
    expect(
      screen.getByRole("heading", { name: "The Hearing Room" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "First, let me listen." }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByLabelText("server status")).toHaveTextContent(
        "Laboratory connected",
      ),
    );
  });
  it("selects a real atlas recording and keeps the orchestra mounted across navigation", async () => {
    backend();
    render(<App />);
    fireEvent.click(screen.getByRole("button", { name: "Orchestra" }));
    const orchestra = screen.getByText("Persistent orchestra");
    expect(orchestra).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Atlas" }));
    expect(orchestra).not.toBeVisible();
    fireEvent.click(screen.getByText("Open real atlas specimen"));
    expect(screen.getByText("Measured specimen view")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Orchestra" }));
    expect(screen.getByText("Persistent orchestra")).toBe(orchestra);
  });
  it("reports backend unavailable while Field remains accessible", async () => {
    backend();
    vi.mocked(api.list).mockRejectedValue(new Error("laptop unreachable"));
    render(<App />);
    await screen.findByText("○ Laboratory unreachable");
    fireEvent.click(screen.getByRole("button", { name: /Go outside/ }));
    expect(
      screen.getByText(/The laboratory is out of reach/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "start recording" }),
    ).toBeEnabled();
  });
});
describe("truthful Chamber states", () => {
  it("places returning recordings in the world without requiring onboarding", () => {
    render(
      <Chamber
        items={
          [{ id: "r", status: "ready" }] as Parameters<
            typeof Chamber
          >[0]["items"]
        }
        memory={null}
        connected
        snapshot={null}
        narrativeStatus="unavailable"
        {...callbacks}
      />,
    );
    expect(
      screen.getByRole("heading", { name: /The world returns/ }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByText(/Return to the hearing room/));
    expect(callbacks.onHear).toHaveBeenCalledWith("r");
  });
  it("renders untrusted narrative labels as text and distinguishes imagination", () => {
    const utterance = {
      id: "n",
      revision: 1,
      moment: { kind: "teaching" },
      lines: [
        {
          text: "<img src=x onerror=alert(1)>",
          kind: "grounded",
          provenance: ["user_confirmed"],
          cites: ["F1"],
        },
        {
          text: "A word is a shelter.",
          kind: "imagination",
          provenance: ["imagination"],
          cites: [],
        },
      ],
      facts: [
        {
          handle: "F1",
          statement: "The user supplied a name.",
          provenance: "user_confirmed",
        },
      ],
      source: "template",
      generation: { status: "fallback" },
    } as Utterance;
    const { container } = render(<NarrativeVoice utterance={utterance} />);
    expect(
      screen.getByText("<img src=x onerror=alert(1)>"),
    ).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(
      screen.getByText("Interpretation · imagination"),
    ).toBeInTheDocument();
  });
});
