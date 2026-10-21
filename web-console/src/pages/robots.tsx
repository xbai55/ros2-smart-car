import { ArrowLeft, Battery, Bot, ListChecks, TriangleAlert, Wrench } from "lucide-react";
import { useState } from "react";
import { Link, navigate } from "../lib/router";
import { useData } from "../hooks/useData";
import { useRobotStream } from "../hooks/useRobotStream";
import { adapters } from "../services/adapters";
import { LiveMapCanvas } from "../components/robot/LiveMapCanvas";
import { RobotStatusPanel } from "../components/robot/RobotStatusPanel";
import { LIVE_ROBOT_ID } from "../liveControl";
import { RobotCamera } from "../components/robot/RobotCamera";
import { RobotRunWorkspace } from "../components/robot/RobotRunWorkspace";
import { Badge, EmptyState, Panel, ProgressBar, Skeleton, StatusDot, Tabs } from "../components/ui";
import { DataTable, ObjectHeader, ObjectItem, SplitView, type Column } from "../components/shared";
import type { Robot, RobotHealth, Task, Incident } from "../types/domain";

const healthLabel: Record<RobotHealth, string> = { online: "在线", offline: "离线", degraded: "退化", charging: "充电中" };
const healthTone: Record<RobotHealth, "success" | "neutral" | "warning" | "info"> = { online: "success", offline: "neutral", degraded: "warning", charging: "info" };
const modeLabel: Record<string, string> = { stop: "停止", manual: "手动", auto: "自动避障", mapping: "建图", navigation: "导航", color_track: "颜色追踪", object_follow: "目标跟随", patrol: "巡检", transport: "运输" };

