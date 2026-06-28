import assert from "node:assert/strict";
import test from "node:test";

import {
  applySlamCorrection,
  mapPoseToScreenCell,
  projectPoseByCommand,
  projectPoseByVelocity,
  scaleCommandProjectionSpeed,
  shouldApplySlamCorrection,
  slamCorrectionTuning,
  smoothMapPoseCell,
} from "../src/mapPoseSmoothing.ts";

test("map pose smoothing ignores tiny position and heading jitter", () => {
  const previous = { x: 20, y: 30, yawDeg: 90 };
  const target = { x: 20.05, y: 29.95, yawDeg: 90.8 };

  const result = smoothMapPoseCell(previous, target);

  assert.deepEqual(result, previous);
});

test("map pose smoothing moves gradually for normal pose updates", () => {
  const previous = { x: 20, y: 30, yawDeg: 90 };
  const target = { x: 24, y: 30, yawDeg: 120 };

  const result = smoothMapPoseCell(previous, target);

  assert.equal(result.x, 22.2);
  assert.equal(result.y, 30);
  assert.ok(Math.abs(result.yawDeg - 109.5) < 0.000001);
});

test("map pose smoothing snaps after large map reset jumps", () => {
  const previous = { x: 20, y: 30, yawDeg: 90 };
  const target = { x: 80, y: 90, yawDeg: 180 };

  assert.deepEqual(smoothMapPoseCell(previous, target), target);
});

test("map pose conversion keeps the vehicle icon front aligned with the physical car", () => {
  const frame = { width: 100, height: 100, resolution: 1, originX: 0, originY: 0 };

  assert.deepEqual(mapPoseToScreenCell(frame, { x: 10, y: 20, yaw: 0 }), {
    x: 10,
    y: 80,
    yawDeg: 180,
    motionYawDeg: 0,
  });
  assert.deepEqual(mapPoseToScreenCell(frame, { x: 10, y: 20, yaw: Math.PI / 2 }), {
    x: 10,
    y: 80,
    yawDeg: 90,
    motionYawDeg: -90,
  });
  assert.deepEqual(mapPoseToScreenCell(frame, { x: 10, y: 20, yaw: -Math.PI / 2 }), {
    x: 10,
    y: 80,
    yawDeg: 270,
    motionYawDeg: 90,
  });
});

test("command projection drives the marker from motion heading, not icon heading", () => {
  const pose = { x: 50, y: 50, yawDeg: 180, motionYawDeg: 0 };

  assert.deepEqual(projectPoseByCommand(pose, "forward", 1, 0.5), {
    x: 49.5,
    y: 50,
    yawDeg: 180,
    motionYawDeg: 0,
  });
  assert.deepEqual(projectPoseByCommand(pose, "backward", 1, 0.5), {
    x: 50.5,
    y: 50,
    yawDeg: 180,
    motionYawDeg: 0,
  });
});

test("lateral command projection is reduced to avoid visible SLAM pullback", () => {
  assert.equal(scaleCommandProjectionSpeed("left", 10), 4.5);
  assert.equal(scaleCommandProjectionSpeed("right", 10), 4.5);
  assert.equal(scaleCommandProjectionSpeed("forward", 10), 10);
  assert.equal(scaleCommandProjectionSpeed("turn_l", 10), 10);
});

test("command projection updates yaw for turn commands while preserving the visual heading offset", () => {
  const pose = { x: 50, y: 50, yawDeg: 180, motionYawDeg: 0 };

  assert.deepEqual(projectPoseByCommand(pose, "turn_l", 1, 0.5, 30), {
    x: 50,
    y: 50,
    yawDeg: 150,
    motionYawDeg: -30,
  });
  assert.deepEqual(projectPoseByCommand(pose, "turn_r", 1, 0.5, 30), {
    x: 50,
    y: 50,
    yawDeg: 210,
    motionYawDeg: 30,
  });
});

