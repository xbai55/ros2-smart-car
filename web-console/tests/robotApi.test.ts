import assert from "node:assert/strict";
import test from "node:test";

import { createRobotApi, statusSocketUrl } from "../src/robotApi.ts";

test("robot API posts real mode and speed payloads", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const api = createRobotApi(async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  });

  await api.setMode("manual");
  await api.setSpeed(0.35);

  assert.equal(calls[0].url, "/api/mode");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { mode: "manual" });
  assert.equal(calls[1].url, "/api/speed");
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { scale: 0.35 });
});

test("status websocket follows the page protocol and host", () => {
  assert.equal(statusSocketUrl({ protocol: "http:", host: "192.168.1.104:8080" }), "ws://192.168.1.104:8080/ws/status");
  assert.equal(statusSocketUrl({ protocol: "https:", host: "car.example" }), "wss://car.example/ws/status");
});

