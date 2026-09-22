import {
  AlertTriangle,
  ArrowUpRight,
  Bot,
  Cpu,
  FileText,
  ListChecks,
  Map as MapIcon,
  ShieldCheck,
  Wifi,
} from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "../../lib/router";
import type { ActivityItem, Incident, Robot, Task } from "../../types/domain";
import { Badge, ProgressBar, StatusDot } from "../ui";

export function HeroSection({ robots, incidents, tasks }: { robots: Robot[]; incidents: Incident[]; tasks: Task[] }) {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const online = robots.filter((r) => r.health === "online").length;
  const openIncidents = incidents.filter((i) => i.status === "open" || i.status === "confirmed").length;
  const activeTasks = tasks.filter((t) => t.status === "running" || t.status === "paused").length;

  return (
    <section className="hero">
      <div className="hero-copy">
        <div className="hero-eyebrow"><span className="hero-live"><StatusDot tone="success" />系统运行正常</span><span className="hero-time">{now.toLocaleDateString("zh-CN")} · {now.toLocaleTimeString("zh-CN", { hour12: false })}</span></div>
        <h1 className="hero-title">InsightRover <span>智巡</span></h1>
        <p className="hero-subtitle">实验室安全巡检与文件运输系统</p>
        <div className="hero-summary">
          <div className="hero-summary-item"><strong>{online}</strong><span>在线机器人</span></div>
          <div className="hero-summary-item"><strong className="danger">{openIncidents}</strong><span>待处理异常</span></div>
          <div className="hero-summary-item"><strong className="blue">{activeTasks}</strong><span>进行中任务</span></div>
        </div>
      </div>
      <div className="hero-visual" aria-hidden="true">
        <div className="hero-scene">
          <div className="hero-radar" />
          <Rover />
          <div className="hero-floor" />
        </div>
      </div>
    </section>
  );
}

function Rover() {
  return (
    <svg className="rover" viewBox="0 0 220 120" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="智巡巡检机器人">
      <ellipse cx="110" cy="106" rx="84" ry="9" fill="rgba(37,99,235,.12)" />
      <g transform="translate(110,72)">
        <rect x="-58" y="-28" width="116" height="40" rx="12" fill="#1e293b" />
        <rect x="-58" y="-28" width="116" height="16" rx="8" fill="#334155" />
        <rect x="30" y="-34" width="40" height="26" rx="7" fill="#1e293b" />
        <rect x="36" y="-30" width="28" height="18" rx="5" fill="#0ea5e9" opacity=".85" />
        <circle cx="66" cy="-21" r="4" fill="#bae6fd" />
        <rect x="-52" y="-22" width="26" height="10" rx="3" fill="#0f172a" />
        <circle cx="0" cy="-17" r="6" fill="#2563eb" />
        <rect x="-8" y="-21" width="16" height="8" rx="4" fill="#1e293b" />
        <line x1="-52" y1="-14" x2="52" y2="-14" stroke="#0f172a" strokeWidth="2" />
        <rect x="-40" y="12" width="18" height="9" rx="2" fill="#0f172a" />
        <rect x="22" y="12" width="18" height="9" rx="2" fill="#0f172a" />
      </g>
      <circle cx="64" cy="96" r="17" fill="#1e293b" />
      <circle cx="64" cy="96" r="9" fill="#334155" />
      <circle cx="64" cy="96" r="3.5" fill="#94a3b8" />
      <circle cx="156" cy="96" r="17" fill="#1e293b" />
      <circle cx="156" cy="96" r="9" fill="#334155" />
      <circle cx="156" cy="96" r="3.5" fill="#94a3b8" />
    </svg>
  );
}

