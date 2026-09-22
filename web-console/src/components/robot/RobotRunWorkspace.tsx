import { CircleStop, Gamepad2, Navigation, OctagonAlert, Route, Wifi, WifiOff } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createRobotApi, type MapSnapshot } from "../../robotApi";
import { modes } from "../../data/consoleData";
import { useRobotStream } from "../../hooks/useRobotStream";
import type { DemoMap } from "../../services/adapters";
import type { Robot } from "../../types/domain";
import { cn } from "../../lib/cn";
import { RobotCamera } from "./RobotCamera";
import { RobotMapCanvas } from "./RobotMapCanvas";

const MANUAL: Array<{ id: string; label: string; slot: string }> = [
  { id: "forward", label: "前进", slot: "top" },
  { id: "turn_l", label: "左旋", slot: "ml" },
  { id: "stop", label: "停止", slot: "mc" },
  { id: "turn_r", label: "右旋", slot: "mr" },
  { id: "left", label: "左移", slot: "bl" },
  { id: "backward", label: "后退", slot: "bc" },
  { id: "right", label: "右移", slot: "br" },
];

function DrivePad({ onCommand }: { onCommand: (command: string) => void }) {
  return (
    <div className="drive-pad-new">
      {MANUAL.map((cmd) => (
        <button
          key={cmd.id}
          type="button"
          className={cn("drive-btn-new", cmd.slot, cmd.id === "stop" && "danger")}
          onPointerDown={(e) => { e.preventDefault(); if (cmd.id === "stop") onCommand("stop"); else onCommand(cmd.id); }}
          onPointerUp={() => onCommand("stop")}
          onPointerLeave={() => onCommand("stop")}
          aria-label={cmd.label}
        >
          {cmd.id === "stop" ? <CircleStop size={20} /> : <span className="drive-arrow">{cmd.id === "forward" ? "▲" : cmd.id === "backward" ? "▼" : cmd.id === "left" ? "◀" : cmd.id === "right" ? "▶" : cmd.id === "turn_l" ? "↺" : "↻"}</span>}
        </button>
      ))}
    </div>
  );
}

export function RobotRunWorkspace({ robot }: { robot: Robot }) {
  const { status, connection, setMode, sendCommand, setEmergencyStop, setSpeed } = useRobotStream();
  const api = useMemo(() => createRobotApi(), []);
  const [liveMap, setLiveMap] = useState<DemoMap | null>(null);
  const [speed, setSpeedLocal] = useState(() => Math.round(status.speed_scale * 100));

  useEffect(() => {
    let active = true;
    api.getMap().then((snapshot: MapSnapshot) => {
      if (active && snapshot.info) {
        setLiveMap({ width: snapshot.info.width, height: snapshot.info.height, resolution: snapshot.info.resolution, data: snapshot.data });
      }
    }).catch(() => { /* 离线时地图画布回退到示意地图 */ });
    return () => { active = false; };
  }, [api]);

  useEffect(() => {
    if (connection === "connected") setSpeedLocal(Math.round(status.speed_scale * 100));
  }, [connection, status.speed_scale]);

  const currentMode = status.mode;
  const connected = connection === "connected";

  return (
    <div className="run-workspace">
      <header className="run-topbar">
        <div className="run-identity">
          <span className={cn("run-dot", robot.health)} />
          <div><strong>{robot.name}</strong><em>{robot.zone} · 运行工作区</em></div>
        </div>
        <div className="run-modes">
          {modes.map((m) => {
            const Icon = m.icon;
            return (
              <button key={m.id} type="button" disabled={!connected} className={cn("run-mode", currentMode === m.id && "active")} onClick={() => setMode(m.id)}>
                <Icon size={14} />{m.name}
              </button>
            );
          })}
        </div>
        <div className="run-top-actions">
          <label className="run-speed">
            <span>速度 {speed}%</span>
            <input type="range" min={0} max={100} value={speed} disabled={!connected} onChange={(e) => { const v = Number(e.target.value); setSpeedLocal(v); setSpeed(v / 100); }} />
          </label>
          <button type="button" className={cn("run-emergency", status.emergency_stop && "active")} disabled={!connected} onClick={() => setEmergencyStop(!status.emergency_stop)}>
            <OctagonAlert size={16} />{status.emergency_stop ? "解除急停" : "急停"}
          </button>
          <span className={cn("run-conn", connected ? "on" : "off")}>{connected ? <Wifi size={14} /> : <WifiOff size={14} />}{connected ? "实时在线" : "离线"}</span>
        </div>
      </header>

      <div className="run-grid">
        <div className="run-map-pane">
          <RobotMapCanvas robots={[robot]} incidents={[]} mapOverride={liveMap} />
        </div>
        <div className="run-side">
          <RobotCamera robot={robot} />
          <div className="run-telemetry">
            <div className="run-telemetry-title">遥测</div>
            <div className="run-telemetry-grid">
              <TelemetryItem label="线性速度" value={status.cmd_vel.ok ? `${status.cmd_vel.linear_x.toFixed(2)} m/s` : "--"} />
              <TelemetryItem label="角速度" value={status.cmd_vel.ok ? `${status.cmd_vel.angular_z.toFixed(2)} rad/s` : "--"} />
              <TelemetryItem label="前方距离" value={status.front_distance == null ? "--" : `${status.front_distance.toFixed(2)} m`} />
              <TelemetryItem label="定位" value={status.map_pose.ok ? "正常" : "待定位"} />
            </div>
          </div>
          <div className="run-drive">
            <div className="run-drive-title">手动控制</div>
            <DrivePad onCommand={sendCommand} />
            <p className="run-drive-hint">所有指令经 decision_controller 安全仲裁后下发 /cmd_vel</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function TelemetryItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="telemetry-item">
      <em>{label}</em>
      <strong>{value}</strong>
    </div>
  );
}
