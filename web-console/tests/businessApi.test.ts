import test from "node:test";
import assert from "node:assert/strict";
import { businessApi, clearBusinessSession, createMapRequestId, getBusinessSession, imagePoint } from "../src/services/businessApi.ts";

const token = (access = "test-access") => ({ access_token: access, refresh_token: "test-refresh", user: { id: "u1", username: "operator", display_name: "操作员", role: { name: "operator", permissions: [{ name: "maps.manage" }] } } });
const response = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });

test("map save request IDs remain valid UUIDs on plain LAN HTTP without randomUUID",()=>{
  const a=createMapRequestId(),b=createMapRequestId();
  assert.match(a,/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.notEqual(a,b);
});

test("SLAM save reuses request id and selection persists through the business API", async()=>{
  const original=globalThis.fetch,calls:Array<{path:string;options?:RequestInit}>=[];
  globalThis.fetch=async(path,options)=>{calls.push({path:String(path),options});return String(path).endsWith("/login")?response(token()):response({id:"m1",map_id:"m1"});};
  try {
    await businessApi.login("operator","password");
    const input={request_id:"same-retry-id",robot_id:"r-001",name:"SLAM",floor:"1F",description:""};
    await businessApi.saveSlamMap(input);await businessApi.saveSlamMap(input);await businessApi.selectMap("m1");
    assert.equal(calls[1].path,"/api/v1/maps/slam");
    assert.equal(JSON.parse(String(calls[2].options?.body)).request_id,"same-retry-id");
    assert.equal(calls[3].path,"/api/v1/maps/m1/select");
    assert.equal(new Headers(calls[3].options?.headers).get("Authorization"),"Bearer test-access");
  } finally {clearBusinessSession();globalThis.fetch=original;}
});

test("map requests carry login token and deletion handles an empty response", async () => {
  const original = globalThis.fetch;
  const calls: Array<{ path: string; options?: RequestInit }> = [];
  globalThis.fetch = async (path, options) => { calls.push({ path: String(path), options }); return String(path).endsWith("/login") ? response(token()) : options?.method === "DELETE" ? new Response(null, { status: 204 }) : response([]); };
  try {
    await businessApi.login("operator", "password");
    await businessApi.listMaps();
    await businessApi.deleteMap("map/one");
    assert.equal(calls[1].path, "/api/v1/maps");
    assert.equal(new Headers(calls[1].options?.headers).get("Authorization"), "Bearer test-access");
    assert.equal(calls[2].path, "/api/v1/maps/map%2Fone");
  } finally { clearBusinessSession(); globalThis.fetch = original; }
});

test("expired access token refreshes once for simultaneous map queries", async () => {
  const original = globalThis.fetch;
  let refreshes = 0;
  globalThis.fetch = async (path, options) => {
    if (String(path).endsWith("/login")) return response(token());
    if (String(path).endsWith("/refresh")) { refreshes++; await new Promise(resolve => setTimeout(resolve, 5)); return response(token("renewed")); }
    return new Headers(options?.headers).get("Authorization") === "Bearer renewed" ? response([]) : response({ detail: { message: "expired" } }, 401);
  };
  try {
    await businessApi.login("operator", "password");
    await Promise.all([businessApi.listMaps(), businessApi.listPlaces("m1")]);
    assert.equal(refreshes, 1);
    assert.equal(getBusinessSession()?.access_token, "renewed");
  } finally { clearBusinessSession(); globalThis.fetch = original; }
});

test("permission error and invalid upload remain visible to the user", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async path => String(path).endsWith("/login") ? response(token()) : response({ detail: { code: "FORBIDDEN", message: "缺少地图管理权限" } }, 403);
  try {
    await businessApi.login("operator", "password");
    await assert.rejects(businessApi.deleteMap("m1"), /缺少地图管理权限/);
    await assert.rejects(businessApi.uploadMap(new File(["svg"], "map.svg", { type: "image/svg+xml" }), "地图", "1F", ""), /PNG/);
    assert.ok(getBusinessSession());
  } finally { clearBusinessSession(); globalThis.fetch = original; }
});

