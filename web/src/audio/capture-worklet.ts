/// <reference lib="webworker" />
// AudioWorklet processor: forwards raw Float32 PCM of channel 0 to the main thread.
// Runs in the AudioWorkletGlobalScope (no DOM). Loaded via `new URL(..., import.meta.url)`.

declare const sampleRate: number;
declare function registerProcessor(name: string, ctor: unknown): void;
declare class AudioWorkletProcessor {
  readonly port: MessagePort;
  constructor();
}

class CaptureProcessor extends AudioWorkletProcessor {
  private active = true;
  constructor() {
    super();
    this.port.onmessage = (e: MessageEvent) => {
      if (e.data === 'stop') this.active = false;
    };
  }
  process(inputs: Float32Array[][]): boolean {
    const input = inputs[0];
    if (this.active && input && input[0]) {
      const copy = new Float32Array(input[0]);
      this.port.postMessage({ samples: copy, sampleRate }, [copy.buffer]);
    }
    return this.active;
  }
}

registerProcessor('unheard-capture', CaptureProcessor);
