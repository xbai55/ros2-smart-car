import test from "node:test";
import assert from "node:assert/strict";
import { directPointError, directSlamRegistration, matchesDirectRegistration } from "../src/directSlamNavigation";
import { drawingToWorld, mapScreenToWorld } from "../src/labNavigation";
import type { MapSnapshot } from "../src/robotApi";
import type { ManagedMap } from "../src/services/businessApi";
const live={session_id:"current",header:{frame_id:"map"},info:{width:30,height:20,resolution:.05,origin:{x:-1,y:2,yaw:.6}},data:Array(600).fill(0)} as MapSnapshot;
const saved={id:"grid-1",name:"room",width:30,height:20,resolution:.05,origin:[-1,2,.6],image_key:"maps/version1.png",metadata:{source:"slam",session_id:"current",frame_id:"map",digest:"digest-1"}} as ManagedMap;
test("temporary SLAM uses exact grid metadata without an uploaded image or human anchors",()=>{
  const registration=directSlamRegistration(undefined,live)!;
  assert.ok(registration);assert.equal(registration.drawing!.kind,"uploaded");
  for(const p of [{x:0,y:0},{x:12,y:7},{x:30,y:20}]){
    const result=drawingToWorld(p,registration.matrix),expected=mapScreenToWorld(live,p);
    assert.ok(Math.hypot(result.x-expected.x,result.y-expected.y)<1e-10);
  }
});
test("saved map points survive grid growth but cannot cross map identities",()=>{
  assert.ok(directSlamRegistration(saved,{...live,info:{...live.info,width:60,height:50}}));
  assert.equal(directSlamRegistration(saved,{...live,session_id:"other"}),null);
  assert.ok(directSlamRegistration(saved,{...live,session_id:"loaded",asset_digest:"digest-1"}));
  assert.equal(directSlamRegistration(saved,{...live,session_id:"loaded",asset_digest:"wrong"}),null);
  assert.equal(directSlamRegistration({...saved,metadata:{...saved.metadata,source:"uploaded_image"}},live),null);
});
test("only the vehicle-confirmed matching coordinate transform enables planning",()=>{
  const expected=directSlamRegistration(saved,live)!;
  assert.equal(matchesDirectRegistration(null,expected),false);
  assert.equal(matchesDirectRegistration({...expected,matrix:expected.matrix.map(v=>v+1e-12)},expected),true);
  assert.equal(matchesDirectRegistration({...expected,invalidated:true},expected),false);
  assert.equal(matchesDirectRegistration({...expected,map_key:"old-map"},expected),false);
  assert.equal(matchesDirectRegistration({...expected,matrix:[1,0,0,0,1,0]},expected),false);
});
test("legacy maps without session/frame need the verified loaded asset",()=>{
  const legacy={...saved,metadata:{source:"slam",digest:"digest-1",session_id:null,frame_id:null}};
  assert.equal(directSlamRegistration(legacy,live),null);
  assert.ok(directSlamRegistration(legacy,{...live,session_id:"localization",asset_digest:"digest-1"}));
  assert.equal(directSlamRegistration({...legacy,metadata:{...legacy.metadata,frame_id:"other"}},{...live,asset_digest:"digest-1"}),null);
});
test("direct picks reject unknown and occupied cells even on rotated maps",()=>{
  const p={x:12.5,y:12.5},world=mapScreenToWorld(live,p);
  assert.equal(directPointError(live,world),null);
  const index=7*30+12,data=[...live.data];data[index]=-1;
  assert.match(directPointError({...live,data},world)!,/尚未被雷达确认/);
  data[index]=100;assert.match(directPointError({...live,data},world)!,/障碍/);
  assert.match(directPointError(live,{x:100,y:100})!,/范围内/);
});
