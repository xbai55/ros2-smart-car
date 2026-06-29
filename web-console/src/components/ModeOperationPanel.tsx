import { Activity, Gauge, Navigation2, Radar, Target } from "lucide-react";
import { modeDetails, modes, type ModeId } from "../data/consoleData";
import type { CSSProperties } from "react";
import type { ColorConfig, RobotStatus } from "../robotApi";
import { ColorConfigPanel } from "./ColorConfigPanel";
import { ManualControlPanel } from "./ManualControlPanel";
import { modeUsesManualControl } from "../mappingControl";

type Props = {
  currentMode: ModeId; status: RobotStatus; speed: number;
  onSpeedChange: (speed: number) => void; onCommand: (command: string) => void;
  onColorConfig: (config: ColorConfig) => void;
  onModeObstacleStopDistance: (mode: ModeId, distance: number) => void;
};

const modeIcons: Record<Exclude<ModeId, "manual" | "mapping" | "color_track">, typeof Radar> = {
  stop: Activity, auto: Radar, navigation: Navigation2, object_follow: Target
};

function ObstacleStopControl({ mode, value, onChange }: { mode: ModeId; value: number; onChange: (mode: ModeId, distance: number) => void }) {
  const distance = Number.isFinite(value) ? value : 0;
  return (
    <div className="mode-threshold-control compact-control-block">
      <div><strong>雷达停止阈值</strong><span>{mode} · {distance.toFixed(2)} m</span></div>
      <input type="range" min="0" max="2" step="0.05" value={distance} onChange={(event) => onChange(mode, Number(event.currentTarget.value))}/>
      <input type="number" min="0" max="5" step="0.05" value={distance} onChange={(event) => onChange(mode, Number(event.currentTarget.value))}/>
    </div>
  );
}

function SpeedControl({ speed, onChange }: { speed: number; onChange: (speed: number) => void }) {
  return (
    <div className="speed-inline-control compact-control-block">
      <div><strong>速度比例</strong><span>{speed}% · 建议低速调试</span></div>
      <input
        type="range"
        min="15"
        max="100"
        value={speed}
        aria-label="速度比例"
        onChange={(event) => onChange(Number(event.currentTarget.value))}
        style={{ "--speed": `${speed}%` } as CSSProperties}
      />
      <button type="button" onClick={() => onChange(15)}>15%</button>
    </div>
  );
}

export function ModeOperationPanel(props: Props) {
  const threshold = props.status.mode_obstacle_stop_distances[props.currentMode] ?? 0;
  const modeName = modes.find((mode) => mode.id === props.currentMode)?.name ?? props.currentMode;
  const thresholdControl = <ObstacleStopControl mode={props.currentMode} value={threshold} onChange={props.onModeObstacleStopDistance}/>;
  const speedControl = <SpeedControl speed={props.speed} onChange={props.onSpeedChange}/>;

  if (modeUsesManualControl(props.currentMode)) {
    return (
      <section className="mode-operation hud-panel manual-panel">
        <div className="panel-heading"><div><p className="panel-kicker">Manual Control</p><h2>{props.currentMode === "mapping" ? "建图安全遥控" : "手动遥控"}</h2></div><span className="tag-pill">/api/command</span></div>
        <div className="mode-control-strip">{speedControl}{thresholdControl}</div>
        <ManualControlPanel currentMode={props.currentMode} speed={props.speed} onSpeedChange={props.onSpeedChange} onCommand={props.onCommand}/>
      </section>
    );
  }

  if (props.currentMode === "color_track") {
    return (
      <section className="mode-operation hud-panel color-operation-panel">
        <div className="panel-heading"><div><p className="panel-kicker">Color Track</p><h2>颜色追踪控制</h2></div><span className="tag-pill">{modeName}</span></div>
        <div className="mode-control-strip">{speedControl}{thresholdControl}</div>
        <ColorConfigPanel config={props.status.color_config} target={props.status.color_target} onApply={props.onColorConfig}/>
      </section>
    );
  }

  const detail = modeDetails[props.currentMode];
  const Icon = modeIcons[props.currentMode];
  return (
    <section className="mode-operation hud-panel">
      <div className="panel-heading"><div><p className="panel-kicker">Mode Operation</p><h2>模式运行状态</h2></div><span className="tag-pill">{props.currentMode}</span></div>
      <div className="mode-control-strip">{speedControl}{thresholdControl}</div>
      <div className="operation-body">
        <div className="operation-primary"><Icon size={40}/><div><strong>{detail.headline}</strong><p>当前模式由后端 /api/mode 设置，ROS2 状态通过 /ws/status 实时回传。</p></div></div>
        <div className="operation-steps">{detail.actions.map((action,index)=><div key={action}><span>{String(index+1).padStart(2,"0")}</span>{action}</div>)}</div>
      </div>
    </section>
  );
}
