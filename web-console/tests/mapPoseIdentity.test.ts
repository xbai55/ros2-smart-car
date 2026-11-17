import test from 'node:test';
import assert from 'node:assert/strict';
import {mapPoseMatchesSnapshot} from '../src/mapSession';
import type {MapSnapshot,MapPose} from '../src/robotApi';
test('only finite valid poses of the same map and session are drawn',()=>{
 const map={header:{frame_id:'map'},session_id:'s',asset_digest:'a'} as MapSnapshot;
 const p={ok:true,x:1,y:2,yaw:0,frame_id:'map',map_session_id:'s',asset_digest:'a',age_sec:.1} as MapPose;
 assert.equal(mapPoseMatchesSnapshot(map,p),true);
 for(const bad of [{ok:false},{x:NaN},{yaw:Infinity},{frame_id:'odom'},{map_session_id:'old'},{asset_digest:'old'},{age_sec:2}])assert.equal(mapPoseMatchesSnapshot(map,{...p,...bad}),false);
});
