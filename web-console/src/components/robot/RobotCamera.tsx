import { Camera, Video } from "lucide-react";
import { useCameraStream } from "../../hooks/useCameraStream";
import { cn } from "../../lib/cn";
import { LIVE_ROBOT_ID } from "../../liveControl";
import { useRobotStream } from "../../hooks/useRobotStream";
import type { Robot } from "../../types/domain";

export function RobotCamera({robot,className}:{robot:Pick<Robot,"id"|"name">;className?:string}) {
  const {connection}=useRobotStream(),bound=robot.id===LIVE_ROBOT_ID,online=bound&&connection==="connected";
  const {host,state,reconnect}=useCameraStream(bound);
  return <div className={cn("camera-workspace",className)}>
    <div className="camera-head"><div className="camera-title"><Camera size={15}/><span>实车视频</span><span className={cn("camera-state",bound&&state==="connected"?"connected":"error")}>{!bound?"未绑定":state==="connected"?"在线":!online?"离线":state==="error"?"无信号":"连接中"}</span></div><button className="camera-tool" disabled={!online} onClick={reconnect}><Video size={15}/>重连</button></div>
    <div className="camera-frame">
      <div ref={host} style={{position:"absolute",inset:0}} />
      {(!bound||state!=="connected")&&<div className="camera-fallback"><Camera size={30} strokeWidth={1.5}/><strong>{!bound?"未绑定实车摄像头":!online?"等待小车连接":state==="error"?"摄像头暂未提供画面":"正在连接视频流…"}</strong><span>{bound?"真实摄像头画面":"未配置实车视频连接"}</span></div>}
      <div className="camera-badge"><span className={cn("camera-badge-dot",bound&&state==="connected"&&"live")}/>{robot.name} · 摄像头</div>
    </div><div className="camera-strip"><span className="camera-strip-hint">实时摄像头视频</span></div>
  </div>;
}
