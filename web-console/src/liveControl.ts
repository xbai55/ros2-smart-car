import type { MapSnapshot, RadarPoint, RobotStatus } from "./robotApi";

export const LIVE_ROBOT_ID = "r-001";
export const MAPPING_SPEED_MAX = 50;
export const MAPPING_SPEED_PRESETS = [15, 25, 35, 50];
export const MODE_LABELS: Record<string, string> = { stop: "停止", manual: "手动驾驶", auto: "自动避障", mapping: "SLAM 建图", navigation: "导航", color_track: "颜色追踪", object_follow: "目标跟随" };
export const COMMAND_LABELS: Record<string, string> = { forward: "前进", backward: "后退", left: "左移", right: "右移", turn_l: "左旋", turn_r: "右旋", stop: "停止" };
export function percentToScale(percent: number, mapping = false) {
  return Math.max(15, Math.min(mapping ? MAPPING_SPEED_MAX : 100, Number.isFinite(percent) ? percent : 15)) / 100;
}
export function canDrive(status: RobotStatus, connected: boolean, robotId = LIVE_ROBOT_ID) {
  const initializing = status.mapping?.state === "starting" || status.mapping?.state === "waiting_map" || status.mapping?.state === "error";
  return robotId === LIVE_ROBOT_ID && connected && !status.emergency_stop && (status.mode === "manual" || status.mode === "mapping" && !initializing);
}
export const DRIVE_KEYS: Record<string, string> = { w: "forward", ArrowUp: "forward", s: "backward", ArrowDown: "backward", a: "left", ArrowLeft: "left", d: "right", ArrowRight: "right", q: "turn_l", e: "turn_r" };
export const DRIVE_PROTECTED_TARGETS = "input,textarea,select,[contenteditable=true],[role=dialog],[role=slider]";
export function driveKeyCommand(event: Pick<KeyboardEvent, "key" | "defaultPrevented" | "ctrlKey" | "metaKey" | "altKey">, protectedTarget = false) {
  if (event.defaultPrevented || event.ctrlKey || event.metaKey || event.altKey || protectedTarget) return null;
  const key = event.key.length === 1 ? event.key.toLowerCase() : event.key;
  return key === " " ? "stop" : DRIVE_KEYS[key] ?? null;
}
export function validThreshold(value: number) { return Number.isFinite(value) && value >= 0 && value <= 5; }
export function radarScreenPoint(point: RadarPoint, range: number, radius = 240, center = 300) {
  return { x: center - point.y / range * radius, y: center - point.x / range * radius };
}
export function validRadarPoints(points: RadarPoint[]) {
  return points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.distance) && p.distance > 0);
}
export function validMap(snapshot: MapSnapshot) {
  if (!snapshot?.info?.origin || !Array.isArray(snapshot.data)) return false;
  const { width, height, resolution, origin } = snapshot.info;
  return Number.isInteger(width) && Number.isInteger(height) && width > 0 && height > 0 && width * height <= 16000000 && resolution > 0 && Number.isFinite(resolution) && [origin.x, origin.y, origin.yaw].every(Number.isFinite) && snapshot.data.length === width * height;
}
export function mapWorldToScreen(snapshot: MapSnapshot, pose: { x: number; y: number; yaw: number }) {
  const { origin, resolution, height } = snapshot.info;
  const dx = pose.x - origin.x, dy = pose.y - origin.y;
  const cos = Math.cos(origin.yaw), sin = Math.sin(origin.yaw);
  return { x: (cos * dx + sin * dy) / resolution, y: height - (-sin * dx + cos * dy) / resolution, yawDeg: -(pose.yaw - origin.yaw) * 180 / Math.PI };
}

export type HoldClock = { every: (fn: () => void, ms: number) => unknown; clear: (timer: unknown) => void };
export function bindDriveStops(windowTarget: EventTarget, documentTarget: EventTarget & { hidden?: boolean }, stop: () => void) {
  const events = ["blur", "pointerup", "pointercancel", "pagehide", "hashchange", "robot-control-stop"];
  const hidden = () => { if (documentTarget.hidden) stop(); };
  for (const event of events) windowTarget.addEventListener(event, stop);
  documentTarget.addEventListener("visibilitychange", hidden);
  return () => { stop(); for (const event of events) windowTarget.removeEventListener(event, stop); documentTarget.removeEventListener("visibilitychange", hidden); };
}
export class DriveHoldController {
  private active: string | null = null;
  private timer: unknown = null;
  private pending: Promise<unknown> | null = null;
  private disposed = false;
  private send: (command: string) => Promise<boolean>;
  private clock: HoldClock;
  private changed: (command: string | null) => void;
  constructor(send: (command: string) => Promise<boolean>, clock: HoldClock, changed: (command: string | null) => void = () => {}) { this.send = send; this.clock = clock; this.changed = changed; }
  start(command: string) {
    if (this.disposed) return;
    if (command === "stop") { this.stop(true); return; }
    this.clearTimer(); this.active = command; this.changed(command); this.tick();
    this.timer = this.clock.every(() => this.tick(), 180);
  }
  private tick() {
    if (!this.active || this.pending || this.disposed) return;
    const pending = this.send(this.active).then(ok => { if (!ok) this.stop(); }).catch(() => this.stop());
    this.pending = pending;
    void pending.finally(() => {
      if (this.pending === pending) this.pending = null;
      // A delayed movement request must be followed by a stop after release.
      if (!this.active) void this.send("stop").catch(() => false);
    });
  }
  private clearTimer() { if (this.timer !== null) this.clock.clear(this.timer); this.timer = null; }
  stop(force = false) {
    const moving = this.active !== null; this.active = null; this.clearTimer(); this.changed(null);
    if (moving || force) void this.send("stop").catch(() => false);
  }
  dispose() { this.stop(); this.disposed = true; }
}
