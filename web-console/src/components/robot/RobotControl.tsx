import { ArrowRight, CircleStop, Gamepad2, Navigation, OctagonAlert, Route } from "lucide-react";
import { cn } from "../../lib/cn";

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
  return (
    <div className="quick-control">
      <div className="qc-row">
        {QUICK_MODES.map((m) => {
          const Icon = m.icon;
          return (
            <button
              key={m.id}
              type="button"
              disabled={!connected}
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
          <span>速度 {speed}%</span>
          <input type="range" min={0} max={100} value={speed} disabled={!connected} onChange={(e) => onSpeed(Number(e.target.value))} />
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
