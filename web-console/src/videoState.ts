export type VideoState = "loading" | "connected" | "error";
export const VIDEO_START_TIMEOUT_MS = 6000;

export function videoStateAfterTimeout(state: VideoState): VideoState {
  return state === "loading" ? "error" : state;
}

export function shouldStartVideo(readyState: DocumentReadyState): boolean {
  return readyState === "complete";
}
