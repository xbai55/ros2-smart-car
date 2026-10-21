import { useRobotStream } from "../../hooks/useRobotStream";
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
import { Badge, EmptyState, ProgressBar, StatusDot } from "../ui";

export function HeroSection({ robots, incidents, tasks }: { robots: Robot[]; incidents: Incident[] | null; tasks: Task[] | null }) {
  const { connection } = useRobotStream();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const online = robots.length && connection === "connected" ? 1 : 0;
  const openIncidents = incidents ? incidents.filter((i) => i.status === "open" || i.status === "confirmed").length : "—";
  const activeTasks = tasks ? tasks.filter((t) => t.status === "running" || t.status === "transporting").length : "—";

  return (
    <section className="hero">
      <div className="hero-copy">
        <div className="hero-eyebrow"><span className="hero-live"><StatusDot tone={connection === "connected" ? "success" : "neutral"} />实车与业务记录</span><span className="hero-time">{now.toLocaleDateString("zh-CN")} · {now.toLocaleTimeString("zh-CN", { hour12: false })}</span></div>
        <h1 className="hero-title">InsightRover <span>智巡</span></h1>
        <p className="hero-subtitle">实验室安全巡检与文件运输系统</p>
      </div>
      <div className="hero-summary" aria-label="车队业务统计">
        <div className="hero-summary-item"><strong>{online}</strong><span>在线机器人</span></div>
        <div className="hero-summary-item"><strong className="danger">{openIncidents}</strong><span>待处理异常</span></div>
        <div className="hero-summary-item"><strong className="blue">{activeTasks}</strong><span>进行中业务任务</span></div>
      </div>
    </section>
  );
}

export function TaskCenterPanel({ tasks }: { tasks: Task[] }) {
  const visible = tasks.filter((t) => ["running", "paused", "pending", "queued", "dispatched", "transporting"].includes(t.status)).slice(0, 4);
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
            <span className="task-row-progress">{task.progress == null ? "未记录进度" : <><ProgressBar value={task.progress} /><b>{task.progress}%</b></>}</span>
          </Link>
        ))}
        {!visible.length && <EmptyState title="暂无待执行任务记录"/>}
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
        {!visible.length && <EmptyState title="暂无待处理异常记录"/>}
        {visible.map((incident) => (
          <Link key={incident.id} to={`/incidents/${incident.id}`} className="incident-row">
            <StatusDot tone={tone(incident.level)} />
            <span className="incident-row-main">
              <strong>{incident.title}</strong>
              <em>{incident.location} · {incident.detectedAt}</em>
            </span>
            <Badge tone={tone(incident.level)}>{incident.level === "critical" ? "严重" : incident.level === "warning" ? "警告" : "提示"}</Badge>
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
        {!activity.length && <EmptyState title="暂无动态记录"/>}
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
  const {status,connection}=useRobotStream();
  const online=connection==="connected";
  const nodes=online?Object.entries(status.nodes).map(([name,value])=>({name,ok:value==="ok"})):[];
  const okCount=nodes.filter(n=>n.ok).length;
  return (
    <section className="home-panel">
      <header className="home-panel-head">
        <div className="home-panel-title"><ShieldCheck size={16} /><h3>系统概览</h3></div>
        <Link to="/system" className="home-panel-more"><ArrowUpRight size={13} /></Link>
      </header>
      <div className="home-panel-body">
        <div className="sys-summary-line">
          <span><Wifi size={14} />实车控制链路</span><strong>{online ? "在线" : "未连接"}</strong>
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
        <div className="sys-summary-line"><span><FileText size={14} />节点在线</span><strong>{online ? okCount + "/" + nodes.length : "—"}</strong></div>
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
        <span className="strip-item"><em>模式</em><strong>{connected ? modeLabel[mode] ?? mode : "—"}</strong></span>
        <span className="strip-item"><em>速度</em><strong>{connected ? speed + "%" : "—"}</strong></span>
        <span className="strip-item"><em>前方距离</em><strong>{distance == null ? "--" : `${distance.toFixed(2)} m`}</strong></span>

        <span className="strip-status"><StatusDot tone={connected ? "success" : "warning"} />{connected ? "实时连接" : "未连接实车"}</span>
      </div>
    </div>
  );
}
