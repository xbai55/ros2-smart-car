import type { ManagedMap } from "./services/businessApi";
import type { MapSnapshot } from "./robotApi";
import type { CalibrationPair } from "./labNavigation";

// A saved grid has an exact pixel-to-world transform, but it is only reusable
// automatically while the live map belongs to the same SLAM coordinate session.
export function savedSlamAnchors(saved: ManagedMap | undefined, live: MapSnapshot | null): CalibrationPair[] | null {
  if (!saved || !live || saved.metadata.source!=="slam") return null;
  const loaded = !!live.asset_digest && live.asset_digest === saved.metadata.digest;
  const frame=live.header?.frame_id,savedFrame=saved.metadata.frame_id;
  // Legacy imported files may have no recorded frame/session. A verified loaded
  // digest establishes their identity; an explicit conflicting frame never does.
  if (!frame || savedFrame && savedFrame!==frame || !loaded && savedFrame!==frame) return null;
  if (!loaded && (!live.session_id || saved.metadata.session_id!==live.session_id)) return null;
  const r=saved.resolution, origin=saved.origin;
  if (!r || !Number.isFinite(r) || r<=0 || !origin || origin.length!==3 || !origin.every(Number.isFinite) || saved.width<=0 || saved.height<=0) return null;
  const [ox,oy,yaw]=origin,c=Math.cos(yaw),s=Math.sin(yaw);
  return [[0,0],[saved.width,0],[0,saved.height],[saved.width,saved.height]].map(([x,y])=>{
    const gx=x*r,gy=(saved.height-y)*r;
    return {drawing:{x,y},world:{x:ox+c*gx-s*gy,y:oy+s*gx+c*gy}};
  });
}
