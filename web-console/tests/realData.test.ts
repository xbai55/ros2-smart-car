import test from "node:test";
import assert from "node:assert/strict";
import { adapters } from "../src/services/adapters";
import { businessApi, clearBusinessSession } from "../src/services/businessApi";

test("configured physical identity never supplies invented telemetry", async () => {
  const robots = await adapters.listRobots();
  assert.equal(robots.length, 1);
  assert.equal(robots[0].id, "r-001");
  for (const field of ["battery", "speed", "position", "heading", "tasks", "incidents"] as const) assert.equal(robots[0][field], null);
  assert.equal(robots[0].health, "offline");
  assert.equal(await adapters.getRobot("r-002"), undefined);
});

test("missing login or failed API cannot become an empty successful business result", async () => {
  clearBusinessSession();
  await assert.rejects(adapters.listIncidents(), /登录/);
  const original = globalThis.fetch;
  globalThis.fetch = async input => new Response(JSON.stringify(String(input).endsWith("/login") ? { access_token: "test", refresh_token: "test", user: { id: "real-user", username: "operator" } } : { detail: "业务服务不可用" }), { status: String(input).endsWith("/login") ? 200 : 503 });
  try {
    await businessApi.login("operator", "test");
    await assert.rejects(adapters.listIncidents(), /业务服务不可用/);
    await assert.rejects(adapters.listTasks(), /业务服务不可用/);
  } finally { globalThis.fetch = original; clearBusinessSession(); }
});

test("records follow API updates and unprovided confidence stays unknown", async () => {
  const original = globalThis.fetch;
  let items: unknown[] = [];
  globalThis.fetch = async input => new Response(JSON.stringify(String(input).endsWith("/login") ? { access_token: "test", refresh_token: "test", user: { id: "real-user", username: "operator" } } : items));
  try {
    await businessApi.login("operator", "test");
    assert.deepEqual(await adapters.listIncidents(), []);
    items = [{ id: "actual-record", title: "现场记录", type: "obstacle", severity: "warning", status: "open", robot_id: null, location: "", created_at: "2026-10-13T04:00:00", description: "人工记录" }];
    const result = await adapters.listIncidents();
    assert.equal(result.length, 1); assert.equal(result[0].id, "actual-record"); assert.equal(result[0].confidence, null);
  } finally { globalThis.fetch = original; clearBusinessSession(); }
});

test("transport task status is preserved rather than inferred as vehicle execution", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async input => new Response(JSON.stringify(String(input).endsWith("/login") ? { access_token: "test", refresh_token: "test", user: { id: "real-user", username: "operator" } } : String(input).endsWith("/mission-tasks") ? [{ id: "actual-task", name: "业务任务", status: "dispatched", progress: null, robot_id: null, route_id: null, created_at: null, updated_at: null }] : []));
  try {
    await businessApi.login("operator", "test");
    const [task] = await adapters.listTasks();
    assert.equal(task.status, "dispatched"); assert.equal(task.progress, null); assert.equal(task.robotId, null);
  } finally { globalThis.fetch = original; clearBusinessSession(); }
});
