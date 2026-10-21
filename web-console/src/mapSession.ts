import type { MapSnapshot, MappingState, MapPose } from "./robotApi";
import { validMap } from "./liveControl";

// An epoch invalidates pending HTTP responses even before the new session ID is known.
export class MapSessionGate {
  session: string | null = null;
  epoch = 0;
  restarting = false;
  private retired = new Set<string>();
  changeSession(session: string | null) {
    if (session && this.retired.has(session)) return false;
    if (session === this.session) return true;
    if (this.session) this.retired.add(this.session);
    this.session = session; this.epoch += 1;
    return true;
  }
  beginRestart() { this.restarting = true; this.epoch += 1; }
  finishRestart(session: string | null) { this.changeSession(session); this.restarting = false; }
  accepts(snapshot: MapSnapshot, epoch: number, previous: MapSnapshot | null) {
    if (this.restarting || epoch !== this.epoch) return false;
    if (this.session && snapshot.session_id !== this.session) return false;
    if (snapshot.session_id && this.retired.has(snapshot.session_id)) return false;
    if (previous?.session_id === snapshot.session_id && previous?.revision !== undefined && snapshot.revision !== undefined && snapshot.revision < previous.revision) return false;
    return true;
  }
}

export function sameMapRevision(previous: MapSnapshot | null, snapshot: MapSnapshot) {
  if (!previous || previous.session_id !== snapshot.session_id) return false;
  return snapshot.revision !== undefined ? previous.revision === snapshot.revision : previous.updated_at === snapshot.updated_at;
}

export function captureInitialMapYaw(previous: number | null, snapshot: MapSnapshot | null, mapping: MappingState, pose: MapPose, connected: boolean, stale: boolean) {
  if (previous !== null) return previous;
  if (!snapshot || !connected || stale || !pose.ok || !Number.isFinite(pose.yaw)) return null;
  if (mapping.session_id && snapshot.session_id !== mapping.session_id) return null;
  if (mapping.state === "starting" || mapping.state === "waiting_map" || mapping.state === "error") return null;
  const sampledAt = pose.updated_at === null ? null : pose.updated_at - (pose.age_sec ?? 0);
  if (mapping.started_at && (sampledAt === null || sampledAt < mapping.started_at)) return null;
  return pose.yaw;
}

type PollClock = { now: () => number; later: (callback: () => void, delay: number) => unknown; cancel: (timer: unknown) => void };
export function startMapPolling(options: {
  request: (signal: AbortSignal) => Promise<MapSnapshot>; gate: MapSessionGate;
  current: () => MapSnapshot | null; receive: (snapshot: MapSnapshot) => void; failed: (error: string) => void;
}, clock: PollClock) {
  let active = true, timer: unknown;
  const abort = new AbortController();
  const load = async () => {
    const started = clock.now(), epoch = options.gate.epoch;
    try {
      if (options.gate.restarting) return;
      const snapshot = await options.request(abort.signal);
      if (!validMap(snapshot)) throw new Error("地图尺寸或坐标数据异常");
      if (active && options.gate.accepts(snapshot, epoch, options.current())) {
        if (!sameMapRevision(options.current(), snapshot)) options.receive(snapshot);
        options.failed("");
      }
    } catch (reason) {
      if (active && epoch === options.gate.epoch) options.failed(reason instanceof Error ? reason.message : "暂时无法读取地图");
    } finally {
      if (active) timer = clock.later(() => void load(), Math.max(0, 500 - (clock.now() - started)));
    }
  };
  void load();
  return () => { active = false; abort.abort(); if (timer !== undefined) clock.cancel(timer); };
}
