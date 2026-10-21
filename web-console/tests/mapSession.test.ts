import assert from "node:assert/strict";
import test from "node:test";
import { MapSessionGate, sameMapRevision, startMapPolling, captureInitialMapYaw } from "../src/mapSession.ts";
import { initialRobotStatus, type MapSnapshot } from "../src/robotApi.ts";

const map = (session_id: string, revision: number) => ({ session_id, revision, updated_at: 1 } as MapSnapshot);

test("restart invalidates a pending old map before the new session ID is received", () => {
  const gate = new MapSessionGate(); gate.changeSession("old"); const oldEpoch = gate.epoch;
  gate.beginRestart();
  assert.equal(gate.accepts(map("old", 8), oldEpoch, null), false);
  gate.finishRestart("new");
  assert.equal(gate.accepts(map("old", 9), gate.epoch, null), false);
  assert.equal(gate.accepts(map("new", 1), gate.epoch, null), true);
  assert.equal(gate.changeSession("old"), false);
  assert.equal(gate.session, "new");
});

test("session restart accepts revision one and ignores out-of-order revisions", () => {
  const gate = new MapSessionGate(); gate.changeSession("first");
  assert.equal(gate.accepts(map("first", 2), gate.epoch, map("first", 3)), false);
  gate.changeSession("second");
  assert.equal(gate.accepts(map("second", 1), gate.epoch, map("first", 30)), true);
  assert.equal(sameMapRevision(map("first", 1), map("second", 1)), false);
  assert.equal(sameMapRevision(map("second", 1), map("second", 2)), false);
  assert.equal(sameMapRevision(map("second", 2), map("second", 2)), true);
});

test("initial heading survives later turns and rejects stale poses from before restart", () => {
  const mapping = { ...initialRobotStatus.mapping, session_id: "new", started_at: 100, state: "ready" as const };
  const pose = { ...initialRobotStatus.map_pose, ok: true, yaw: .8, updated_at: 101, age_sec: 2 };
  assert.equal(captureInitialMapYaw(null, map("new", 1), mapping, pose, true, false), null);
  const heading = captureInitialMapYaw(null, map("new", 1), mapping, { ...pose, age_sec: .2 }, true, false);
  assert.equal(heading, .8);
  assert.equal(captureInitialMapYaw(heading, map("new", 8), mapping, { ...pose, yaw: -1.2, age_sec: 0 }, true, false), .8);
  assert.equal(captureInitialMapYaw(null, map("old", 9), mapping, { ...pose, age_sec: 0 }, true, false), null);
  assert.equal(captureInitialMapYaw(null, map("new", 1), mapping, { ...pose, age_sec: 0 }, true, true), null);
});

test("slow map polling never overlaps; failure retains the map and subsequent success clears stale error", async () => {
  const gate = new MapSessionGate(); gate.changeSession("current");
  const valid = (revision: number) => ({ ...map("current", revision), info: { width: 1, height: 1, resolution: .05, origin: { x: 0, y: 0, yaw: 0 } }, data: [0] } as MapSnapshot);
  let retained = valid(4), error = "", calls = 0, resolve!: (value: MapSnapshot) => void, reject!: (error: Error) => void;
  const timers: Array<() => void> = [], delays: number[] = [];
  const stop = startMapPolling({
    request: () => { calls++; return new Promise((yes, no) => { resolve = yes; reject = no; }); }, gate,
    current: () => retained, receive: value => { retained = value; }, failed: value => { error = value; },
  }, { now: () => 0, later: (callback, delay) => { timers.push(callback); delays.push(delay); return callback; }, cancel: () => { timers.length = 0; } });
  assert.equal(calls, 1); assert.equal(timers.length, 0);
  reject(new Error("temporary network failure")); await new Promise(done => setImmediate(done));
  assert.equal(retained.revision, 4); assert.equal(error, "temporary network failure"); assert.equal(delays[0], 500);
  timers.shift()!(); assert.equal(calls, 2); assert.equal(timers.length, 0);
  resolve(valid(5)); await new Promise(done => setImmediate(done));
  assert.equal(retained.revision, 5); assert.equal(error, "");
  stop(); assert.equal(timers.length, 0);
});
