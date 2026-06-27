import assert from "node:assert/strict";
import test from "node:test";

import { normalizeRobotStatus } from "../src/robotApi.ts";

test("normalizes partial backend status so panels do not crash on missing arrays", () => {
  const status = normalizeRobotStatus({
    mode: "stop",
    lidar: { ok: false, message: "no_data", scan_age_sec: null, scan_rate_hz: 0, valid_count: 0, valid_ratio: 0, frame_id: "" },
  });

  assert.deepEqual(status.radar_points, []);
  assert.equal(status.lane_offset, 0);
  assert.equal(status.map.message, "no_map");
  assert.equal(status.odom.message, "no_odom");
});
