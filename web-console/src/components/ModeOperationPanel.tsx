import { Activity, MapPinned, Navigation2, Radar, Target } from "lucide-react";
import { modeDetails, type ModeId } from "../data/consoleData";
import type { ColorConfig, RobotStatus } from "../robotApi";
import { ColorConfigPanel } from "./ColorConfigPanel";
import { ManualControlPanel } from "./ManualControlPanel";

type Props = {
  currentMode: ModeId; status: RobotStatus; speed: number;
  onSpeedChange: (speed: number) => void; onCommand: (command: string) => void;
  onColorConfig: (config: ColorConfig) => void;
};
const modeIcons: Record<Exclude<ModeId, "manual" | "color_track">, typeof Radar> = {
  stop: Activity, auto: Radar, mapping: MapPinned, navigation: Navigation2, object_follow: Target
};

export function ModeOperationPanel(props: Props) {
  if (props.currentMode === "manual") return <ManualControlPanel currentMode={props.currentMode} speed={props.speed} onSpeedChange={props.onSpeedChange} onCommand={props.onCommand}/>;
  if (props.currentMode === "color_track") return <ColorConfigPanel config={props.status.color_config} target={props.status.color_target} onApply={props.onColorConfig}/>;
  const detail = modeDetails[props.currentMode];
  const Icon = modeIcons[props.currentMode];
  return (
    <section className="mode-operation hud-panel">
      <div className="panel-heading"><div><p className="panel-kicker">Mode Operation</p><h2>模式运行状态</h2></div><span className="tag-pill">{props.currentMode}</span></div>
      <div className="operation-body">
        <div className="operation-primary"><Icon size={40}/><div><strong>{detail.headline}</strong><p>当前模式由后端 /api/mode 设置，ROS2 状态通过 /ws/status 实时回传。</p></div></div>
        <div className="operation-steps">{detail.actions.map((action,index)=><div key={action}><span>{String(index+1).padStart(2,"0")}</span>{action}</div>)}</div>
      </div>
    </section>
  );
}