export function TaskCenterPanel({ tasks }: { tasks: Task[] }) {
  const visible = tasks.filter((t) => t.status === "running" || t.status === "paused" || t.status === "pending").slice(0, 4);
  return (
    <section className="home-panel">
      <header className="home-panel-head">
        <div className="home-panel-title"><ListChecks size={16} /><h3>任务中心</h3></div>
        <Link to="/tasks" className="home-panel-more">全部任务 <ArrowUpRight size={13} /></Link>
      </header>
      <div className="home-panel-body">
        {visible.map((task) => (
          <Link key={task.id} to={`/tasks/${task.id}`} className="task-row">
            <span className="task-row-type"><Badge tone={task.type === "patrol" ? "blue" : "info"}>{task.type === "patrol" ? "巡检" : "运输"}</Badge></span>
            <span className="task-row-main">
              <strong>{task.title}</strong>
              <em>{task.robotName} · {task.currentStep}</em>
            </span>
            <span className="task-row-progress"><ProgressBar value={task.progress} /><b>{task.progress}%</b></span>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function IncidentPanel({ incidents }: { incidents: Incident[] }) {
  const visible = incidents.filter((i) => i.status === "open" || i.status === "confirmed").slice(0, 4);
  const tone = (level: Incident["level"]) => (level === "critical" ? "danger" : level === "warning" ? "warning" : "info");
  return (
    <section className="home-panel">
      <header className="home-panel-head">
        <div className="home-panel-title"><AlertTriangle size={16} /><h3>异常告警</h3></div>
        <Link to="/incidents" className="home-panel-more">全部异常 <ArrowUpRight size={13} /></Link>
      </header>
      <div className="home-panel-body">
        {visible.map((incident) => (
          <Link key={incident.id} to={`/incidents/${incident.id}`} className="incident-row">
            <StatusDot tone={tone(incident.level)} />
            <span className="incident-row-main">
              <strong>{incident.title}</strong>
              <em>{incident.location} · {incident.detectedAt}</em>
            </span>
            <Badge tone={tone(incident.level)}>{incident.confidence}%</Badge>
          </Link>
        ))}
      </div>
    </section>
  );
}

export function RecentObjectsPanel({ activity }: { activity: ActivityItem[] }) {
  const iconFor = (kind: ActivityItem["kind"]) => (kind === "incident" ? AlertTriangle : kind === "task" ? ListChecks : kind === "robot" ? Bot : Cpu);
  return (
    <section className="home-panel">
      <header className="home-panel-head">
        <div className="home-panel-title"><Bot size={16} /><h3>最近动态</h3></div>
      </header>
      <div className="home-panel-body">
        {activity.slice(0, 5).map((item) => {
          const Icon = iconFor(item.kind);
          return (
            <Link key={item.id} to={item.href} className="activity-row">
              <span className="activity-icon"><Icon size={14} /></span>
              <span className="activity-main"><strong>{item.text}</strong><em>{item.time}</em></span>
            </Link>
          );
        })}
      </div>
    </section>
  );
}

export function SystemOverviewPanel() {
  const nodes = [
    { name: "decision_controller", ok: true },
    { name: "lidar_node", ok: true },
    { name: "yolo_detector", ok: true },
    { name: "camera_node", ok: false },
  ];
  const okCount = nodes.filter((n) => n.ok).length;
  return (
    <section className="home-panel">
      <header className="home-panel-head">
        <div className="home-panel-title"><ShieldCheck size={16} /><h3>系统概览</h3></div>
        <Link to="/system" className="home-panel-more"><ArrowUpRight size={13} /></Link>
      </header>
      <div className="home-panel-body">
        <div className="sys-summary-line">
          <span><Wifi size={14} />控制链路</span><strong>正常</strong>
        </div>
        <div className="sys-node-list">
          {nodes.map((node) => (
            <div key={node.name} className="sys-node">
              <StatusDot tone={node.ok ? "success" : "danger"} />
              <span>{node.name}</span>
              <em>{node.ok ? "ok" : "down"}</em>
            </div>
          ))}
        </div>
        <div className="sys-summary-line"><span><FileText size={14} />节点在线</span><strong>{okCount}/{nodes.length}</strong></div>
      </div>
    </section>
  );
}

export function RobotStatusStrip({ robot, connected, mode, speed, distance }: { robot: Robot | undefined; connected: boolean; mode: string; speed: number; distance: number | null }) {
  if (!robot) return null;
  const modeLabel: Record<string, string> = { stop: "停止", manual: "手动", auto: "自动避障", mapping: "建图", navigation: "导航", color_track: "颜色追踪", object_follow: "目标跟随", patrol: "巡检", transport: "运输" };
  return (
    <div className="robot-status-strip">
      <div className="strip-inner">
        <span className="strip-robot"><Bot size={14} />{robot.name}</span>
        <span className="strip-item"><em>模式</em><strong>{modeLabel[mode] ?? mode}</strong></span>
        <span className="strip-item"><em>速度</em><strong>{speed}%</strong></span>
        <span className="strip-item"><em>前方距离</em><strong>{distance == null ? "--" : `${distance.toFixed(2)} m`}</strong></span>
        <span className="strip-item"><em>安全</em><strong className="safe">正常</strong></span>
        <span className="strip-status"><StatusDot tone={connected ? "success" : "warning"} />{connected ? "实时连接" : "离线缓存"}</span>
      </div>
    </div>
  );
}
