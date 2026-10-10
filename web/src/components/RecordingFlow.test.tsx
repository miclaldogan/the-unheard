import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RecordingPanel } from "./RecordingPanel";
import { saveCapture } from "../platform/captureStore";
import { uploadCapture } from "../platform/uploadQueue";
const mocks = vi.hoisted(() => ({
  permission: vi.fn(),
  start: vi.fn(),
  stop: vi.fn(),
  cancel: vi.fn(),
}));
vi.mock("../audio/recorder", () => ({
  hasGetUserMedia: () => true,
  isSecureForMic: () => true,
  Recorder: class {
    onLevel = null;
    onAutoStop = null;
    requestPermission = mocks.permission;
    start = mocks.start;
    stop = mocks.stop;
    cancel = mocks.cancel;
  },
}));
vi.mock("../platform/captureStore", () => ({ saveCapture: vi.fn() }));
vi.mock("../platform/uploadQueue", () => ({ uploadCapture: vi.fn() }));
const props = {
  field: true,
  limits: { min_duration_s: 3, max_duration_s: 30 },
  onProcessed: vi.fn(),
  onArchiveChanged: vi.fn(),
};
beforeEach(() => {
  mocks.permission.mockResolvedValue({});
  mocks.start.mockResolvedValue(undefined);
  mocks.cancel.mockResolvedValue(undefined);
  mocks.stop.mockResolvedValue({
    blob: new Blob(["audio"]),
    filename: "capture.wav",
    durationMs: 4000,
    method: "audioworklet-wav",
    mimeType: "audio/wav",
    sampleRate: 48000,
    constraintsHonored: {},
  });
  vi.mocked(saveCapture).mockResolvedValue({ id: "local-id" } as Awaited<
    ReturnType<typeof saveCapture>
  >);
  Object.defineProperty(URL, "createObjectURL", {
    configurable: true,
    value: vi.fn(() => "blob:preview"),
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    configurable: true,
    value: vi.fn(),
  });
});
afterEach(() => {
  vi.clearAllMocks();
  vi.restoreAllMocks();
});
describe("Field recording workflow", () => {
  it("persists before reporting saved, keeps preview on upload failure, and preserves the copy for another capture", async () => {
    vi.mocked(uploadCapture).mockRejectedValue(new Error("laptop unavailable"));
    const active = vi.fn();
    render(<RecordingPanel {...props} onCaptureActive={active} />);
    fireEvent.click(screen.getByLabelText("start recording"));
    await screen.findByLabelText("stop recording");
    expect(active).toHaveBeenLastCalledWith(true);
    fireEvent.click(screen.getByLabelText("stop recording"));
    await screen.findByText(/Saved on this device/);
    expect(saveCapture).toHaveBeenCalledWith(
      expect.objectContaining({ durationMs: 4000, filename: "capture.wav" }),
    );
    fireEvent.click(screen.getByText("Submit for analysis"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "laptop unavailable",
    );
    expect(screen.getByLabelText("recording preview")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Clear"));
    expect(screen.getByText("Submit for analysis")).toBeEnabled();
    fireEvent.click(screen.getByText("Record another"));
    expect(screen.getByLabelText("start recording")).toBeEnabled();
    expect(active).toHaveBeenLastCalledWith(false);
  });
  it("shows denied permission and never enters recording", async () => {
    mocks.permission.mockRejectedValue(
      new DOMException("denied", "NotAllowedError"),
    );
    render(<RecordingPanel {...props} />);
    fireEvent.click(screen.getByLabelText("start recording"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Microphone permission was denied",
    );
    expect(mocks.start).not.toHaveBeenCalled();
  });
  it("offers download when local quota fails and closes capture resources on unmount", async () => {
    vi.mocked(saveCapture).mockRejectedValue(new Error("quota exceeded"));
    const { unmount } = render(<RecordingPanel {...props} />);
    fireEvent.click(screen.getByLabelText("start recording"));
    await screen.findByLabelText("stop recording");
    fireEvent.click(screen.getByLabelText("stop recording"));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("quota exceeded"),
    );
    expect(
      screen.getByRole("link", { name: "Download original" }),
    ).toHaveAttribute("href", "blob:preview");
    unmount();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:preview");
  });
});
