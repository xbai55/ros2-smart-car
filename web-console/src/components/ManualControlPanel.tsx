import { Gauge, Home, RotateCcw } from "lucide-react";
import type { CSSProperties } from "react";
import { manualCommands, modes, type ModeId } from "../data/consoleData";
import { HudPanel } from "./HudPanel";

type Props = { currentMode: ModeId; speed: number; onSpeedChange: (speed: number) => void; onCommand: (command: string) => void };

export function ManualControlPanel({ currentMode, speed, onSpeedChange, onCommand }: Props) {
  const modeName = modes.find((mode) => mode.id === currentMode)?.name ?? "停止";
  return (
    <HudPanel className="manual-panel" title="Manual Control" subtitle="手动遥控" action={<span className="tag-pill">/api/command</span>}>
      <div className="manual-layout">
        <div className="drive-pad">{manualCommands.map((command)=>{const Icon=command.icon;return (
          <button key={command.id} type="button" className={`drive-btn ${command.slot} ${command.danger ? "danger" : ""}`} onClick={()=>onCommand(command.id)} title={command.label}>
            <Icon size={22}/><span>{command.label}</span>
          </button>
        );})}</div>
        <div className="speed-console">
          <div className="speed-head"><span>速度比例</span><strong>{speed}%</strong></div>
          <input type="range" min="15" max="100" value={speed} aria-label="速度比例" onChange={(event)=>onSpeedChange(Number(event.currentTarget.value))} style={{"--speed":`${speed}%`} as CSSProperties}/>
          <button className="mini-btn" type="button" onClick={()=>onSpeedChange(15)}><RotateCcw size={14}/>设为安全低速</button>
          <div className="speed-facts">
            <p><Gauge size={15}/>最低速度 <strong>15%</strong></p>
            <p><Home size={15}/>当前模式 <strong>{modeName}</strong></p>
            <p>命令通过 <strong className="green-text">FastAPI / ROS2</strong></p>
          </div>
        </div>
      </div>
    </HudPanel>
  );
}
