import type { VideoState } from "./videoState";

type Options = {
  fetchFrame: (signal: AbortSignal) => Promise<Blob>;
  display: (frame: Blob, signal: AbortSignal) => Promise<void>;
  onState: (state: VideoState) => void;
  visible?: boolean;
  intervalMs?: number;
  timeoutMs?: number;
  retryMs?: number;
};

// One finite request and one decoded image at a time. A slow connection lowers
// FPS instead of building a TCP queue of increasingly old MJPEG frames.
export function startCameraPolling({ fetchFrame, display, onState, visible = true,
  intervalMs = 100, timeoutMs = 1500, retryMs = 500 }: Options) {
  let stopped = false, running = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let controller: AbortController | undefined;
  const schedule = (delay: number) => {
    if (stopped || !visible || running) return;
    clearTimeout(timer);
    timer = setTimeout(() => void run(), delay);
  };
  const run = async () => {
    if (stopped || !visible || running) return;
    running = true;
    const current = controller = new AbortController();
    const started = performance.now();
    const deadline = setTimeout(() => current.abort(), timeoutMs);
    let failed = false;
    try {
      const frame = await fetchFrame(current.signal);
      if (stopped || !visible || current.signal.aborted) return;
      await display(frame, current.signal);
      if (!stopped && visible && !current.signal.aborted) onState("connected");
    } catch {
      failed = true;
      if (!stopped && visible && controller === current) onState("error");
    } finally {
      clearTimeout(deadline);
      running = false;
      if (controller === current) controller = undefined;
      schedule(failed ? retryMs : Math.max(0, intervalMs - (performance.now() - started)));
    }
  };
  schedule(0);
  return {
    stop() { stopped = true; clearTimeout(timer); controller?.abort(); },
    setVisible(value: boolean) {
      if (visible === value || stopped) return;
      visible = value;
      clearTimeout(timer);
      controller?.abort();
      if (visible) { onState("loading"); schedule(0); }
    },
  };
}