test("saved positions use image bounds including after edge rounding", () => {
  assert.deepEqual(imagePoint(120.56789, 25.12345, 160, 90), { x: 120.568, y: 25.123 });
  assert.deepEqual(imagePoint(159.99999, 89.99999, 160, 90), { x: 159.999, y: 89.999 });
  for (const [x, y] of [[160, 0], [-1, 20], [0, 90], [NaN, 10]]) assert.equal(imagePoint(x, y, 160, 90), null);
});

test("task creation saves both task types and reads returned business records", async () => {
  const original = globalThis.fetch;
  const calls: Array<{ path: string; options?: RequestInit }> = [];
  const saved = new Map<string, unknown[]>();
  globalThis.fetch = async (input, options) => {
    const path = String(input); calls.push({ path, options });
    if (path.endsWith("/login")) return response(token());
    if (path.endsWith("/robots")) return response([{ id: "database-robot", name: "已登记机器人", robot_code: "car-one", status: "offline" }]);
    if (options?.method === "POST") {
      assert.equal(new Headers(options.headers).get("Authorization"), "Bearer test-access");
      const payload = JSON.parse(String(options.body));
      assert.equal(Object.hasOwn(payload, "status"), false, "new tasks use the backend's initial status");
      const task = { ...payload, id: `saved-${saved.size}`, status: path.endsWith("/patrol-tasks") ? "pending" : "queued", progress: null, created_at: "2026-10-13T08:00:00Z", updated_at: null };
      saved.set(path, [task]);
      return response(task, 201);
    }
    return response(saved.get(path) || []);
  };
  try {
    await businessApi.login("operator", "password");
    const [robot] = await businessApi.listRobots();
    assert.equal(robot.id, "database-robot");
    const patrol = await businessApi.createPatrolTask({ name: "实验室巡检", description: "检查门窗", robot_id: robot.id, map_id: "map-one", route_id: "route-one", target_area: "一楼", priority: "high" });
    const mission = await businessApi.createMissionTask({ name: "报告运输", description: "交给老师", robot_id: null, map_id: null, route_id: null, cargo_name: "实验报告", start_location: "实验室", end_location: "办公室", pickup_code: "2468" });
    assert.equal(patrol.status, "pending");
    assert.equal(patrol.robot_id, "database-robot");
    assert.equal(patrol.priority, "high");
    assert.equal(mission.status, "queued");
    assert.equal(mission.start_location, "实验室");
    assert.equal(mission.end_location, "办公室");
    assert.deepEqual(await businessApi.listPatrolTasks(), [patrol]);
    assert.deepEqual(await businessApi.listMissionTasks(), [mission]);
    assert.equal(calls.filter(call => call.options?.method === "POST" && !call.path.endsWith("/login")).length, 2);
  } finally { clearBusinessSession(); globalThis.fetch = original; }
});

test("failed task creation keeps the backend error and permits a corrected retry", async () => {
  const original = globalThis.fetch;
  let attempts = 0;
  globalThis.fetch = async (input, options) => {
    if (String(input).endsWith("/login")) return response(token());
    attempts++;
    if (attempts === 1) return response({ detail: { code: "BAD_REQUEST", message: "机器人不存在" } }, 400);
    if (attempts === 2) return response({ detail: { code: "FORBIDDEN", message: "缺少任务管理权限" } }, 403);
    return response({ ...JSON.parse(String(options?.body)), id: "corrected-task", status: "pending" }, 201);
  };
  const payload = { name: "巡检", description: "", robot_id: null, map_id: null, route_id: null, target_area: "", priority: "normal" as const };
  try {
    clearBusinessSession();
    await assert.rejects(businessApi.createPatrolTask(payload), /登录/);
    await businessApi.login("operator", "password");
    await assert.rejects(businessApi.createPatrolTask({ ...payload, robot_id: "missing-robot" }), /机器人不存在/);
    await assert.rejects(businessApi.createPatrolTask(payload), /缺少任务管理权限/);
    assert.ok(getBusinessSession());
    assert.equal((await businessApi.createPatrolTask(payload)).id, "corrected-task");
  } finally { clearBusinessSession(); globalThis.fetch = original; }
});
