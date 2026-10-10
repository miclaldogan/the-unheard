import {
  Recorder,
  hasGetUserMedia,
  isSecureForMic,
  type CaptureResult,
  type LevelProbe,
} from "../audio/recorder";

/** Native Capacitor implementations can replace this boundary without changing recording UI. */
export interface CaptureDevice {
  onLevel: ((probe: LevelProbe) => void) | null;
  onAutoStop: (() => void) | null;
  requestPermission(): Promise<unknown>;
  start(): Promise<unknown>;
  stop(): Promise<CaptureResult>;
  cancel(): Promise<void>;
}
export interface DeviceEnvironment {
  secureMicrophone(): boolean;
  supportsMicrophone(): boolean;
  onSuspend(callback: () => void): () => void;
  hapticFeedback(): void;
}
export const browserDevice: DeviceEnvironment = {
  secureMicrophone: isSecureForMic,
  supportsMicrophone: hasGetUserMedia,
  onSuspend: (callback) => {
    const change = () => {
      if (document.visibilityState === "hidden") callback();
    };
    document.addEventListener("visibilitychange", change);
    return () => document.removeEventListener("visibilitychange", change);
  },
  // Deliberate silence: no haptics by default. A native adapter may add user-enabled feedback.
  hapticFeedback: () => undefined,
};
export function createCaptureDevice(options: { maxMs: number }): CaptureDevice {
  return new Recorder(options);
}
