import type { ManagedMap } from "./services/businessApi";
import type { MapSnapshot } from "./robotApi";
import { mapKey, sameDrawing, type Calibration, type Point } from "./labNavigation";
import { mapWorldToScreen } from "./liveControl";
import { savedSlamAnchors } from "./slamMapSelection";

// Use map metadata, never human-picked drawing correspondences. Reuse the
// vehicle's checked registration protocol so existing deployed vehicles work.
export function directSlamRegistration(saved: ManagedMap | undefined, live: MapSnapshot | null): Calibration | null {
  if (!live) return null;
  const { width, height, resolution: r, origin: o } = live.info;
  if (!live.session_id || !live.header?.frame_id || ![width,height,r,o.x,o.y,o.yaw].every(Number.isFinite) || width <= 0 || height <= 0 || r <= 0) return null;
  const asset: ManagedMap = saved || {
    id:`live-slam:${live.asset_digest || live.session_id}`,name:"当前 SLAM 地图",width,height,resolution:r,origin:[o.x,o.y,o.yaw],
    floor:"",description:"",active:true,image_url:null,created_at:"",updated_at:null,
    metadata:{source:"slam",session_id:live.session_id,frame_id:live.header.frame_id,digest:live.asset_digest},
  };
  const anchors=savedSlamAnchors(asset,live);
  if (!anchors) return null;
  const [ox,oy,yaw]=asset.origin!, c=Math.cos(yaw), s=Math.sin(yaw), cell=asset.resolution!;
  return { map_key:mapKey(live),drawing:{id:asset.id,name:asset.name,kind:"uploaded",width:asset.width,height:asset.height,
    ...(asset.image_key ? {revision:asset.image_key} : {})},
    matrix:[c*cell,s*cell,ox-s*asset.height*cell,s*cell,-c*cell,oy+c*asset.height*cell],anchors };
}

export function matchesDirectRegistration(actual: Calibration | null, expected: Calibration | null) {
  return !!actual && !!expected && !actual.invalidated && actual.map_key===expected.map_key &&
    sameDrawing(actual.drawing,expected.drawing!) && actual.matrix.length===6 &&
    actual.matrix.every((v,i)=>Number.isFinite(v)&&Math.abs(v-expected.matrix[i])<1e-8);
}

export function directPointError(map: MapSnapshot, world: Point): string | null {
  if (![world.x,world.y].every(Number.isFinite)) return "目标坐标无效";
  const p=mapWorldToScreen(map,{...world,yaw:0});
  const x=Math.floor(p.x),y=Math.floor(map.info.height-p.y);
  if(x<0||y<0||x>=map.info.width||y>=map.info.height) return "请选择 SLAM 地图范围内的位置";
  const value=map.data[y*map.info.width+x];
  if(value===undefined||value<0) return "该位置尚未被雷达确认，请选择已知空地";
  if(value>=25) return "该位置为障碍或低可信区域，请选择附近空地";
  return null;
}
