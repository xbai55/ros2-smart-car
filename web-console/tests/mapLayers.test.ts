import assert from "node:assert/strict";
import test from "node:test";
import { drawingRasterTransform, occupancyColor, rasterViewport, rotatedRasterViewport, rotatePoint, viewportToRaster, worldToRaster } from "../src/mapLayers.ts";
import { BUILTIN_DRAWING, drawingToWorld, mapScreenToWorld, sameDrawing, validImagePoint } from "../src/labNavigation.ts";
import type { MapSnapshot } from "../src/robotApi.ts";

test("registered image overlay stays in the same coordinates as robot and goal on a rotated map", () => {
  const snapshot = { info: { width: 200, height: 160, resolution: .05, origin: { x: -3, y: 2, yaw: .7 } } } as MapSnapshot;
  const registration = [.018, .003, -1, -.002, -.016, 7];
  const [a, b, c, d, e, f] = drawingRasterTransform(snapshot, registration);
  for (const p of [{ x: 0, y: 0 }, { x: 800, y: 450 }, { x: 235, y: 177 }]) {
    const world = mapScreenToWorld(snapshot, { x: a * p.x + c * p.y + e, y: b * p.x + d * p.y + f });
    const expected = drawingToWorld(p, registration);
    assert.ok(Math.hypot(world.x - expected.x, world.y - expected.y) < 1e-9);
  }
});

test("renaming preserves calibration but another image or size invalidates it", () => {
  const drawing = { id: "map-a", name: "房间", width: 800, height: 450, kind: "uploaded" as const, revision: "maps/a.png" };
  assert.ok(sameDrawing(drawing, { ...drawing, name: "房间新名字" }));
  assert.ok(!sameDrawing(drawing, { ...drawing, id: "map-b" }));
  assert.ok(!sameDrawing(drawing, { ...drawing, width: 801 }));
  assert.ok(!sameDrawing(drawing, { ...drawing, revision: "maps/new.png" }));
  assert.ok(sameDrawing(undefined, BUILTIN_DRAWING));
  assert.ok(!sameDrawing(undefined, drawing));
});

test("custom images respect their own bounds rather than laboratory walls", () => {
  const drawing = { id: "large", name: "大图", width: 2000, height: 1200, kind: "uploaded" as const };
  assert.ok(validImagePoint({ x: 1500, y: 900 }, drawing));
  assert.ok(validImagePoint({ x: 400, y: 165 }, drawing));
  for (const p of [{ x: 2000, y: 0 }, { x: -1, y: 10 }, { x: NaN, y: 0 }]) assert.ok(!validImagePoint(p, drawing));
});

test("map palettes keep obstacles distinct without modifying occupancy", () => {
  for (const theme of ["light", "dark"] as const) {
    assert.notDeepEqual(occupancyColor(100, theme), occupancyColor(0, theme));
    assert.notDeepEqual(occupancyColor(-1, theme), occupancyColor(0, theme));
    assert.equal(occupancyColor(100, theme)[3], 255);
  }
});

test("growing SLAM dimensions and shifted origin preserve a world's screen position and size", () => {
  const basis = { info: { width: 200, height: 160, resolution: .05, origin: { x: -3, y: 2, yaw: .7 } } } as MapSnapshot;
  const grown = { info: { width: 340, height: 240, resolution: .025, origin: { x: -5, y: 1, yaw: .7 } } } as MapSnapshot;
  const size = { w: 800, h: 450 }, pan = { x: 35, y: -21 };
  const screen = (map: MapSnapshot, point: { x: number; y: number }) => {
    const v = rasterViewport(map, basis, size, 1.7, pan), p = worldToRaster(map, point);
    return { x: size.w / 2 + v.offset.x + (p.x - map.info.width / 2) * v.scale, y: size.h / 2 + v.offset.y + (p.y - map.info.height / 2) * v.scale };
  };
  for (const point of [{ x: 1, y: 2 }, { x: 3, y: 7 }]) {
    const before = screen(basis, point), after = screen(grown, point);
    assert.ok(Math.hypot(before.x - after.x, before.y - after.y) < 1e-8);
  }
});

test("automatic fitting keeps every corner of a map growing down and right inside the canvas", () => {
  const size = { w: 900, h: 400 };
  for (const [width, height] of [[100, 100], [220, 180], [300, 400]]) {
    const snapshot = { info: { width, height, resolution: .05, origin: { x: -3, y: -2, yaw: .3 } } } as MapSnapshot;
    for (const rotation of [0, .5, -Math.PI / 2]) {
      const v = rotatedRasterViewport(snapshot, snapshot, size, 1, { x: 0, y: 0 }, rotation);
      for (const [x, y] of [[0, 0], [width, 0], [width, height], [0, height]]) {
        const p = rotatePoint({ x: (x - width / 2) * v.scale, y: (y - height / 2) * v.scale }, rotation);
        assert.ok(p.x + size.w / 2 >= 0 && p.x + size.w / 2 <= size.w);
        assert.ok(p.y + size.h / 2 >= 0 && p.y + size.h / 2 <= size.h);
      }
    }
  }
});

test("heading-up display preserves world coordinates when selecting a navigation target", () => {
  const snapshot = { info: { width: 230, height: 140, resolution: .05, origin: { x: -3, y: -2, yaw: .3 } } } as MapSnapshot;
  const size = { w: 900, h: 400 }, initialYaw = 1.1, rotation = initialYaw - snapshot.info.origin.yaw - Math.PI / 2;
  const viewport = rotatedRasterViewport(snapshot, snapshot, size, 1.3, { x: 24, y: -35 }, rotation);
  for (const point of [{ x: -1, y: 0 }, { x: 2, y: 4 }]) {
    const raster = worldToRaster(snapshot, point);
    const delta = rotatePoint({ x: (raster.x - snapshot.info.width / 2) * viewport.scale, y: (raster.y - snapshot.info.height / 2) * viewport.scale }, rotation);
    const screen = { x: size.w / 2 + viewport.offset.x + delta.x, y: size.h / 2 + viewport.offset.y + delta.y };
    const selected = mapScreenToWorld(snapshot, viewportToRaster(screen, snapshot, size, viewport.scale, viewport.offset, rotation));
    assert.ok(Math.hypot(point.x - selected.x, point.y - selected.y) < 1e-9);
  }
  const arrowAngle = -(initialYaw - snapshot.info.origin.yaw) + rotation;
  assert.ok(Math.abs(arrowAngle + Math.PI / 2) < 1e-9);
});
