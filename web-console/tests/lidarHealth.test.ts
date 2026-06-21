import assert from "node:assert/strict";
import test from "node:test";

import { lidarHealthLabel, lidarIsReady } from "../src/lidarHealth.ts";


test("lidar readiness requires an explicit healthy status", () => {
  assert.equal(lidarIsReady(undefined), false);
  assert.equal(lidarIsReady({ ok: false, message: "stale" }), false);
  assert.equal(lidarIsReady({ ok: true, message: "ok" }), true);
});


test("lidar health messages have stable operator labels", () => {
  assert.equal(lidarHealthLabel(undefined), "等待雷达数据");
  assert.equal(lidarHealthLabel({ ok: false, message: "no_data" }), "未收到雷达数据");
  assert.equal(lidarHealthLabel({ ok: false, message: "stale" }), "雷达数据已过期");
  assert.equal(lidarHealthLabel({ ok: false, message: "insufficient_valid_points" }), "雷达有效点不足");
  assert.equal(lidarHealthLabel({ ok: true, message: "ok" }), "雷达正常");
});
