import { ArrowLeft, Battery, Bot, ListChecks, TriangleAlert, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, navigate } from "../lib/router";
import { useData } from "../hooks/useData";
import { useRobotStream } from "../hooks/useRobotStream";
import { adapters } from "../services/adapters";
import { RobotMapCanvas } from "../components/robot/RobotMapCanvas";
import { RobotCamera } from "../components/robot/RobotCamera";
import { RobotRunWorkspace } from "../components/robot/RobotRunWorkspace";
import { Badge, EmptyState, Panel, ProgressBar, StatusDot, Tabs } from "../components/ui";
import { DataTable, ObjectHeader, ObjectItem, SplitView, type Column } from "../components/shared";
import type { Robot, RobotHealth, Task, Incident } from "../types/domain";

const healthLabel: Record<RobotHealth, string> = { online: "在线", offline: "离线", degraded: "退化", charging: "充电中" };
const healthTone: Record<RobotHealth, "success" | "neutral" | "warning" | "info"> = { online: "success", offline: "neutral", degraded: "warning", charging: "info" };
const modeLabel: Record<string, string> = { stop: "停止", manual: "手动", auto: "自动避障", mapping: "建图", navigation: "导航", color_track: "颜色追踪", object_follow: "目标跟随", patrol: "巡检", transport: "运输" };

export function RobotsPage() {
  const { data, loading } = useData(() => adapters.listRobots());
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<RobotHealth | "all">("all");

  const robots = (data ?? []).filter((r) => {
    const q = query.trim().toLowerCase();
    const hitQ = !q || r.name.toLowerCase().includes(q) || r.zone.toLowerCase().includes(q) || r.id.includes(q);
    const hitF = filter === "all" || r.health === filter;
    return hitQ && hitF;
  });

  const columns: Column<Robot>[] = [
    { key: "robot", header: "机器人", render: (r) => <div className="cell-robot"><span className={cnDot(r.health)} /><div><strong>{r.name}</strong><em>{r.model}</em></div></div> },
    { key: "health", header: "状态", render: (r) => <Badge tone={healthTone[r.health]}>{healthLabel[r.health]}</Badge> },
    { key: "zone", header: "区域", render: (r) => r.zone },
    { key: "battery", header: "电量", render: (r) => <div className="cell-battery"><ProgressBar value={r.battery} tone={r.battery < 25 ? "danger" : "success"} /><span>{r.battery}%</span></div> },
    { key: "mode", header: "当前模式", render: (r) => modeLabel[r.mode] ?? r.mode },
    { key: "activity", header: "任务/异常", render: (r) => <span className="cell-count"><span>{r.tasks} 任务</span><span className="warn">{r.incidents} 异常</span></span> },
  ];

  return (
    <div className="page">
      <ObjectHeader
        kicker="Robots"
        title="机器人"
        subtitle="实验室巡检与运输车队的运行、调度与对象入口"
        badges={[{ label: `${(data ?? []).filter((r) => r.health === "online").length} 在线`, tone: "success" }]}
        actions={<Link className="btn btn-primary btn-sm" to="/robots/r-001/run"><Wrench size={14} />进入运行工作区</Link>}
      />
      <Panel className="list-panel" bodyClassName="panel-flush">
        <div className="list-toolbar">
          <div className="filter-tabs">
            {(["all", "online", "degraded", "charging", "offline"] as const).map((f) => (
              <button key={f} type="button" className={filter === f ? "on" : ""} onClick={() => setFilter(f)}>
                {f === "all" ? "全部" : healthLabel[f]}
              </button>
            ))}
          </div>
          <input className="search-input" placeholder="搜索机器人、区域…" value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <DataTable columns={columns} rows={robots} rowKey={(r) => r.id} loading={loading} emptyTitle="没有匹配的机器人" onRowClick={(r) => { window.location.hash = `/robots/${r.id}`; }} />
      </Panel>
    </div>
  );
}

function cnDot(health: RobotHealth) {
  return health === "online" ? "dot online" : health === "degraded" ? "dot degraded" : health === "charging" ? "dot charging" : "dot offline";
}