test("command turn fallback matches measured cmd_vel angular speed", () => {
  const pose = { x: 50, y: 50, yawDeg: 180, motionYawDeg: 0 };

  assert.deepEqual(projectPoseByCommand(pose, "turn_l", 1, 0.5), {
    x: 50,
    y: 50,
    yawDeg: 166,
    motionYawDeg: -14,
  });
  assert.deepEqual(projectPoseByCommand(pose, "turn_r", 1, 0.5), {
    x: 50,
    y: 50,
    yawDeg: 194,
    motionYawDeg: 14,
  });
});

test("velocity projection follows controller cmd_vel signs", () => {
  const pose = { x: 50, y: 50, yawDeg: 180, motionYawDeg: 0 };

  assert.deepEqual(projectPoseByVelocity(pose, { linear_x: 0.1, linear_y: 0, angular_z: 0 }, 1, 0.05), {
    x: 48,
    y: 50,
    yawDeg: 180,
    motionYawDeg: 0,
  });
  assert.deepEqual(projectPoseByVelocity(pose, { linear_x: 0, linear_y: 0.1, angular_z: 0 }, 1, 0.05), {
    x: 50,
    y: 52,
    yawDeg: 180,
    motionYawDeg: 0,
  });
  assert.deepEqual(projectPoseByVelocity(pose, { linear_x: 0, linear_y: 0, angular_z: 1 }, 1, 0.05), {
    x: 50,
    y: 50,
    yawDeg: 122.70422048691768,
    motionYawDeg: -57.29577951308232,
  });
});

test("slam correction can be disabled, attracted, or snapped", () => {
  const display = { x: 50, y: 50, yawDeg: 180, motionYawDeg: 0 };
  const nearSlam = { x: 52, y: 50, yawDeg: 180, motionYawDeg: 0 };
  const farSlam = { x: 80, y: 50, yawDeg: 180, motionYawDeg: 0 };

  assert.deepEqual(applySlamCorrection(display, nearSlam, false), {
    pose: display,
    status: "off",
  });
  assert.deepEqual(applySlamCorrection(display, nearSlam, true, { attractDistanceCells: 8, snapDistanceCells: 18, alpha: 0.25 }), {
    pose: { x: 50.5, y: 50, yawDeg: 180, motionYawDeg: 0 },
    status: "attract",
  });
  assert.deepEqual(applySlamCorrection(display, farSlam, true, { attractDistanceCells: 8, snapDistanceCells: 18, alpha: 0.25 }), {
    pose: farSlam,
    status: "snap",
  });
});

test("slam correction applies continuously instead of waiting for stop-only pullback", () => {
  const moving = { ok: true, linear_x: 0.07, linear_y: 0, angular_z: 0 };
  const rotating = { ok: true, linear_x: 0, linear_y: 0, angular_z: 0.25 };
  const stopped = { ok: true, linear_x: 0, linear_y: 0, angular_z: 0 };

  assert.equal(shouldApplySlamCorrection(true, true, "forward", moving), true);
  assert.equal(shouldApplySlamCorrection(true, true, "turn_l", rotating), true);
  assert.equal(shouldApplySlamCorrection(true, true, "stop", stopped), true);
  assert.equal(shouldApplySlamCorrection(false, true, "stop", stopped), false);
  assert.equal(shouldApplySlamCorrection(true, false, "stop", stopped), false);
});

test("lateral commands use stronger in-motion SLAM attraction than forward commands", () => {
  const lateral = slamCorrectionTuning("left", true);
  const forward = slamCorrectionTuning("forward", true);
  const stopped = slamCorrectionTuning("stop", false);

  assert.equal(lateral.alpha, 0.045);
  assert.ok(lateral.alpha > forward.alpha);
  assert.ok(lateral.positionAlpha < forward.positionAlpha);
  assert.equal(lateral.snapDistanceCells, 999);
  assert.equal(stopped.alpha, 0.035);
});
