import { drawingToWorld, mapScreenToWorld, type Point } from "./labNavigation";
import { mapWorldToScreen } from "./liveControl";
import type { MapSnapshot } from "./robotApi";

export function worldToRaster(snapshot: MapSnapshot, p: Point) {
  return mapWorldToScreen(snapshot, { ...p, yaw: 0 });
}

export function rasterViewport(snapshot: MapSnapshot, basis: MapSnapshot, size: { w: number; h: number }, zoom: number, pan: Point) {
  const scale = Math.min(size.w / basis.info.width, size.h / basis.info.height) * .85 * zoom * snapshot.info.resolution / basis.info.resolution;
  const center = worldToRaster(snapshot, mapScreenToWorld(basis, { x: basis.info.width / 2, y: basis.info.height / 2 }));
  return { scale, offset: { x: (snapshot.info.width / 2 - center.x) * scale + pan.x, y: (snapshot.info.height / 2 - center.y) * scale + pan.y } };
}

export function rotatePoint(point: Point, angle: number): Point {
  const c = Math.cos(angle), s = Math.sin(angle);
  return { x: c * point.x - s * point.y, y: s * point.x + c * point.y };
}

export function rotatedRasterViewport(snapshot: MapSnapshot, basis: MapSnapshot, size: { w: number; h: number }, zoom: number, pan: Point, rotation: number) {
  const c = Math.abs(Math.cos(rotation)), s = Math.abs(Math.sin(rotation));
  const width = basis.info.width * c + basis.info.height * s, height = basis.info.width * s + basis.info.height * c;
  const scale = Math.min(size.w / width, size.h / height) * .85 * zoom * snapshot.info.resolution / basis.info.resolution;
  const center = worldToRaster(snapshot, mapScreenToWorld(basis, { x: basis.info.width / 2, y: basis.info.height / 2 }));
  const delta = rotatePoint({ x: (snapshot.info.width / 2 - center.x) * scale, y: (snapshot.info.height / 2 - center.y) * scale }, rotation);
  return { scale, offset: { x: delta.x + pan.x, y: delta.y + pan.y } };
}

export function viewportToRaster(point: Point, snapshot: MapSnapshot, size: { w: number; h: number }, scale: number, offset: Point, rotation: number) {
  const unrotated = rotatePoint({ x: (point.x - size.w / 2 - offset.x) / scale, y: (point.y - size.h / 2 - offset.y) / scale }, -rotation);
  return { x: unrotated.x + snapshot.info.width / 2, y: unrotated.y + snapshot.info.height / 2 };
}

// Canvas image coordinates -> measured grid coordinates, including both Y flips,
// the map origin rotation, resolution, and the persisted drawing registration.
export function drawingRasterTransform(snapshot: MapSnapshot, matrix: number[]) {
  const project = (p: Point) => worldToRaster(snapshot, drawingToWorld(p, matrix));
  const zero = project({ x: 0, y: 0 }), x = project({ x: 1, y: 0 }), y = project({ x: 0, y: 1 });
  return [x.x - zero.x, x.y - zero.y, y.x - zero.x, y.y - zero.y, zero.x, zero.y] as const;
}

// Preserve every occupancy value; visual styling never removes obstacles.
export function occupancyColor(value: number, theme: "light" | "dark") {
  if (theme === "dark") return value < 0 ? [29, 43, 62, 255] : value < 25 ? [216, 230, 240, 255] : value < 65 ? [123, 141, 161, 255] : [62, 83, 111, 255];
  return value < 0 ? [229, 235, 242, 255] : value < 25 ? [252, 253, 255, 255] : value < 65 ? [174, 189, 207, 255] : [51, 65, 85, 255];
}
