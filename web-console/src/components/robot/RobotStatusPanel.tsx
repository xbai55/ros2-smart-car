import { Battery, Gauge, Navigation, ShieldCheck, Zap } from "lucide-react";
import type { Robot } from "../../types/domain";
import type { RobotStatus } from "../../robotApi";
import { LIVE_ROBOT_ID, MODE_LABELS } from "../../liveControl";
import { cn } from "../../lib/cn";
export function RobotStatusPanel({robot,live,connected,className}:{robot:Robot;live:RobotStatus|null;connected:boolean;className?:string}) {
  const bound=robot.id===LIVE_ROBOT_ID,online=bound&&connected&&live;
  const labels:Record<string,string>={...MODE_LABELS,transport:"运输",patrol:"巡检"};
  const battery=bound?(online?live.battery:null):robot.battery;
  const mode=bound?(online?labels[live.mode]??live.mode:"—"):labels[robot.mode]??robot.mode;
  const speed=bound?(online?Math.round(live.speed_scale*100)+"%":"—"):robot.speed+"%";
  const distance=bound?(online?live.front_distance:null):robot.frontDistance;
  return <div className={cn("robot-status-panel",className)}>
    <div className="rsp-head"><div className="rsp-identity"><span className={cn("rsp-avatar",online?"online":"offline")}><Battery size={16}/></span><div><strong>{robot.name}</strong><em>{bound?"实车 · r-001":robot.zone+" · 未绑定"}</em></div></div><span className={cn("rsp-online",online?"on":"off")}>{!bound?"未绑定":online?"实时在线":"未连接"}</span></div>
    <div className="rsp-grid">
      <div className="rsp-item"><span className="rsp-icon"><Zap size={15}/></span><div><em>当前模式</em><strong>{mode}</strong></div></div>
      <div className="rsp-item"><span className="rsp-icon"><Gauge size={15}/></span><div><em>速度比例</em><strong>{speed}</strong></div></div>
      <div className="rsp-item"><span className="rsp-icon"><Navigation size={15}/></span><div><em>前方距离</em><strong>{distance==null?"—":distance.toFixed(2)+" m"}</strong></div></div>
      <div className="rsp-item"><span className="rsp-icon"><ShieldCheck size={15}/></span><div><em>急停状态</em><strong className={online&&live.emergency_stop?"danger":""}>{online?(live.emergency_stop?"锁定中":"未锁定"):"—"}</strong></div></div>
    </div><div className="rsp-battery"><span>电量</span><div className="rsp-battery-track"><div className="rsp-battery-fill" style={{width:`${battery??0}%`}}/></div><strong>{battery==null?"—":battery+"%"}</strong></div>
    {bound&&battery==null&&<div className="rsp-note">车端尚未提供电池测量值</div>}
  </div>;
}
