import assert from "node:assert/strict";
import test from "node:test";
import { MAPPING_RANGE_PRESETS, validMappingRange, validTurnSpeed } from "../src/mappingSettings";
import { createRobotApi, normalizeRobotStatus } from "../src/robotApi";
import { ROBOT_API_PROXY_PATTERN } from "../src/robotProxy";

test("mapping presets and independent angular limits reject invalid inputs", () => {
  assert.deepEqual([...MAPPING_RANGE_PRESETS], [0.5, 1, 3, 6]);
  for (const n of MAPPING_RANGE_PRESETS) assert.equal(validMappingRange(n), true);
  for (const n of [0, 2, NaN, Infinity]) assert.equal(validMappingRange(n), false);
  for (const n of [0.05, 0.15, 0.6]) assert.equal(validTurnSpeed(n), true);
  for (const n of [0, 0.61, NaN, Infinity]) assert.equal(validTurnSpeed(n), false);
});

test("settings requests use the car proxy and preserve per-session range", async () => {
  const requests: {url: string; body: unknown}[] = [];
  const api = createRobotApi(async (url, options) => {
    requests.push({url: String(url), body: JSON.parse(String(options?.body))});
    return new Response(JSON.stringify({ok: true, settings: {turn_speed: 0.15, max_laser_range: 1}}));
  });
  await api.setMotionSettings({turn_speed: 0.15});
  await api.setMotionSettings({max_laser_range: 1});
  assert.deepEqual(requests.map(x=>x.body), [{turn_speed: 0.15}, {max_laser_range: 1}]);
  assert.equal(new RegExp(ROBOT_API_PROXY_PATTERN).test(requests[0].url), true);
  const status = normalizeRobotStatus({motion_settings: {turn_speed: 0.15, max_laser_range: 1}, manual_turn_speed: 0.15,
    mapping: {state: "ready", session_id: "current", started_at: 1, error: null, max_laser_range: 6}});
  assert.equal(status.mapping.max_laser_range, 6);
  assert.equal(status.motion_settings?.max_laser_range, 1);
});
