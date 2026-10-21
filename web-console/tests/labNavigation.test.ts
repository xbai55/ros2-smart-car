import assert from "node:assert/strict";
import test from "node:test";
import { DEFAULT_PLACES, LAB, LAB_BARRIERS, validDrawingPoint, planDrawingPath, distanceToSegment, drawingToWorld, worldToDrawing, drawingYawToWorld, mapScreenToWorld, mapKey } from "../src/labNavigation.ts";
import { createRobotApi, type MapSnapshot } from "../src/robotApi.ts";

test("teacher and door stops are in free space; benches and podium reject clicks", () => {
  for (const place of DEFAULT_PLACES) assert.equal(validDrawingPoint(place.drawing), true);
  for (const p of [{x:400,y:165},{x:400,y:187},{x:912,y:150},{x:400,y:398},{x:0,y:100}]) assert.equal(validDrawingPoint(p), false);
});
test("sketch route goes around the bench ends without crossing obstacles", () => {
  const route=planDrawingPath(LAB.door,{x:350,y:75});
  assert.ok(route.length>2);
  assert.ok(route.some(p=>p.x>940));
  for(let i=1;i<route.length;i++) for(let t=0;t<=1;t+=.025) {
    const a=route[i-1],b=route[i],p={x:a.x+(b.x-a.x)*t,y:a.y+(b.y-a.y)*t};
    for(const [c,d] of LAB_BARRIERS) assert.ok(distanceToSegment(p,c,d)>17);
  }
  assert.deepEqual(planDrawingPath(LAB.door,{x:400,y:398}),[]);
});
test("affine transform inverts rotated coordinates and teacher orientation",()=>{
  const matrix=[0,-.01,4,-.01,0,12],p={x:1015,y:180};
  const inverse=worldToDrawing(drawingToWorld(p,matrix),matrix);
  assert.ok(Math.hypot(inverse.x-p.x,inverse.y-p.y)<1e-8);
  assert.ok(Math.abs(drawingYawToWorld(Math.PI,matrix)-Math.PI/2)<1e-8);
});
test("screen map coordinates handle origin yaw and stable calibration key",()=>{
  const map={header:{frame_id:"map"},info:{width:100,height:80,resolution:.05,origin:{x:1,y:2,yaw:Math.PI/2}}} as MapSnapshot;
  const p=mapScreenToWorld(map,{x:20,y:40});
  assert.ok(Math.abs(p.x+1)<1e-8);assert.ok(Math.abs(p.y-3)<1e-8);
  assert.equal(mapKey(map),"map:100:80:0.050000:1.000000:2.000000:1.570796");
});
test("preview only sends a planning request; navigation starts with its plan id",async()=>{
  const requests:Array<{url:string,body:unknown}>=[];
  const api=createRobotApi(async(url,init)=>{requests.push({url:String(url),body:JSON.parse(String(init?.body))});return new Response(JSON.stringify({ok:true}));});
  await api.planNavigation({x:2,y:3,yaw:1},"map-key",[1,0,0,0,1,0]);
  assert.deepEqual(requests,[{url:"/api/navigation/plan",body:{goal:{x:2,y:3,yaw:1},map_key:"map-key",calibration_matrix:[1,0,0,0,1,0]}}]);
  await api.startNavigation("preview-id");
  assert.deepEqual(requests[1],{url:"/api/navigation/start",body:{plan_id:"preview-id"}});
});