export function RobotDetailPage({ id }: { id: string }) {
  const { data: robot } = useData(() => adapters.getRobot(id), [id]);
  const robotsQuery = useData(() => adapters.listRobots());
  const [tab, setTab] = useState("overview");
  const tasksQuery = useData(() => adapters.listTasks());
  const incidentsQuery = useData(() => adapters.listIncidents());

  if (!robot) {
    return <div className="page"><EmptyState title="未找到该机器人" /></div>;
  }

  const robots = robotsQuery.data ?? [];
  const tasks = (tasksQuery.data ?? []).filter((t) => t.robotId === robot.id);
  const incidents = (incidentsQuery.data ?? []).filter((i) => i.robotName === robot.name);

  return (
    <div className="page">
      <Link to="/robots" className="back-link"><ArrowLeft size={15} />机器人</Link>
      <ObjectHeader
        kicker={`Robot · ${robot.id}`}
        title={robot.name}
        subtitle={`${robot.model} · ${robot.zone}`}
        badges={[
          { label: healthLabel[robot.health], tone: healthTone[robot.health] },
          { label: modeLabel[robot.mode] ?? robot.mode, tone: "blue" },
        ]}
        actions={<><Badge tone="neutral">电量 {robot.battery}%</Badge></>}
      />
      <SplitView railTitle="机器人" railCount={robots.length} rail={robots.map((r) => (
        <ObjectItem key={r.id} active={r.id === robot.id} icon={Bot} title={r.name} meta={`${healthLabel[r.health]} · ${r.zone} · 电量 ${r.battery}%`} badge={<Badge tone={healthTone[r.health]}>{healthLabel[r.health]}</Badge>} onClick={() => navigate(`/robots/${r.id}`)} />
      ))}>
        <Tabs
          items={[
            { id: "overview", label: "概览", icon: Bot },
            { id: "run", label: "运行", icon: Wrench },
            { id: "tasks", label: "任务" },
            { id: "incidents", label: "异常" },
            { id: "telemetry", label: "遥测" },
          ]}
          active={tab}
          onChange={setTab}
        />
        {tab === "overview" ? <RobotOverview robot={robot} tasks={tasks} incidents={incidents} /> : null}
        {tab === "run" ? <RobotRunWorkspace robot={robot} /> : null}
        {tab === "tasks" ? <RobotTasks tasks={tasks} /> : null}
        {tab === "incidents" ? <RobotIncidents incidents={incidents} /> : null}
        {tab === "telemetry" ? <RobotTelemetry /> : null}
      </SplitView>
    </div>
  );
}

export function RobotRunPage({ id }: { id: string }) {
  const { data: robot } = useData(() => adapters.getRobot(id), [id]);
  if (!robot) return <div className="page"><EmptyState title="未找到该机器人" /></div>;
  return (
    <div className="page page-dark">
      <Link to={`/robots/${id}`} className="back-link dark"><ArrowLeft size={15} />返回机器人详情</Link>
      <RobotRunWorkspace robot={robot} />
    </div>
  );
}

function RobotOverview({ robot, tasks, incidents }: { robot: Robot; tasks: Task[]; incidents: Incident[] }) {
  return (
    <div className="workspace">
      <div className="workspace-stats">
        <div className="ws-stat"><em>型号</em><strong>{robot.model}</strong></div>
        <div className="ws-stat"><em>区域</em><strong>{robot.zone}</strong></div>
        <div className="ws-stat"><em>模式</em><strong>{modeLabel[robot.mode] ?? robot.mode}</strong></div>
        <div className="ws-stat"><em>电量</em><strong>{robot.battery}%</strong></div>
        <div className="ws-stat"><em>前方距离</em><strong>{robot.frontDistance == null ? "--" : `${robot.frontDistance.toFixed(2)} m`}</strong></div>
        <div className="ws-stat"><em>最近上报</em><strong>{robot.lastSeen}</strong></div>
      </div>
      <div className="ws-split ws-split-map">
        <div className="ws-media-cell">
          <div className="ws-section-title"><span>实时位置 · Map</span></div>
          <div className="ws-media"><RobotMapCanvas robots={[robot]} incidents={incidents} /></div>
        </div>
        <div className="ws-media-cell">
          <div className="ws-section-title"><span>实时画面 · Camera</span></div>
          <div className="ws-media"><RobotCamera robot={robot} /></div>
        </div>
      </div>
      <div className="ws-section">
        <div className="ws-section-title"><span>当前任务</span></div>
        {tasks.length ? tasks.map((t) => (
          <Link key={t.id} to={`/tasks/${t.id}`} className="mini-row">
            <ListChecks size={15} />
            <span><strong>{t.title}</strong><em>{t.status}</em></span>
            <ProgressBar value={t.progress} />
          </Link>
        )) : <EmptyState title="暂无任务" />}
      </div>
    </div>
  );
}

