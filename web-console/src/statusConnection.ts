// Allow a new socket to finish connecting even when the previous session is stale.
export function statusSocketTimedOut(readyState: number, receivedAt: number, startedAt: number, now: number) {
  if (readyState === 0) return now - startedAt > 5000;
  if (readyState === 1) return now - (receivedAt || startedAt) > 2500;
  return false;
}
