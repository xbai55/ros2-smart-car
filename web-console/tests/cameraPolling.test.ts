import assert from "node:assert/strict";
import test from "node:test";
import { startCameraPolling } from "../src/cameraPolling";

const pause = (ms = 8) => new Promise(resolve => setTimeout(resolve, ms));
const frame = new Blob(["jpeg"], { type: "image/jpeg" });

test("slow fetch and decoding never overlap with the next frame request", async () => {
  let calls = 0, fetched!: (value: Blob) => void, decoded!: () => void;
  const polling = startCameraPolling({
    intervalMs: 1, timeoutMs: 1000,
    fetchFrame: () => { calls++; return new Promise(resolve => { fetched = resolve; }); },
    display: () => new Promise(resolve => { decoded = resolve; }), onState() {},
  });
  try {
    await pause();
    assert.equal(calls, 1);
    await pause(15);
    assert.equal(calls, 1);
    fetched(frame);
    await pause();
    assert.equal(calls, 1);
    decoded();
    await pause();
    assert.equal(calls, 2);
  } finally { polling.stop(); }
});

test("an obsolete request completing after stop cannot display an old image", async () => {
  let fetched!: (value: Blob) => void, displayed = 0;
  const polling = startCameraPolling({
    fetchFrame: () => new Promise(resolve => { fetched = resolve; }),
    display: async () => { displayed++; }, onState() {},
  });
  await pause();
  polling.stop();
  fetched(frame);
  await pause();
  assert.equal(displayed, 0);
});

test("hidden tab cancels transport and resumes with a new request", async () => {
  let calls = 0, latestSignal!: AbortSignal;
  const states: string[] = [];
  const polling = startCameraPolling({
    visible: false, intervalMs: 1, retryMs: 1,
    fetchFrame: signal => {
      calls++; latestSignal = signal;
      return new Promise((_, reject) => signal.addEventListener("abort", () => reject(new Error("aborted"))));
    },
    display: async () => {}, onState: value => states.push(value),
  });
  try {
    await pause();
    assert.equal(calls, 0);
    polling.setVisible(true);
    await pause();
    assert.equal(calls, 1);
    polling.setVisible(false);
    assert.equal(latestSignal.aborted, true);
    await pause();
    assert.equal(calls, 1);
    polling.setVisible(true);
    await pause();
    assert.equal(calls, 2);
    assert.equal(states.includes("connected"), false);
  } finally { polling.stop(); }
});

test("timeout aborts a stuck frame and retries without treating it as live", async () => {
  let calls = 0, aborted = 0;
  const states: string[] = [];
  const polling = startCameraPolling({
    timeoutMs: 10, retryMs: 3,
    fetchFrame: signal => {
      calls++;
      return new Promise((_, reject) => signal.addEventListener("abort", () => { aborted++; reject(new Error("timeout")); }));
    },
    display: async () => { throw new Error("must not display"); }, onState: state => states.push(state),
  });
  try {
    await pause(38);
    assert.ok(calls >= 2);
    assert.ok(aborted >= 1);
    assert.ok(states.includes("error"));
    assert.ok(!states.includes("connected"));
  } finally { polling.stop(); }
});

test("temporary camera failure recovers only after a new image is decoded", async () => {
  let calls = 0, displayed = 0;
  const states: string[] = [];
  const polling = startCameraPolling({
    intervalMs: 2, retryMs: 2,
    fetchFrame: async () => { if (++calls === 1) throw new Error("503"); return frame; },
    display: async () => { displayed++; }, onState: state => states.push(state),
  });
  try {
    await pause(25);
    assert.equal(states[0], "error");
    assert.ok(states.includes("connected"));
    assert.ok(displayed > 0);
  } finally { polling.stop(); }
});
