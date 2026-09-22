import { Battery, Gauge, Navigation, ShieldCheck, Zap } from "lucide-react";
import type { Robot } from "../../types/domain";
import type { RobotStatus } from "../../robotApi";
import { cn } from "../../lib/cn";
import { ProgressBar } from "../ui";

type Props = { robot: Robot; live: RobotStatus | null; connected: boolean; className?: string };

export function RobotStatusPanel({ robot, live, connected, className }: Props) {
  const battery = live?.nodes ? robot.battery : robot.battery;
  const mode = connected && live ? live.mode : robot.mode;
  const speed = connected && live ? Math.round(live.speed_scale * 100) : robot.speed;
  const distance = connected && live && live.front_distance != null ? live.front_distance : robot.frontDistance;
  const emergency = connected && live ? live.emergency_stop : false;

  const modeLabel: Record<string, string> = { stop: "停止", manual: "手动", auto: "自动避障", mapping: "建图", navigation: "导航", color_track: "颜色追踪", object_follow: "目标跟随", patrol: "巡检", transport: "运输" };

  return (
    <div className={cn("robot-status-panel", className)}>
      <div className="rsp-head">
        <div className="rsp-identity">
          <span className={cn("rsp-avatar", robot.health)}><Battery size={16} /></span>
          <div><strong>{robot.name}</strong><em>{robot.zone}</em></div>
        </div>
        <span className={cn("rsp-online", connected ? "on" : "off")}>{connected ? "实时在线" : "离线缓存"}</span>
      </div>

      <div className="rsp-grid">
        <div className="rsp-item">
          <span className="rsp-icon"><Zap size={15} /></span>
          <div><em>当前模式</em><strong>{modeLabel[mode] ?? mode}</strong></div>
        </div>
        <div className="rsp-item">
          <span className="rsp-icon"><Gauge size={15} /></span>
          <div><em>速度比例</em><strong>{speed}%</strong></div>
        </div>
        <div className="rsp-item">
          <span className="rsp-icon"><Navigation size={15} /></span>
          <div><em>前方距离</em><strong>{distance == null ? "--" : `${distance.toFixed(2)} m`}</strong></div>
        </div>
        <div className="rsp-item">
          <span className="rsp-icon"><ShieldCheck size={15} /></span>
          <div><em>安全状态</em><strong className={emergency ? "danger" : "safe"}>{emergency ? "急停中" : "正常"}</strong></div>
        </div>
      </div>

      <div className="rsp-battery">
        <span>电量</span>
        <div className="rsp-battery-track">
          <div className="rsp-battery-fill" style={{ width: `${battery}%` }} />
        </div>
        <strong>{battery}%</strong>
      </div>
      {robot.health === "degraded" ? <div className="rsp-note">检测到传感器退化，建议返回充电并检查</div> : null}
      {connected ? <div className="rsp-sync">状态更新于 {live?.updated_at ? new Date(live.updated_at * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "--:--:--"}</div> : null}
    </div>
  );
}
