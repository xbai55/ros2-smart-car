import type { NavigationTaskState } from "./robotApi";

export function acceptTaskState(previous: NavigationTaskState | null, next: NavigationTaskState) {
  if (!previous) return next;
  if (previous.run_id && !next.run_id) return previous;
  if (previous.run_id === next.run_id && ['completed','failed','cancelled'].includes(previous.state) && previous.state !== next.state) return previous;
  if (previous.run_id === next.run_id && (previous.version || 0) > (next.version || 0)) return previous;
  if (previous.run_id !== next.run_id && (previous.updated_at || 0) > (next.updated_at || 0)) return previous;
  return next;
}
