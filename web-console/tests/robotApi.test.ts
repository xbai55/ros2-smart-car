import assert from "node:assert/strict";
import test from "node:test";

import { createRobotApi, statusSocketUrl } from "../src/robotApi.ts";

test("manual commands and key release use the same driving identity with increasing sequence", async () => {
  const bodies: unknown[] = [];
  const api = createRobotApi(async (_url, init) => {
    const body = JSON.parse(String(init?.body));
    bodies.push(body);
    return Response.json(body.mode === "manual" ? { ok: true, drive_id: "drive", motion_epoch: "m", command_valid_until: 1234 } : { ok: true });
  });
  await assert.rejects(api.sendCommand("forward"), /请先选择/);
  await api.setMode("manual");
  await api.sendCommand("forward");
  await api.sendCommand("stop");
  await api.sendCommand("turn_l");
  await api.setMode("stop");
  await assert.rejects(api.sendCommand("forward"), /请先选择/);
  const clientId = (bodies[0] as {client_id: string}).client_id;
  assert.equal(typeof clientId, "string");
  assert.deepEqual(bodies, [
    { mode: "manual", client_id: clientId }, { command: "forward", drive_id: "drive", drive_seq: 1 },
    { command: "stop", drive_id: "drive", drive_seq: 2 }, { command: "turn_l", drive_id: "drive", drive_seq: 3 },
    { mode: "stop" },
  ]);
});

test('vision search uses dedicated endpoints and propagates task identifiers', async()=>{
  const calls:{url:string;body:unknown}[]=[];
  const api=createRobotApi(async(url,init)=>{
    calls.push({url:String(url),body:init?.body?JSON.parse(String(init.body)):null});
    return new Response(JSON.stringify({state:'searching',run_id:'run'}),{headers:{'content-type':'application/json'}});
  });
  await api.getVision(); await api.startSearch({targets:[{name:'服务器',prompt:'server rack'}],travel:'auto'});
  await api.searchAction('run','cancel');
  assert.equal(calls[0].url,'/api/vision/status');
  assert.equal(calls[1].url,'/api/search/start');
  assert.deepEqual(calls[2],{url:'/api/search/action',body:{run_id:'run',action:'cancel'}});
});

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
  assert.equal(JSON.parse(String(calls[0].init?.body)).mode, "manual");
  assert.equal(typeof JSON.parse(String(calls[0].init?.body)).client_id, "string");
  assert.equal(calls[1].url, "/api/speed");
  assert.deepEqual(JSON.parse(String(calls[1].init?.body)), { scale: 0.35 });
});

test("status websocket follows the page protocol and host", () => {
  assert.equal(statusSocketUrl({ protocol: "http:", host: "192.168.1.104:8080" }), "ws://192.168.1.104:8080/ws/status");
  assert.equal(statusSocketUrl({ protocol: "https:", host: "car.example" }), "wss://car.example/ws/status");
});

test("robot API fetches latest occupancy grid map", async () => {
  const calls: string[] = [];
  const api = createRobotApi(async (url) => {
    calls.push(String(url));
    return new Response(JSON.stringify({
      header: { frame_id: "map", stamp: { sec: 1, nanosec: 2 } },
      info: { width: 2, height: 2, resolution: 0.05, origin: { x: 0, y: 0, yaw: 0 } },
      data: [-1, 0, 50, 100],
      updated_at: 1
    }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  });

  const map = await api.getMap();

  assert.deepEqual(calls, ["/api/map"]);
  assert.equal(map.header.frame_id, "map");
  assert.deepEqual(map.data, [-1, 0, 50, 100]);
});

test("robot API requests mapping restart", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const api = createRobotApi(async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ ok: true, pid: 1234, message: "slam_toolbox restarted" }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  });

  const result = await api.restartMapping();

  assert.equal(calls[0].url, "/api/mapping/restart");
  assert.equal(calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {});
  assert.equal(result.pid, 1234);
});

test("robot API requests mapping save", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const api = createRobotApi(async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({
      ok: true,
      message: "map saved",
      yaml_path: "/tmp/map.yaml",
      pgm_path: "/tmp/map.pgm"
    }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  });

  const result = await api.saveMapping();

  assert.equal(calls[0].url, "/api/mapping/save");
  assert.equal(calls[0].init?.method, "POST");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), {});
  assert.equal(result.yaml_path, "/tmp/map.yaml");
});

test("robot API posts per-mode obstacle stop distance payloads", async () => {
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const api = createRobotApi(async (url, init) => {
    calls.push({ url: String(url), init });
    return new Response(JSON.stringify({ mode_obstacle_stop_distances: { mapping: 0.6 } }), {
      status: 200,
      headers: { "content-type": "application/json" }
    });
  });

  await api.setModeObstacleStopDistance("mapping", 0.6);

  assert.equal(calls[0].url, "/api/mode-obstacle-stop-distance");
  assert.deepEqual(JSON.parse(String(calls[0].init?.body)), { mode: "mapping", distance: 0.6 });
});

test("navigation preview drains old driving requests and fences delayed stops", async () => {
  const calls: string[] = [];
  let complete!: (r: Response) => void;
  const api = createRobotApi(async (url, init) => {
    calls.push(String(url));
    if(String(url).endsWith('/mode')) return Response.json({drive_id:'old'});
    if(String(url).endsWith('/command')) return new Promise<Response>(resolve=>{complete=resolve;});
    return Response.json({plan_id:'plan'});
  });
  await api.setMode('manual');
  const driving=api.sendCommand('forward');
  const preview=api.planNavigation({x:0,y:0,yaw:0},'map',[]);
  await api.sendCommand('stop');
  assert.equal(calls.filter(x=>x.endsWith('/command')).length,1);
  assert.equal(calls.some(x=>x.endsWith('/plan')),false);
  complete(Response.json({ok:true}));
  await driving; await preview;
  await api.sendCommand('stop');
  await api.startNavigation('plan');
  assert.equal(calls.filter(x=>x.endsWith('/command')).length,1);
  assert.equal(calls.at(-1),'/api/navigation/start');
});
