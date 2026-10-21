import { ArrowRight, CircleStop, Gamepad2, Navigation, OctagonAlert, Route } from "lucide-react";
import { cn } from "../../lib/cn";
import { useEffect, useState } from "react";
import { MAPPING_SPEED_MAX } from "../../liveControl";

type Props = {
  connected: boolean;
  mode: string;
  emergency: boolean;
  speed: number;
  onMode: (mode: string) => void;
  onEmergency: () => void;
  onSpeed: (speed: number) => void;
  onEnterFull: () => void;
};

const QUICK_MODES = [
  { id: "stop", label: "停止", icon: CircleStop },
  { id: "auto", label: "自动避障", icon: Route },
  { id: "navigation", label: "导航", icon: Navigation },
  { id: "manual", label: "手动", icon: Gamepad2 },
];

export function RobotControl({ connected, mode, emergency, speed, onMode, onEmergency, onSpeed, onEnterFull }: Props) {
  const [draft, setDraft] = useState(speed);
  useEffect(() => setDraft(speed), [speed]);
  return (
    <div className="quick-control">
      <div className="qc-row">
        {QUICK_MODES.map((m) => {
          const Icon = m.icon;
          return (
            <button
              key={m.id}
              type="button"
              disabled={!connected || (emergency && m.id !== "stop")}
              className={cn("qc-mode", mode === m.id && "active")}
              onClick={() => onMode(m.id)}
            >
              <Icon size={15} />
              {m.label}
            </button>
          );
        })}
      </div>
      <div className="qc-row qc-bottom">
        <label className="qc-speed">
          <span>速度 {draft}% · 已生效 {connected ? speed + "%" : "—"}</span>
          <input aria-label="快速控制速度" type="range" min={15} max={mode === "mapping" ? MAPPING_SPEED_MAX : 100} value={draft} disabled={!connected} onChange={(e) => setDraft(Number(e.target.value))} />
          <button className="setting-apply" disabled={!connected} onClick={() => onSpeed(draft)}>应用速度</button>
        </label>
        <button type="button" disabled={!connected} className={cn("qc-emergency", emergency && "active")} onClick={onEmergency}>
          <OctagonAlert size={16} />
          {emergency ? "解除急停" : "急停"}
        </button>
        <button type="button" className="qc-enter" onClick={onEnterFull}>
          进入完整控制 <ArrowRight size={15} />
        </button>
      </div>
    </div>
  );
}
