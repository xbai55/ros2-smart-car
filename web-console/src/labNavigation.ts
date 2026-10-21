import type { MapSnapshot } from "./robotApi";

export type Point = { x: number; y: number };
export type Pose = Point & { yaw: number };
export type CalibrationPair = { drawing: Point; world: Point };
export type DrawingDescriptor = { id: string; name: string; width: number; height: number; kind: "builtin" | "uploaded"; revision?: string };
export const BUILTIN_DRAWING: DrawingDescriptor = { id: "builtin-lab", name: "实验室平面图", width: 1208, height: 552, kind: "builtin" };
export type Calibration = { map_key: string; matrix: number[]; anchors: CalibrationPair[]; drawing?: DrawingDescriptor; invalidated?: boolean; max_error?: number; rms_error?: number; errors?: number[] };
export type Place = { id: string; name: string; drawing: Point; yaw: number };
export type NavigationConfig = { calibration: Calibration | null; places: Place[] };

export function sameDrawing(a: DrawingDescriptor | undefined, b: DrawingDescriptor) {
  const first = a || BUILTIN_DRAWING;
  return first.id === b.id && first.kind === b.kind && first.width === b.width && first.height === b.height && (first.revision || "") === (b.revision || "");
}
export function validImagePoint(p: Point, drawing: DrawingDescriptor) {
  return Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= 0 && p.y >= 0 && p.x < drawing.width && p.y < drawing.height;
}
export type NavigationState = {
  ready: boolean; state: "idle" | "planning" | "preview" | "starting" | "running" | "succeeded" | "canceled" | "failed";
  message: string; goal_id: string | null; goal: Pose | null; path: Point[];
  distance_remaining: number | null; estimated_time_remaining: number | null;
};
export type NavigationPlan = { ok: boolean; plan_id: string; map_key: string; goal: Pose; path: Point[]; distance: number };

// Drawing units reproduce the supplied sketch, and deliberately are not metres.
export const LAB = { width: 1208, height: 552, door: { x: 1078, y: 510 } };
export const LAB_BARRIERS: Array<[Point, Point]> = [
  [{ x: 0, y: 0 }, { x: 1208, y: 0 }], [{ x: 0, y: 0 }, { x: 0, y: 552 }],
  [{ x: 1208, y: 0 }, { x: 1208, y: 552 }], [{ x: 0, y: 552 }, { x: 1007, y: 552 }],
  [{ x: 1148, y: 552 }, { x: 1208, y: 552 }],
  [{ x: 0, y: 165 }, { x: 912, y: 165 }],
  [{ x: 912, y: 88 }, { x: 912, y: 243 }],
  [{ x: 0, y: 398 }, { x: 912, y: 398 }],
];
export const DEFAULT_PLACES: Place[] = [
  { id: "teacher", name: "老师处", drawing: { x: 1015, y: 180 }, yaw: Math.PI },
  { id: "door", name: "门口", drawing: { ...LAB.door }, yaw: -Math.PI / 2 },
];
export const INITIAL_NAVIGATION: NavigationState = {
  ready: false, state: "idle", message: "等待车端导航服务", goal_id: null, goal: null,
  path: [], distance_remaining: null, estimated_time_remaining: null,
};
export function distanceToSegment(p: Point, a: Point, b: Point) {
  const dx = b.x - a.x, dy = b.y - a.y;
  const t = Math.max(0, Math.min(1, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)));
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}
export function validDrawingPoint(p: Point, margin = 18) {
  return Number.isFinite(p.x) && Number.isFinite(p.y) && p.x >= margin && p.y >= margin &&
    p.x <= LAB.width - margin && p.y <= LAB.height - margin &&
    LAB_BARRIERS.every(([a, b], i) => distanceToSegment(p, a, b) > (i < 5 ? margin : Math.max(28, margin)));
}
export function drawingToWorld(p: Point, matrix: number[]): Point {
  return { x: matrix[0] * p.x + matrix[1] * p.y + matrix[2], y: matrix[3] * p.x + matrix[4] * p.y + matrix[5] };
}
export function worldToDrawing(p: Point, matrix: number[]): Point {
  const determinant = matrix[0] * matrix[4] - matrix[1] * matrix[3];
  if (Math.abs(determinant) < 1e-12) throw new Error("地图对齐参数无效");
  const x = p.x - matrix[2], y = p.y - matrix[5];
  return { x: (matrix[4] * x - matrix[1] * y) / determinant, y: (-matrix[3] * x + matrix[0] * y) / determinant };
}
export function drawingYawToWorld(yaw: number, matrix: number[]) {
  const x = Math.cos(yaw), y = Math.sin(yaw);
  return Math.atan2(matrix[3] * x + matrix[4] * y, matrix[0] * x + matrix[1] * y);
}
export function worldYawToDrawing(yaw: number, matrix: number[]) {
  const a = worldToDrawing({ x: 0, y: 0 }, matrix), b = worldToDrawing({ x: Math.cos(yaw), y: Math.sin(yaw) }, matrix);
  return Math.atan2(b.y - a.y, b.x - a.x);
}
export function mapKey(snapshot: MapSnapshot) {
  const i = snapshot.info;
  const identity = snapshot.asset_digest || snapshot.session_id;
  return `${snapshot.header?.frame_id || "map"}:${i.width}:${i.height}:${i.resolution.toFixed(6)}:${i.origin.x.toFixed(6)}:${i.origin.y.toFixed(6)}:${i.origin.yaw.toFixed(6)}${identity ? `:${identity}` : ""}`;
}
export function mapScreenToWorld(snapshot: MapSnapshot, p: Point): Point {
  const { origin, resolution, height } = snapshot.info;
  const x = p.x * resolution, y = (height - p.y) * resolution;
  return { x: origin.x + Math.cos(origin.yaw) * x - Math.sin(origin.yaw) * y,
    y: origin.y + Math.sin(origin.yaw) * x + Math.cos(origin.yaw) * y };
}