function RobotTasks({ tasks }: { tasks: Task[] }) {
  const columns: Column<Task>[] = [
    { key: "title", header: "任务", render: (t) => t.title },
    { key: "type", header: "类型", render: (t) => <Badge tone={t.type === "patrol" ? "blue" : "info"}>{t.type === "patrol" ? "巡检" : "运输"}</Badge> },
    { key: "status", header: "状态", render: (t) => statusLabel(t.status) },
    { key: "progress", header: "进度", render: (t) => <ProgressBar value={t.progress} /> },
  ];
  return <Panel className="list-panel" bodyClassName="panel-flush"><DataTable columns={columns} rows={tasks} rowKey={(t) => t.id} emptyTitle="暂无任务" onRowClick={(t) => { window.location.hash = `/tasks/${t.id}`; }} /></Panel>;
}

function RobotIncidents({ incidents }: { incidents: Incident[] }) {
  const tone = (level: Incident["level"]) => (level === "critical" ? "danger" : level === "warning" ? "warning" : "info");
  const columns: Column<Incident>[] = [
    { key: "title", header: "异常", render: (i) => <span className="cell-strong">{i.title}</span> },
    { key: "level", header: "级别", render: (i) => <Badge tone={tone(i.level)}>{i.level}</Badge> },
    { key: "location", header: "位置", render: (i) => i.location },
    { key: "time", header: "时间", render: (i) => i.detectedAt },
  ];
  return <Panel className="list-panel" bodyClassName="panel-flush"><DataTable columns={columns} rows={incidents} rowKey={(i) => i.id} emptyTitle="暂无异常" onRowClick={(i) => { window.location.hash = `/incidents/${i.id}`; }} /></Panel>;
}

function RobotTelemetry() {
  const { status, connection } = useRobotStream();
  const nodeEntries = Object.entries(status.nodes);
  return (
    <div className="telemetry-panels">
      <Panel title="ROS2 节点" kicker="Nodes" className="list-panel">
        {nodeEntries.length ? (
          <div className="node-list">
            {nodeEntries.map(([name, value]) => (
              <div key={name} className="sys-node">
                <StatusDot tone={value === "ok" ? "success" : "danger"} />
                <span>{name}</span>
                <em>{value}</em>
              </div>
            ))}
          </div>
        ) : <EmptyState title="无节点数据（ROS2 未连接）" />}
      </Panel>
      <Panel title="运动与定位" kicker="Odom · TF" className="list-panel">
        <div className="profile-list">
          <div><em>连接</em><strong>{connection === "connected" ? "实时在线" : "离线"}</strong></div>
          <div><em>线性速度</em><strong>{status.cmd_vel.ok ? `${status.cmd_vel.linear_x.toFixed(2)} m/s` : "--"}</strong></div>
          <div><em>角速度</em><strong>{status.cmd_vel.ok ? `${status.cmd_vel.angular_z.toFixed(2)} rad/s` : "--"}</strong></div>
          <div><em>前方距离</em><strong>{status.front_distance == null ? "--" : `${status.front_distance.toFixed(2)} m`}</strong></div>
          <div><em>定位</em><strong>{status.map_pose.ok ? "正常" : "待定位"}</strong></div>
          <div><em>安全互锁</em><strong className={status.emergency_stop ? "danger" : "safe"}>{status.emergency_stop ? "急停中" : "正常"}</strong></div>
        </div>
      </Panel>
      <Panel title="电池" kicker="Power" className="list-panel">
        <div className="battery-gauge"><Battery size={30} /><ProgressBar value={75} tone="success" /><span>75%</span></div>
      </Panel>
    </div>
  );
}

function statusLabel(status: Task["status"]) {
  const map: Record<string, { label: string; tone: "neutral" | "blue" | "warning" | "success" | "danger" }> = {
    pending: { label: "待分配", tone: "neutral" },
    running: { label: "进行中", tone: "blue" },
    paused: { label: "已暂停", tone: "warning" },
    completed: { label: "已完成", tone: "success" },
    failed: { label: "失败", tone: "danger" },
  };
  const s = map[status] ?? { label: status, tone: "neutral" as const };
  return <Badge tone={s.tone}>{s.label}</Badge>;
}
