import { ArrowUpRight, CheckCircle2, CircleStop, Map, RotateCcw, Save, TriangleAlert } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useRobotStream } from "../hooks/useRobotStream";
import { Link } from "../lib/router";
import { ObjectHeader } from "../components/shared";
import { Panel } from "../components/ui";
import { LiveConnectionBar, LiveFeedback } from "../components/robot/LiveFeedback";
import { LiveMapCanvas } from "../components/robot/LiveMapCanvas";
import { DrivePad } from "../components/robot/DrivePad";
import { MotionSettings } from "../components/robot/MotionSettings";
import { RadarPanel } from "../components/robot/RadarPanel";
import { RobotCamera } from "../components/robot/RobotCamera";
import { LIVE_ROBOT_ID, MAPPING_SPEED_MAX } from "../liveControl";
import { SaveSlamMapDialog } from "../components/maps/SaveSlamMapDialog";
const mappingRobot = { id: LIVE_ROBOT_ID, name: "智巡一号" };
export function SlamPage() {
  const robot=useRobotStream(),s=robot.status,online=robot.connection==="connected";
  const [restartOpen,setRestartOpen]=useState(false), dialog=useRef<HTMLElement>(null);
  const [saveOpen,setSaveOpen]=useState(false);
  useEffect(()=>{
    if(!restartOpen)return;
    const previous=document.activeElement as HTMLElement|null;
    const keys=(e:KeyboardEvent)=>{
      if(e.key==="Escape"){e.preventDefault();setRestartOpen(false);}
      if(e.key==="Tab"){
        const buttons=dialog.current?.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
        if(!buttons?.length)return;
        if(e.shiftKey&&document.activeElement===buttons[0]){e.preventDefault();buttons[buttons.length-1].focus();}
        else if(!e.shiftKey&&document.activeElement===buttons[buttons.length-1]){e.preventDefault();buttons[0].focus();}
      }
    };
    window.addEventListener("keydown",keys);
    return()=>{window.removeEventListener("keydown",keys);previous?.focus();};
  },[restartOpen]);
  const checks=[{label:"雷达扫描",ok:online&&s.lidar.ok,detail:s.lidar.message},{label:"里程计",ok:online&&s.odom.ok,detail:s.odom.message},{label:"坐标变换",ok:online&&s.tf.ok,detail:s.tf.message},{label:"实时地图",ok:online&&s.map.ok,detail:s.map.message}];
  const initializing=s.mapping.state==="starting"||s.mapping.state==="waiting_map";
  const ready=online&&!s.emergency_stop&&s.lidar.ok&&s.odom.ok&&s.tf.ok&&!robot.pending&&!initializing;
  const start=()=>{setRestartOpen(false);void robot.restartMapping();};
  return <div className="page sensor-page slam-page">
    <ObjectHeader kicker="Mapping / SLAM" title="SLAM 建图" subtitle="对照实时地图、摄像头画面与雷达扫描，低速探索环境并保存建图结果。" actions={<Link className="btn btn-outline" to="/maps"><Map size={15}/>地图管理 <ArrowUpRight size={14}/></Link>}/>
    <LiveConnectionBar/><LiveFeedback/>
    <div className="slam-actions">
      <button className="btn btn-primary" disabled={!ready} onClick={()=>s.map.ok?setRestartOpen(true):start()}><RotateCcw size={16}/>{robot.pending?"操作中…":s.map.ok?"重新建图":"开始建图"}</button>
      <button className="btn btn-outline" disabled={!online||robot.pending||s.mode!=="mapping"} onClick={()=>void robot.setMode("stop")}><CircleStop size={16}/>退出建图模式</button>
      <button className="btn btn-outline" disabled={!online||!s.map.ok||!robot.mapSnapshot||robot.pending} onClick={()=>setSaveOpen(true)}><Save size={16}/>保存地图</button>
      <span className="slam-step-hint">{s.mapping.state==="starting"?"正在启动建图进程，请保持静止":s.mapping.state==="waiting_map"?"等待雷达与坐标变换生成首张地图，请保持静止":s.mapping.state==="error"?`建图失败：${s.mapping.error||"请检查车端日志"}`:s.mode==="mapping"?`首张地图已就绪，再低速移动 · 速度上限 ${MAPPING_SPEED_MAX}%`:"开始建图前先检查雷达、里程计和坐标变换"}</span>
    </div>
    <div className="slam-health">{checks.map(c=><div className={c.ok?"healthy":"unhealthy"} key={c.label}>{c.ok?<CheckCircle2 size={17}/>:<TriangleAlert size={17}/>}<strong>{c.label}</strong><span>{c.ok?"正常":c.detail==="no_data"||c.detail==="no_map"||c.detail==="no_odom"?"等待数据":"未就绪"}</span></div>)}</div>
    {!ready&&<p className="slam-block-reason">{s.emergency_stop?"急停锁定中，请先解除急停。":!online?"连接小车后可启动建图。":robot.pending?"正在处理操作。":initializing?"首张地图未就绪，请保持静止。":"启动条件未满足："+checks.slice(0,3).filter(c=>!c.ok).map(c=>c.label).join("、")+"。"}</p>}
    <div className="slam-workspace"><Panel title="环境地图" kicker="Live Occupancy Grid" className="sensor-main" bodyClassName="panel-flush"><LiveMapCanvas/><div className="map-measurements"><span>地图坐标 <strong>{online&&s.map_pose.ok?`X ${s.map_pose.x.toFixed(2)} / Y ${s.map_pose.y.toFixed(2)} m`:"—"}</strong></span><span>朝向 <strong>{online&&s.map_pose.ok?(s.map_pose.yaw*180/Math.PI).toFixed(1)+"°":"—"}</strong></span><span>建图链路 <strong>{online&&s.mapping_quality.ok?"正常":"待检查"}</strong></span></div></Panel>
      <aside className="slam-side" aria-label="建图现场观察与遥控">
        <RobotCamera robot={mappingRobot} className="slam-camera" />
        <Panel title="建图遥控" kicker="Hold to Drive"><DrivePad/></Panel>
      </aside>
      <RadarPanel className="slam-radar-panel" />
    </div>
    <div className="slam-controls">
      <Panel title="运动参数" kicker="Low Speed Mapping" bodyClassName="panel-flush"><MotionSettings compact mappingControls/></Panel>
    </div>
    {robot.savedMap&&<section className="saved-map-result" role="status"><CheckCircle2 size={21}/><div><strong>{robot.savedMap.name || "SLAM 地图"}已保存到地图管理</strong>{robot.savedMap.map_id&&<Link to={`/maps/${robot.savedMap.map_id}`}>查看与选用地图</Link>}<span>地图配置：{robot.savedMap.yaml_path}</span><span>栅格图像：{robot.savedMap.pgm_path}</span></div></section>}
    {saveOpen&&<SaveSlamMapDialog onClose={()=>setSaveOpen(false)} onSave={robot.saveMapping} error={robot.error}/>}
    {restartOpen&&<div className="live-modal-backdrop"><section ref={dialog} role="dialog" aria-modal="true" aria-labelledby="restart-title" className="live-confirm"><h2 id="restart-title">重新开始建图？</h2><p>当前实时地图将重新初始化。已有保存文件会保留，尚未保存的结果请先保存。</p><div><button autoFocus className="btn btn-outline" onClick={()=>setRestartOpen(false)}>取消</button><button className="btn btn-primary" onClick={start}>确认重新建图</button></div></section></div>}
  </div>;
}
