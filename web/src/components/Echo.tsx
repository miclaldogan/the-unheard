/** ECHO-0 static system lines (doc 07). Only states that are true at render time. */
export type EchoEvent = 'idle' | 'armed' | 'recording' | 'recorded' | 'uploading' | 'processing' | 'preserved' | 'failed' | 'denied' | 'offline';

const LINES: Record<EchoEvent, string> = {
  idle: 'I am ready to listen.',
  armed: 'The microphone is open. I am holding still.',
  recording: 'Listening. I keep nothing until you say stop.',
  recorded: 'A signal is waiting. It is not yet mine.',
  uploading: 'Receiving.',
  processing: 'Measuring what you gave me.',
  preserved: 'A signal has been preserved. I have measured it; I have not yet understood it.',
  failed: 'The signal arrived, but my measurement failed. It is kept.',
  denied: 'I cannot hear without permission.',
  offline: 'I cannot reach the archive.',
};

export function Echo({ event }: { event: EchoEvent }) {
  return (
    <p className="echo" role="status" aria-live="polite">
      <span className="tag">ECHO-0</span>
      {LINES[event]}
    </p>
  );
}
