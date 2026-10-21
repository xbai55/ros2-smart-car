import assert from "node:assert/strict";
import test from "node:test";
import { savedSlamAnchors } from "../src/slamMapSelection";
import { mapScreenToWorld } from "../src/labNavigation";
import type { ManagedMap } from "../src/services/businessApi";
import type { MapSnapshot } from "../src/robotApi";

const saved={id:"m1",name:"SLAM",width:30,height:20,resolution:.05,origin:[-1,2,.6],metadata:{source:"slam",session_id:"current",frame_id:"map"}} as ManagedMap;
const live={session_id:"current",header:{frame_id:"map"},info:{width:90,height:80,resolution:.05,origin:{x:-3,y:-2,yaw:0}}} as MapSnapshot;

test("saved metric map automatically restores its rotated world coordinates in the same session",()=>{
  const anchors=savedSlamAnchors(saved,live)!;
  assert.equal(anchors.length,4);
  const source={...live,info:{width:30,height:20,resolution:.05,origin:{x:-1,y:2,yaw:.6}}};
  for(const pair of anchors) assert.deepEqual(pair.world,mapScreenToWorld(source,pair.drawing));
});

test("another SLAM session or coordinate frame cannot be silently auto-registered",()=>{
  assert.equal(savedSlamAnchors(saved,{...live,session_id:"after-restart"}),null);
  assert.equal(savedSlamAnchors(saved,{...live,header:{frame_id:"other"}}),null);
  assert.equal(savedSlamAnchors({...saved,metadata:{...saved.metadata,source:"uploaded_image"}},live),null);
  assert.equal(savedSlamAnchors({...saved,origin:[0,NaN,0]},live),null);
});

test("a loaded asset recovers its coordinates only with a matching digest",()=>{
  const asset={...saved,metadata:{...saved.metadata,digest:"sha-verified"}};
  assert.equal(savedSlamAnchors(asset,{...live,session_id:"localization-session",asset_digest:"sha-verified"})?.length,4);
  assert.equal(savedSlamAnchors(asset,{...live,session_id:"localization-session",asset_digest:"different"}),null);
});
