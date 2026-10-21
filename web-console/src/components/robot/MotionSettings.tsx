import { Check, Gauge, ShieldCheck } from "lucide-react";
import { useEffect, useState } from "react";
import { useRobotStream } from "../../hooks/useRobotStream";
import { LIVE_ROBOT_ID, MAPPING_SPEED_MAX, MAPPING_SPEED_PRESETS, MODE_LABELS, validThreshold } from "../../liveControl";
import { MAPPING_RANGE_PRESETS, TURN_SPEED_PRESETS, validTurnSpeed } from "../../mappingSettings";
export function MotionSettings({ robotId = LIVE_ROBOT_ID, compact = false, mappingControls = false }: {robotId?:string;compact?:boolean;mappingControls?:boolean}) {
  const robot = useRobotStream();
  const connected = robot.connection==="connected" && robotId===LIVE_ROBOT_ID;
  const mapping = robot.status.mode==="mapping";
  const [speed,setSpeed] = useState(Math.round(robot.status.speed_scale*100));
  const [mode,setMode] = useState(robot.status.mode==="stop" ? "manual" : robot.status.mode);
  const actual = robot.status.mode_obstacle_stop_distances[mode] ?? 0;
  const [distance,setDistance] = useState(actual.toFixed(2));
  const configuredTurn = robot.status.motion_settings?.turn_speed ?? 0.15;
  const configuredRange = robot.status.motion_settings?.max_laser_range ?? 3;
  const [turn,setTurn] = useState(configuredTurn.toFixed(2));
  const [range,setRange] = useState(configuredRange);
  const settingsReady = connected && !!robot.status.motion_settings && !robot.pending;
  const turnValid = turn.trim() !== "" && validTurnSpeed(Number(turn));
  useEffect(()=>setTurn(configuredTurn.toFixed(2)),[configuredTurn]);
  useEffect(()=>setRange(configuredRange),[configuredRange]);
  useEffect(()=>setSpeed(Math.round(robot.status.speed_scale*100)),[robot.status.speed_scale]);
  useEffect(()=>{if(robot.status.mode!=="stop")setMode(robot.status.mode);},[robot.status.mode]);
  useEffect(()=>setDistance(actual.toFixed(2)),[mode,actual]);
  const valid = distance.trim()!=="" && validThreshold(Number(distance));
  return <div className={compact ? "motion-settings compact" : "motion-settings"}>
    <section className="motion-setting">
      <div className="setting-title"><Gauge size={16}/><strong>速度比例</strong><output>{speed}%</output></div>
      <input aria-label="速度比例" type="range" min={15} max={mapping?MAPPING_SPEED_MAX:100} step={1} value={Math.max(15,Math.min(mapping?MAPPING_SPEED_MAX:100,speed))} disabled={!connected||robot.pending} onChange={e=>setSpeed(Number(e.target.value))}/>
      <div className="setting-presets">{(mapping?MAPPING_SPEED_PRESETS:[15,25,50,75]).map(n=><button type="button" key={n} aria-pressed={speed===n} disabled={!connected||robot.pending} onClick={()=>setSpeed(n)}>{n}%</button>)}<button type="button" className="setting-apply" disabled={!connected||robot.pending} onClick={()=>void robot.setSpeed(speed)}><Check size={13}/>应用速度</button></div>
      <p className="live-helper">已生效：{connected?Math.round(robot.status.speed_scale*100)+"%":"—"}{mapping?` · 建图最高 ${MAPPING_SPEED_MAX}%`:" · 调试建议 15%–50%"}</p>
      <p className="setting-note">手动和建图的直行、横移按所选比例行驶，转弯速度单独设置。</p>
    </section>
    <section className="motion-setting">
      <div className="setting-title"><Gauge size={16}/><strong>转弯速度</strong><span>rad/s</span></div>
      <div className="threshold-editor"><input aria-label="转弯速度滑块" type="range" min={0.05} max={0.6} step={0.01} value={turnValid?Number(turn):configuredTurn} disabled={!settingsReady} onChange={e=>setTurn(Number(e.target.value).toFixed(2))}/><input aria-label="转弯速度" type="number" min={0.05} max={0.6} step={0.01} value={turn} disabled={!settingsReady} onChange={e=>setTurn(e.target.value)}/></div>
      <div className="setting-presets">{TURN_SPEED_PRESETS.map(n=><button type="button" key={n} aria-pressed={Number(turn)===n} disabled={!settingsReady} onClick={()=>setTurn(n.toFixed(2))}>{n.toFixed(2)}</button>)}<button type="button" className="setting-apply" disabled={!settingsReady||!turnValid} onClick={()=>void robot.setMotionSettings({turn_speed:Number(turn)})}><Check size={13}/>应用转弯速度</button></div>
      <p className="live-helper">{!connected?"已生效：—":!robot.status.motion_settings?"请更新车端以使用独立转弯速度":!turnValid?"请输入 0.05–0.60 rad/s":robot.status.manual_turn_speed===undefined?"等待车端确认":`已生效：${robot.status.manual_turn_speed.toFixed(2)} rad/s`}</p>
      <p className="setting-note">手动与建图共用，不受速度比例影响。0.15 rad/s 约为每秒 8.6°；应用时先停车。</p>
    </section>
    {mappingControls&&<section className="motion-setting">
      <div className="setting-title"><Gauge size={16}/><strong>建图距离</strong><output>{range} m</output></div>
      <div className="setting-presets">{MAPPING_RANGE_PRESETS.map(n=><button type="button" key={n} aria-pressed={range===n} disabled={!settingsReady} onClick={()=>setRange(n)}>{n} m</button>)}<button type="button" className="setting-apply" disabled={!settingsReady} onClick={()=>void robot.setMotionSettings({max_laser_range:range})}><Check size={13}/>保存建图距离</button></div>
      <p className="live-helper">{!connected?"等待小车连接":!robot.status.motion_settings?"请更新车端以设置建图距离":`下次建图：${configuredRange} m${robot.status.mapping.max_laser_range!==undefined?` · 本轮：${robot.status.mapping.max_laser_range} m`:""}`}</p>
      <p className="setting-note">下次开始建图时生效，保存设置不会清空当前地图。{range<=1?"近距离模式看到的环境较少，可能难以保持定位。":""}</p>
    </section>}
    <section className="motion-setting">
      <div className="setting-title"><ShieldCheck size={16}/><strong>前方防撞阈值</strong><span>m</span></div>
      <label className="setting-mode"><span>适用模式</span><select aria-label="防撞适用模式" value={mode} disabled={!connected||robot.pending} onChange={e=>setMode(e.target.value)}>{Object.entries(MODE_LABELS).filter(([id])=>id!=="stop").map(([id,label])=><option key={id} value={id}>{label}</option>)}</select></label>
      <div className="threshold-editor"><input aria-label="防撞阈值滑块" type="range" min={0} max={5} step={0.05} value={valid?Number(distance):actual} disabled={!connected||robot.pending} onChange={e=>setDistance(Number(e.target.value).toFixed(2))}/><input aria-label="防撞阈值" type="number" min={0} max={5} step={0.05} value={distance} disabled={!connected||robot.pending} onChange={e=>setDistance(e.target.value)}/><button type="button" className="setting-apply" disabled={!connected||robot.pending||!valid} onClick={()=>void robot.setModeObstacleStopDistance(mode,Number(distance))}>应用阈值</button></div>
      <p className="live-helper">{!connected?"已生效：—（等待实车状态）":!valid?"请输入 0–5 米的有效距离":actual===0?"已生效：0 m · 该模式的距离停车已关闭":"已生效："+actual.toFixed(2)+" m · 前方距离不大于阈值时停车"}</p>
      <p className="setting-note">0 m 表示关闭该模式的距离停车；急停与指令超时停车仍有效。</p>
    </section>
  </div>;
}
