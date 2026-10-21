import { Crosshair, Pause, Play, Radar } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { useRobotStream } from "../../hooks/useRobotStream";
import { radarScreenPoint, validRadarPoints } from "../../liveControl";
import type { RadarPoint } from "../../robotApi";
export function RadarCanvas() {
  const {status,connection}=useRobotStream();
  const gridId=useId();
  const [range,setRange]=useState(3),[paused,setPaused]=useState(false),[frozen,setFrozen]=useState<RadarPoint[]>([]);
  const [selected,setSelected]=useState<RadarPoint|null>(null);
  useEffect(()=>{if(!paused)setFrozen(validRadarPoints(status.radar_points));},[status.radar_points,paused]);
  const current=paused?frozen:validRadarPoints(status.radar_points);
  const points=connection==="connected"&&status.lidar.ok?current:[];
  const threshold=status.mode_obstacle_stop_distances[status.mode]??0;
  const radius=Math.min(240,threshold/range*240),a=35*Math.PI/180;
  const sector=`M 300 300 L ${300-radius*Math.sin(a)} ${300-radius*Math.cos(a)} A ${radius} ${radius} 0 0 1 ${300+radius*Math.sin(a)} ${300-radius*Math.cos(a)} Z`;
  return <div className="radar-view">
    <div className="radar-toolbar"><span><Radar size={15}/>{paused?"显示已暂停":"实时二维点云"}</span><label>量程 <select aria-label="雷达显示量程" value={range} onChange={e=>setRange(Number(e.target.value))}>{[2,3,5,10].map(n=><option key={n} value={n}>{n} m</option>)}</select></label><button type="button" aria-pressed={paused} onClick={()=>setPaused(v=>!v)}>{paused?<Play size={14}/>:<Pause size={14}/>} {paused?"恢复显示":"暂停显示"}</button></div>
    <div className="radar-stage">
      <svg viewBox="0 0 600 600" role="img" aria-label="全周二维雷达点云，前方在上，左侧在左" className="radar-svg">
        <defs><pattern id={gridId} width="30" height="30" patternUnits="userSpaceOnUse"><path d="M 30 0 H 0 V 30" fill="none" stroke="#24364e" strokeWidth=".5"/></pattern></defs>
        <rect width="600" height="600" fill="#101b2b"/><rect width="600" height="600" fill={`url(#${gridId})`}/>
        <g className="radar-rings">{[.25,.5,.75,1].map(f=><g key={f}><circle cx="300" cy="300" r={240*f}/><text x="307" y={300-240*f+16}>{(range*f).toFixed(1)} m</text></g>)}{[0,45,90,135].map(angle=><line key={angle} x1={300-240*Math.cos(angle*Math.PI/180)} y1={300-240*Math.sin(angle*Math.PI/180)} x2={300+240*Math.cos(angle*Math.PI/180)} y2={300+240*Math.sin(angle*Math.PI/180)}/>)}</g>
        {radius>0&&<path d={sector} fill="rgba(239,68,68,.17)" stroke="#f87171" strokeWidth="1" strokeDasharray="5 4"/>}
        <text className="radar-direction" x="300" y="35" textAnchor="middle">前方 +X</text><text className="radar-direction" x="300" y="580" textAnchor="middle">后方 −X</text><text className="radar-direction" x="32" y="300" textAnchor="middle">左 +Y</text><text className="radar-direction" x="568" y="300" textAnchor="middle">右 −Y</text>
        <g>{points.filter(p=>p.distance<=range).map((p,i)=>{const s=radarScreenPoint(p,range);return <circle key={i} cx={s.x} cy={s.y} r="3" fill={p.distance<=threshold&&p.x>0&&Math.abs(Math.atan2(p.y,p.x))<=a?"#fb7185":"#59c7ff"} className="radar-point" onPointerEnter={()=>setSelected(p)} onPointerLeave={()=>setSelected(null)}><title>{`距离 ${p.distance.toFixed(2)} m · X ${p.x.toFixed(2)} · Y ${p.y.toFixed(2)}`}</title></circle>;})}</g>
        <circle cx="300" cy="300" r="18" fill="#172b46" stroke="#3985ff" strokeWidth="1.5"/><path d="M 300 287 L 307 308 L 300 304 L 293 308 Z" fill="#f8fbff"/>
      </svg>
      {!points.length&&<div className="radar-no-data"><Crosshair size={23}/><strong>{connection!=="connected"?"等待小车连接":"等待有效雷达扫描"}</strong><span>{status.lidar.message==="stale"?"雷达数据已超时":"有效数据到达后自动显示"}</span></div>}
      {selected&&<div className="radar-inspect">距离 {selected.distance.toFixed(2)} m · X {selected.x.toFixed(2)} · Y {selected.y.toFixed(2)}</div>}
    </div>
    <div className="radar-legend"><span><i className="legend-dot scan"/>扫描点</span><span><i className="legend-dot danger"/>前方停车区域 ±35°</span><span>显示暂停不影响小车运行</span></div>
  </div>;
}
