import { AlertTriangle, ArrowRight, BatteryCharging, Camera, Gauge, RadioTower, ShieldCheck } from "lucide-react";
import type { ConnectionState, RobotStatus } from "../robotApi";
import type { VideoState } from "./LiveCameraPanel";
import type { ModeId } from "../data/consoleData";

type Props = {
  status: RobotStatus;
  connection: ConnectionState;
  currentMode: ModeId;
  currentModeName: string;
  videoState: VideoState;
  onEnter: () => void;
  onEmergency: () => void;
};

export function HomePage({ status, connection, currentMode, currentModeName, videoState, onEnter, onEmergency }: Props) {
  const connected = connection === "connected";
  const frontDistance = status.front_distance == null ? "--" : `${status.front_distance.toFixed(2)} m`;
  const updatedAt = status.updated_at ? new Date(status.updated_at * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "--:--:--";
  const modeClass = status.emergency_stop ? "danger" : currentMode === "stop" ? "idle" : "active";
  const videoLabel = videoState === "connected" ? "视频已连接" : videoState === "error" ? "视频异常" : "等待视频";

  const metrics = [
    { label: "连接状态", value: connected ? "已连接" : connection === "connecting" ? "连接中" : "已断开", icon: RadioTower, tone: connected ? "good" : "warn" },
    { label: "当前模式", value: currentModeName, icon: ShieldCheck, tone: modeClass },
    { label: "前方距离", value: frontDistance, icon: Gauge, tone: "cyan" },
    { label: "视频源", value: videoLabel, icon: Camera, tone: videoState === "connected" ? "good" : "warn" }
  ];

  return (
    <main className="home-shell">
      <section className="home-hero">
        <div className="home-copy">
          <div className="home-brand"><div className="brand-mark"><span>SC</span></div><strong>Yahboom ROSMASTER X3</strong></div>
          <h1>ROS2 Smart Car 控制中心</h1>
          <p>先看车辆状态，再进入驾驶、感知、建图和跟随控制。首页只做安全确认，避免一打开网页就进入密集操作面板。</p>
          <div className="home-actions">
            <button className="home-primary" type="button" onClick={onEnter}>进入控制台<ArrowRight size={18}/></button>
            <button className="home-emergency" type="button" onClick={onEmergency}><AlertTriangle size={18}/>{status.emergency_stop ? "解除急停" : "急停"}</button>
          </div>
        </div>
        <div className="home-status-board" aria-label="车辆状态概览">
          <div className="home-board-head"><span>状态更新</span><strong>{updatedAt}</strong><i className={`status-dot ${status.updated_at ? "green" : ""}`}/></div>
          <div className="home-metrics">
            {metrics.map((item) => {
              const Icon = item.icon;
              return <article key={item.label} className={`home-metric ${item.tone}`}><Icon size={24}/><span>{item.label}</span><strong>{item.value}</strong></article>;
            })}
          </div>
          <div className="home-route">
            <span><BatteryCharging size={16}/>速度比例 {Math.round(status.speed_scale * 100)}%</span>
            <span>感知结果 {status.detection || (status.color_target?.visible ? "颜色目标可见" : "无目标")}</span>
          </div>
        </div>
      </section>
    </main>
  );
}