export function RobotsPage() {
  const { data, loading } = useData(() => adapters.listRobots());
  const [query, setQuery] = useState("");
  const { status, connection } = useRobotStream();
  const online = connection === "connected";
  const [filter, setFilter] = useState<RobotHealth | "all">("all");

  const robots = (data ?? []).filter((r) => {
    const q = query.trim().toLowerCase();
    const hitQ = !q || r.name.toLowerCase().includes(q) || r.zone.toLowerCase().includes(q) || r.id.includes(q);
    const hitF = filter === "all" || (r.id === LIVE_ROBOT_ID ? (online ? "online" : "offline") : r.health) === filter;
    return hitQ && hitF;
  });

  const columns: Column<Robot>[] = [
    { key: "robot", header: "机器人", render: (r) => <div className="cell-robot"><span className={cnDot(r.id===LIVE_ROBOT_ID?(online?"online":"offline"):r.health)} /><div><strong>{r.name}</strong><em>{r.id === LIVE_ROBOT_ID ? "实车 · " + r.model : "未绑定 · " + r.model}</em></div></div> },
    { key: "health", header: "状态", render: (r) => <Badge tone={r.id === LIVE_ROBOT_ID ? (online ? "success" : "neutral") : healthTone[r.health]}>{r.id === LIVE_ROBOT_ID ? (online ? "实车在线" : "实车未连接") : healthLabel[r.health]}</Badge> },
    { key: "zone", header: "区域", render: (r) => r.id === LIVE_ROBOT_ID ? "实车连接" : r.zone },
    { key: "battery", header: "电量", render: (r) => r.id === LIVE_ROBOT_ID ? (online && status.battery != null ? status.battery + "%" : "—") : <div className="cell-battery"><span>未采集</span></div> },
    { key: "mode", header: "当前模式", render: (r) => r.id === LIVE_ROBOT_ID ? (online ? modeLabel[status.mode] ?? status.mode : "—") : modeLabel[r.mode] ?? r.mode },
    { key: "activity", header: "任务/异常", render: (r) => <span className="cell-count"><span>未关联业务统计</span></span> },
  ];

  return (
    <div className="page">
      <ObjectHeader
        kicker="Robots"
        title="机器人"
        subtitle="已配置的实车连接；状态由车端实时提供"
        badges={[{ label: online ? "实车在线" : "实车未连接", tone: online ? "success" : "neutral" }]}
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
  const { data: robot, loading } = useData(() => adapters.getRobot(id), [id]);
  const {status,connection} = useRobotStream();
  const online=connection==="connected",bound=id===LIVE_ROBOT_ID;
  const robotsQuery = useData(() => adapters.listRobots());
  const [tab, setTab] = useState("overview");
  const tasksQuery = useData(() => adapters.listTasks());
  const incidentsQuery = useData(() => adapters.listIncidents());

  if(loading || (robot && robot.id !== id))return <div className="page"><Skeleton className="robot-loading"/></div>;
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
        subtitle={`${robot.model} · ${bound ? "实车连接" : robot.zone + " · 未绑定"}`}
        badges={[
          { label: bound ? (online ? "实车在线" : "实车未连接") : "未绑定实车", tone: bound && online ? "success" : "neutral" },
          { label: bound ? (online ? modeLabel[status.mode] ?? status.mode : "—") : modeLabel[robot.mode] ?? robot.mode, tone: "blue" },
        ]}
        actions={<><Badge tone="neutral">电量 {bound ? (online && status.battery != null ? status.battery + "%" : "—") : robot.battery + "%"}</Badge></>}
      />
      <SplitView railTitle="机器人" railCount={robots.length} rail={robots.map((r) => (
        <ObjectItem key={r.id} active={r.id === robot.id} icon={Bot} title={r.name} meta={r.id === LIVE_ROBOT_ID ? "r-001 · 实车连接" : `未绑定 · ${r.zone}`} badge={<Badge tone={r.id===LIVE_ROBOT_ID?(online?"success":"neutral"):healthTone[r.health]}>{r.id===LIVE_ROBOT_ID?(online?"实车在线":"未连接"):healthLabel[r.health]}</Badge>} onClick={() => navigate(`/robots/${r.id}`)} />
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
        {tab === "telemetry" ? <RobotTelemetry robotId={robot.id} /> : null}
      </SplitView>
    </div>
  );
}

export function RobotRunPage({ id }: { id: string }) {
  const { data: robot, loading } = useData(() => adapters.getRobot(id), [id]);
  if(loading || (robot && robot.id !== id))return <div className="page"><Skeleton className="robot-loading"/></div>;
  if (!robot) return <div className="page"><EmptyState title="未找到该机器人" /></div>;
  return (
    <div className="page page-dark">
      <Link to={`/robots/${id}`} className="back-link dark"><ArrowLeft size={15} />返回机器人详情</Link>
      <RobotRunWorkspace robot={robot} />
    </div>
  );
}

function RobotOverview({ robot, tasks }: {robot:Robot;tasks:Task[];incidents:Incident[]}) {
  const {status,connection}=useRobotStream(),bound=robot.id===LIVE_ROBOT_ID;
  return <div className="workspace">
    <p className="data-source-note">{bound?"状态、地图和视频来自实车；任务来自业务记录。":"尚未绑定实车。"}</p>
    <RobotStatusPanel robot={robot} live={bound&&connection==="connected"?status:null} connected={bound&&connection==="connected"}/>
    <div className="ws-split ws-split-map"><div className="ws-media-cell"><div className="ws-section-title">实时环境地图</div><div className="ws-media">{bound?<LiveMapCanvas/>:<EmptyState title="未绑定实车地图"/>}</div></div><div className="ws-media-cell"><div className="ws-section-title">实时摄像头</div><div className="ws-media"><RobotCamera robot={robot}/></div></div></div>
    <div className="ws-section"><div className="ws-section-title">业务任务记录</div>{tasks.length?tasks.map(t=><Link key={t.id} to={`/tasks/${t.id}`} className="mini-row"><ListChecks size={15}/><span><strong>{t.title}</strong><em>{t.status}</em></span><span>{t.progress == null ? "未记录" : t.progress + "%"}</span></Link>):<EmptyState title="暂无任务"/>}</div>
  </div>;
}

function RobotTasks({ tasks }: { tasks: Task[] }) {
  const columns: Column<Task>[] = [
    { key: "title", header: "任务", render: (t) => t.title },
    { key: "type", header: "类型", render: (t) => <Badge tone={t.type === "patrol" ? "blue" : "info"}>{t.type === "patrol" ? "巡检" : "运输"}</Badge> },
    { key: "status", header: "状态", render: (t) => statusLabel(t.status) },
    { key: "progress", header: "进度", render: (t) => <span>{t.progress == null ? "未记录" : t.progress + "%"}</span> },
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

function RobotTelemetry({robotId}:{robotId:string}) {
  const { status, connection } = useRobotStream();
  const online=robotId===LIVE_ROBOT_ID && connection==="connected";
  if(robotId!==LIVE_ROBOT_ID)return <EmptyState title="未绑定实车遥测"/>;
  const nodeEntries = online ? Object.entries(status.nodes) : [];
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
          <div><em>线性速度</em><strong>{online && status.cmd_vel.ok ? `${status.cmd_vel.linear_x.toFixed(2)} m/s` : "--"}</strong></div>
          <div><em>角速度</em><strong>{online && status.cmd_vel.ok ? `${status.cmd_vel.angular_z.toFixed(2)} rad/s` : "--"}</strong></div>
          <div><em>前方距离</em><strong>{!online || status.front_distance == null ? "--" : `${status.front_distance.toFixed(2)} m`}</strong></div>
          <div><em>定位</em><strong>{online && status.map_pose.ok ? "正常" : "待定位"}</strong></div>
          <div><em>安全互锁</em><strong className={status.emergency_stop ? "danger" : "safe"}>{online ? (status.emergency_stop ? "急停中" : "未锁定") : "—"}</strong></div>
        </div>
      </Panel>
      <Panel title="电池" kicker="Power" className="list-panel">
        <div className="battery-gauge"><Battery size={30} /><span>{online && status.battery != null ? status.battery + "%" : "—（车端尚未提供测量值）"}</span></div>
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
