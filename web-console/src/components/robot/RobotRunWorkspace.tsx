import { CircleStop, Gamepad2, Map, Navigation, Route } from "lucide-react";
import type { Robot } from "../../types/domain";
import { useRobotStream } from "../../hooks/useRobotStream";
import { LIVE_ROBOT_ID, COMMAND_LABELS } from "../../liveControl";
import { Link } from "../../lib/router";
import { LiveMapCanvas } from "./LiveMapCanvas";
import { RobotCamera } from "./RobotCamera";
import { DrivePad } from "./DrivePad";
import { MotionSettings } from "./MotionSettings";
import { LiveConnectionBar, LiveFeedback } from "./LiveFeedback";
import { cn } from "../../lib/cn";
import { useState } from "react";
import { NavigationWorkspace } from "./NavigationWorkspace";
const modes=[{id:"stop",label:"停止",icon:CircleStop},{id:"manual",label:"手动驾驶",icon:Gamepad2},{id:"auto",label:"自动避障",icon:Route},{id:"navigation",label:"导航",icon:Navigation}];
export function RobotRunWorkspace({robot}:{robot:Robot}) {
  const [mapView,setMapView]=useState<"lab"|"live">("lab");
  const live=useRobotStream(),s=live.status,bound=robot.id===LIVE_ROBOT_ID,online=bound&&live.connection==="connected";
  if(!bound)return <div className="unbound-robot"><Gamepad2 size={35}/><h3>未绑定实车连接</h3><p>尚未绑定实车连接，运动控制不可用。</p><Link to="/robots/r-001/run" className="btn btn-primary">进入智巡一号实车工作区</Link></div>;
  return <div className="live-run-workspace">
    <LiveConnectionBar/><LiveFeedback/>
    <div className="live-run-modes"><div>{modes.map(({id,label,icon:Icon})=><button type="button" key={id} disabled={(id!=="navigation"&&!online)||live.pending||(s.emergency_stop&&id!=="stop")} aria-pressed={s.mode===id} className={cn("btn",s.mode===id?"btn-primary":"btn-outline")} onClick={()=>{if(id==="navigation")setMapView("lab");else void live.setMode(id);}}><Icon size={15}/>{label}</button>)}</div><div><Link className="btn btn-outline" to="/slam"><Map size={15}/>SLAM 建图</Link></div></div>
    <div className="live-run-grid"><div className="live-run-map"><div className="navigation-view-switch"><button aria-pressed={mapView==="lab"} onClick={()=>setMapView("lab")}>地图与导航</button><button aria-pressed={mapView==="live"} onClick={()=>setMapView("live")}>SLAM 原始地图</button></div><div hidden={mapView!=="lab"}><NavigationWorkspace/></div>{mapView==="live"&&<LiveMapCanvas/>}<div className="live-run-telemetry">
      <Telemetry label="当前指令" value={online?COMMAND_LABELS[s.last_command]??s.last_command:"—"}/>
      <Telemetry label="控制输出 X / Y" value={online&&s.cmd_vel.ok?`${s.cmd_vel.linear_x.toFixed(3)} / ${s.cmd_vel.linear_y.toFixed(3)} m/s`:"—"}/>
      <Telemetry label="控制输出角速度" value={online&&s.cmd_vel.ok?s.cmd_vel.angular_z.toFixed(3)+" rad/s":"—"}/>
      <Telemetry label="前方距离" value={online&&s.front_distance!=null?s.front_distance.toFixed(2)+" m":"—"}/>
    </div><div className="live-odom-readout"><span>实测里程计速度 X：{online&&s.odom.ok?s.odom.linear_speed.toFixed(3)+" m/s":"—"}</span><span>实测角速度：{online&&s.odom.ok?s.odom.angular_speed.toFixed(3)+" rad/s":"—"}</span></div><MotionSettings compact/></div><aside className="live-run-side"><RobotCamera robot={robot}/><DrivePad robotId={robot.id}/></aside></div>
  </div>;
}
function Telemetry({label,value}:{label:string;value:string}) {return <div><span>{label}</span><strong>{value}</strong></div>;}