/** Local sketch preview only: the actual vehicle always uses a Nav2 plan. */
export function planDrawingPath(start: Point, goal: Point): Point[] {
  if (!validDrawingPoint(start) || !validDrawingPoint(goal)) return [];
  const step = 12, cols = Math.floor(LAB.width / step) + 1, rows = Math.floor(LAB.height / step) + 1;
  const index = (p: Point) => Math.round(p.y / step) * cols + Math.round(p.x / step);
  const point = (id: number) => ({ x: (id % cols) * step, y: Math.floor(id / cols) * step });
  const source = index(start), target = index(goal), open = new Set([source]), done = new Set<number>();
  const costs = new Map([[source, 0]]), parent = new Map<number, number>();
  const free = new Map<number, boolean>();
  const valid = (id: number) => {
    if (!free.has(id)) free.set(id, validDrawingPoint(point(id)));
    return free.get(id)!;
  };
  if (!valid(source) || !valid(target)) return [];
  const heuristic = (id: number) => Math.abs(id % cols - target % cols) + Math.abs(Math.floor(id / cols) - Math.floor(target / cols));
  while (open.size) {
    let current = -1, best = Infinity;
    for (const id of open) { const score = costs.get(id)! + heuristic(id); if (score < best) { current = id; best = score; } }
    if (current === target) {
      const ids = [current];
      while (parent.has(ids[ids.length - 1])) ids.push(parent.get(ids[ids.length - 1])!);
      const points = ids.reverse().map(point);
      const simplified = points.filter((p, i) => i === 0 || i === points.length - 1 ||
        (p.x - points[i - 1].x) * (points[i + 1].y - p.y) !== (p.y - points[i - 1].y) * (points[i + 1].x - p.x));
      return [start, ...simplified, goal];
    }
    open.delete(current); done.add(current);
    const x = current % cols, y = Math.floor(current / cols);
    for (const [nx, ny] of [[x - 1, y], [x + 1, y], [x, y - 1], [x, y + 1]]) {
      if (nx < 0 || ny < 0 || nx >= cols || ny >= rows) continue;
      const next = ny * cols + nx;
      if (done.has(next) || !valid(next)) continue;
      const cost = costs.get(current)! + 1;
      if (cost < (costs.get(next) ?? Infinity)) { costs.set(next, cost); parent.set(next, current); open.add(next); }
    }
  }
  return [];
}
