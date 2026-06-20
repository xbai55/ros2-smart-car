import { CheckCircle2, Cpu, Gamepad2 } from "lucide-react";
import { modeDetails, modeFocusText, modes, type ModeId } from "../data/consoleData";
import type { RobotStatus } from "../robotApi";
import { HudPanel } from "./HudPanel";

type Props = { currentMode: ModeId; status: RobotStatus };

export function ModeFocusPanel({ currentMode, status }: Props) {
  const modeName = modes.find((item) => item.id === currentMode)?.name ?? "停止";
  const detail = modeDetails[currentMode];
  const metrics = [
    { label: "前方距离", value: status.front_distance == null ? "--" : `${status.front_distance.toFixed(2)}m`, tone: "cyan" },
    { label: "速度比例", value: `${Math.round(status.speed_scale * 100)}%`, tone: "green" },
    { label: "感知结果", value: status.detection || (status.color_target?.visible ? "color visible" : "无目标") }
  ];
  const actionIcons = [CheckCircle2, Cpu, Gamepad2];
  return (
    <HudPanel className="mode-focus" title="Mode Focus" subtitle="模式聚焦">
      <div className="focus-content">
        <p>{modeFocusText[currentMode]}</p>
        <strong className="focus-headline">{detail.headline}</strong>
        <div className="focus-metrics">{metrics.map((metric)=><span key={metric.label} className={metric.tone}><small>{metric.label}</small><b>{metric.value}</b></span>)}</div>
        <div className="focus-actions">{detail.actions.map((action,index)=>{const Icon=actionIcons[index]??CheckCircle2;return <span key={action}><Icon size={15}/>{action}</span>;})}</div>
      </div>
      <div className="target-hud" aria-hidden="true"><span/><i/><b>{modeName}</b></div>
    </HudPanel>
  );
}
