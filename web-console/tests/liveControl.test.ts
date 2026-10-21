import assert from "node:assert/strict";
import test from "node:test";
import { bindDriveStops, percentToScale, canDrive, driveKeyCommand, validThreshold, radarScreenPoint, validMap, mapWorldToScreen, DriveHoldController } from "../src/liveControl.ts";
import { initialRobotStatus, createRobotApi, type MapSnapshot } from "../src/robotApi.ts";

test("normal arrows drive while Alt arrows and protected editor focus cannot drive", () => {
  const event = { key: "ArrowUp", defaultPrevented: false, ctrlKey: false, metaKey: false, altKey: false };
  assert.equal(driveKeyCommand(event), "forward");
  assert.equal(driveKeyCommand({ ...event, altKey: true }), null);
  assert.equal(driveKeyCommand(event, true), null);
  assert.equal(driveKeyCommand({ ...event, defaultPrevented: true }), null);
  assert.equal(driveKeyCommand({ ...event, key: "Q" }), "turn_l");
  assert.equal(driveKeyCommand({ ...event, key: " " }), "stop");
});

test("percent speed conversion supports mapping at 50% and clamps higher requests",()=>{
  assert.equal(percentToScale(15),.15); assert.equal(percentToScale(25),.25);
  assert.equal(percentToScale(100),1); assert.equal(percentToScale(0),.15);
  assert.equal(percentToScale(101),1); assert.equal(percentToScale(NaN),.15);
  assert.equal(percentToScale(50,true),.5); assert.equal(percentToScale(35,true),.35);
  assert.equal(percentToScale(100,true),.5); assert.equal(percentToScale(15,true),.15);
});
test("only bound, connected, unlocked manual and mapping robots may drive",()=>{
  for(const mode of ["manual","mapping"]) {
    const s={...initialRobotStatus,mode};
    assert.equal(canDrive(s,true),true); assert.equal(canDrive(s,false),false);
    assert.equal(canDrive(s,true,"r-002"),false);
    assert.equal(canDrive({...s,emergency_stop:true},true),false);
  }
  for(const mode of ["stop","auto","navigation","color_track","object_follow"]) assert.equal(canDrive({...initialRobotStatus,mode},true),false);
  for (const state of ["starting", "waiting_map", "error"] as const) assert.equal(canDrive({ ...initialRobotStatus, mode: "mapping", mapping: { ...initialRobotStatus.mapping, state } }, true), false);
  assert.equal(canDrive({ ...initialRobotStatus, mode: "mapping", mapping: { ...initialRobotStatus.mapping, state: "ready" } }, true), true);
});
test("thresholds accept zero and reject malformed or out-of-range distances",()=>{
  for(const n of [0,.05,5]) assert.equal(validThreshold(n),true);
  for(const n of [-.05,5.05,NaN,Infinity]) assert.equal(validThreshold(n),false);
});
const flush=async()=>{await new Promise<void>(resolve=>setImmediate(resolve));};
function clock() {
  const callbacks=new Map<number,()=>void>(); let serial=0;
  return {every:(fn:()=>void,ms:number)=>{assert.equal(ms,180);callbacks.set(++serial,fn);return serial;},clear:(id:unknown)=>{callbacks.delete(id as number);},advance:()=>{for(const fn of callbacks.values())fn();},size:()=>callbacks.size};
}
test("hold sends immediately and every 180ms; release cancels repeat and sends stop",async()=>{
  const calls:string[]=[],c=clock(),hold=new DriveHoldController(async cmd=>{calls.push(cmd);return true;},c);
  hold.start("forward"); await flush(); c.advance(); await flush(); c.advance(); await flush();
  assert.deepEqual(calls,["forward","forward","forward"]); hold.stop(); await flush();
  const length=calls.length;c.advance();await flush();assert.equal(calls.length,length);assert.equal(calls.at(-1),"stop");assert.equal(c.size(),0);
});
test("focus loss, cancellation, page disposal and mode changes share immediate stop",async()=>{
  for(const event of ["blur","pointercancel","page-unmount","mode-change","robot-change"]) {
    const calls:string[]=[],c=clock(),hold=new DriveHoldController(async cmd=>{calls.push(cmd);return true;},c);
    hold.start("left");await flush();
    if(event==="page-unmount")hold.dispose();else hold.stop();
    await flush();c.advance();await flush();assert.deepEqual(calls,["left","stop"],event);
    if(event==="page-unmount"){hold.start("right");assert.deepEqual(calls,["left","stop"]);}
  }
});
test("a delayed movement response is followed by stop after release",async()=>{
  const calls:string[]=[],c=clock();let resolveMove!:(ok:boolean)=>void;
  const hold=new DriveHoldController(cmd=>{calls.push(cmd);return cmd==="stop"?Promise.resolve(true):new Promise(resolve=>{resolveMove=resolve;});},c);
  hold.start("backward");c.advance();assert.deepEqual(calls,["backward"]);
  hold.stop();assert.equal(calls.at(-1),"stop");resolveMove(true);await flush();
  assert.deepEqual(calls,["backward","stop","stop"]);assert.equal(c.size(),0);
});
test("browser safety events cancel real repeat timers, including hidden tabs and navigation",async()=>{
  for(const event of ["blur","pointerup","pointercancel","pagehide","hashchange","robot-control-stop","visibilitychange"]){
    const calls:string[]=[],c=clock(),hold=new DriveHoldController(async cmd=>{calls.push(cmd);return true;},c);
    const win=new EventTarget(),doc=Object.assign(new EventTarget(),{hidden:false});
    const unbind=bindDriveStops(win,doc,()=>hold.stop());
    hold.start("turn_l");await flush();
    if(event==="visibilitychange"){doc.hidden=true;doc.dispatchEvent(new Event(event));}else win.dispatchEvent(new Event(event));
    await flush();c.advance();await flush();assert.equal(c.size(),0,event);assert.equal(calls.at(-1),"stop",event);assert.equal(calls.filter(x=>x==="turn_l").length,1,event);
    unbind();hold.dispose();
  }
});
test("connection or request failure ends a held command",async()=>{
  for(const failure of ["false","throw"]) {
    const calls:string[]=[],c=clock(),hold=new DriveHoldController(async cmd=>{calls.push(cmd);if(cmd==="stop")return true;if(failure==="throw")throw Error("disconnect");return false;},c);
    hold.start("right");await flush();assert.equal(c.size(),0);assert.equal(calls.at(-1),"stop");c.advance();await flush();assert.equal(calls.filter(x=>x==="right").length,1);
  }
});
test("HTTP and logical parameter failures preserve the server reason",async()=>{
  for(const status of [200,400,503]) {
    const api=createRobotApi(async()=>new Response(JSON.stringify({ok:false,message:"threshold rejected"}),{status,headers:{"content-type":"application/json"}}));
    await assert.rejects(()=>api.setModeObstacleStopDistance("manual",.5),/threshold rejected/);
  }
});
test("full scan retains all four quadrants; rear points remain below the car",()=>{
  const coordinates=[[1,1],[1,-1],[-1,1],[-1,-1]];
  const projected=coordinates.map(([x,y])=>radarScreenPoint({x,y,distance:Math.sqrt(2)},3));
  assert.ok(projected[0].x<300&&projected[0].y<300);
  assert.ok(projected[1].x>300&&projected[1].y<300);
  assert.ok(projected[2].x<300&&projected[2].y>300);
  assert.ok(projected[3].x>300&&projected[3].y>300);
});
const map:MapSnapshot={header:{frame_id:"map",stamp:{sec:0,nanosec:0}},info:{width:4,height:6,resolution:.5,origin:{x:10,y:20,yaw:Math.PI/2}},data:Array(24).fill(0),updated_at:1};
test("map projection handles translated, rotated origins, resolution and screen Y",()=>{
  const p=mapWorldToScreen(map,{x:9,y:20.5,yaw:Math.PI});
  assert.ok(Math.abs(p.x-1)<1e-10);assert.ok(Math.abs(p.y-4)<1e-10);assert.ok(Math.abs(p.yawDeg+90)<1e-10);
  const origin=mapWorldToScreen(map,{...map.info.origin});assert.equal(origin.x,0);assert.equal(origin.y,6);assert.ok(Math.abs(origin.yawDeg)<1e-10);
});
test("invalid map shapes and dimensions cannot allocate a raster",()=>{
  assert.equal(validMap(map),true);assert.equal(validMap({} as MapSnapshot),false);
  assert.equal(validMap({...map,data:[]}),false);
  assert.equal(validMap({...map,info:{...map.info,resolution:0}}),false);
  assert.equal(validMap({...map,info:{...map.info,origin:{x:NaN,y:0,yaw:0}}}),false);
});
