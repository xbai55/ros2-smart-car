import { ArrowLeft, CircleStop, ListChecks, Package, Pause, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { Link, navigate } from "../lib/router";
import { useData } from "../hooks/useData";
import { adapters } from "../services/adapters";
import { MissionStepper } from "../components/task/MissionStepper";
import { Badge, Button, EmptyState, Panel, ProgressBar, Tabs } from "../components/ui";
import { DataTable, ObjectHeader, ObjectItem, SplitView, Timeline, type Column } from "../components/shared";
import type { Task, TaskStatus, TaskType } from "../types/domain";

const statusMeta: Record<TaskStatus, { label: string; tone: "neutral" | "blue" | "warning" | "success" | "danger" }> = {
  pending: { label: "待分配", tone: "neutral" },
  running: { label: "进行中", tone: "blue" },
  paused: { label: "已暂停", tone: "warning" },
  completed: { label: "已完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
};

export function TasksPage() {
  const { data, loading } = useData(() => adapters.listTasks());
  const [type, setType] = useState<TaskType | "all">("all");
  const [status, setStatus] = useState<TaskStatus | "all">("all");

  const tasks = (data ?? []).filter((t) => (type === "all" || t.type === type) && (status === "all" || t.status === status));

  const columns: Column<Task>[] = [
    { key: "title", header: "任务", render: (t) => <div className="cell-strong"><strong>{t.title}</strong><em>{t.id}</em></div> },
    { key: "type", header: "类型", render: (t) => <Badge tone={t.type === "patrol" ? "blue" : "info"}>{t.type === "patrol" ? "巡检" : "运输"}</Badge> },
    { key: "robot", header: "机器人", render: (t) => t.robotName },
    { key: "route", header: "路线", render: (t) => t.routeName },
    { key: "status", header: "状态", render: (t) => <Badge tone={statusMeta[t.status].tone}>{statusMeta[t.status].label}</Badge> },
    { key: "progress", header: "进度", render: (t) => <div className="cell-progress"><ProgressBar value={t.progress} /><span>{t.progress}%</span></div> },
    { key: "time", header: "创建时间", render: (t) => t.createdAt },
  ];

  return (
    <div className="page">
      <ObjectHeader kicker="Tasks" title="任务中心" subtitle="巡检与文件运输任务的统一编排、执行与追踪" badges={[{ label: `${(data ?? []).filter((t) => t.status === "running").length} 进行中`, tone: "blue" }]} />
      <Panel className="list-panel" bodyClassName="panel-flush">
        <div className="list-toolbar">
          <div className="filter-tabs">
            {(["all", "patrol", "transport"] as const).map((t) => (
              <button key={t} type="button" className={type === t ? "on" : ""} onClick={() => setType(t)}>{t === "all" ? "全部类型" : t === "patrol" ? "巡检" : "运输"}</button>
            ))}
          </div>
          <div className="filter-tabs">
            {(["all", "running", "pending", "paused", "completed", "failed"] as const).map((s) => (
              <button key={s} type="button" className={status === s ? "on" : ""} onClick={() => setStatus(s)}>{s === "all" ? "全部状态" : statusMeta[s].label}</button>
            ))}
          </div>
        </div>
        <DataTable columns={columns} rows={tasks} rowKey={(t) => t.id} loading={loading} emptyTitle="暂无任务" onRowClick={(t) => { window.location.hash = `/tasks/${t.id}`; }} />
      </Panel>
    </div>
  );
}

export function TaskDetailPage({ id }: { id: string }) {
  const { data: task } = useData(() => adapters.getTask(id), [id]);
  const tasksQuery = useData(() => adapters.listTasks());
  const [tab, setTab] = useState("overview");
  if (!task) return <div className="page"><EmptyState title="未找到该任务" /></div>;
  const tasks = tasksQuery.data ?? [];

  return (
    <div className="page">
      <Link to="/tasks" className="back-link"><ArrowLeft size={15} />任务中心</Link>
      <ObjectHeader
        kicker={`Task · ${task.id}`}
        title={task.title}
        subtitle={`${task.routeName} · ${task.robotName}`}
        badges={[
          { label: task.type === "patrol" ? "巡检" : "运输", tone: task.type === "patrol" ? "blue" : "info" },
          { label: statusMeta[task.status].label, tone: statusMeta[task.status].tone },
        ]}
        actions={task.status === "running" ? <><Button size="sm" icon={Pause}>暂停</Button><Button size="sm" variant="danger" icon={CircleStop}>终止</Button></> : task.status === "paused" ? <Button size="sm" icon={Play}>恢复</Button> : null}
      />
      <SplitView railTitle="任务" railCount={tasks.length} rail={tasks.map((t) => (
        <ObjectItem key={t.id} active={t.id === task.id} icon={t.type === "patrol" ? ListChecks : Package} title={t.title} meta={`${t.robotName} · ${t.routeName}`} badge={<Badge tone={statusMeta[t.status].tone}>{statusMeta[t.status].label}</Badge>} onClick={() => navigate(`/tasks/${t.id}`)} />
      ))}>
        <Tabs items={[{ id: "overview", label: "概览" }, { id: "exec", label: "执行" }, { id: "timeline", label: "时间线" }]} active={tab} onChange={setTab} />
        {tab === "overview" ? <TaskOverview task={task} /> : null}
        {tab === "exec" ? <TaskExec task={task} /> : null}
        {tab === "timeline" ? <TaskTimeline task={task} /> : null}
      </SplitView>
    </div>
  );
}

function TaskOverview({ task }: { task: Task }) {
  return (
    <div className="workspace">
      <div className="workspace-stats">
        <div className="ws-stat"><em>任务编号</em><strong>{task.id}</strong></div>
        <div className="ws-stat"><em>类型</em><strong>{task.type === "patrol" ? "安全巡检" : "文件运输"}</strong></div>
        <div className="ws-stat"><em>执行机器人</em><strong>{task.robotName}</strong></div>
        <div className="ws-stat"><em>路线</em><strong>{task.routeName}</strong></div>
        <div className="ws-stat"><em>进度</em><strong>{task.progress}%</strong></div>
      </div>
      <div className="ws-section">
        <div className="ws-section-title"><span>执行进度 · {task.currentStep}</span></div>
        <ProgressBar value={task.progress} />
      </div>
      {task.type === "transport" ? (
        <div className="ws-section">
          <div className="ws-section-title"><span>运输流程</span></div>
          <MissionStepper stage={task.transportStage} />
        </div>
      ) : null}
    </div>
  );
}

function TaskExec({ task }: { task: Task }) {
  return (
    <div className="ws-split ws-split-map">
      <div className="ws-media-cell">
        <div className="ws-section-title"><span>路线执行 · Route</span></div>
        <div className="exec-placeholder">任务路线地图画布</div>
      </div>
      <div className="ws-section">
        <div className="ws-section-title"><span>执行状态</span></div>
        <div className="profile-list">
          <div><em>状态</em><strong>{statusMeta[task.status].label}</strong></div>
          <div><em>进度</em><strong>{task.progress}%</strong></div>
          <div><em>当前步骤</em><strong>{task.currentStep}</strong></div>
          {task.type === "transport" ? <div><em>运输阶段</em><strong>{task.transportStage ?? "--"}</strong></div> : null}
        </div>
        {task.type === "transport" ? <MissionStepper stage={task.transportStage} /> : null}
      </div>
    </div>
  );
}

function TaskTimeline({ task }: { task: Task }) {
  const entries = [
    { id: "e1", title: "任务创建", time: task.createdAt, description: `已创建${task.type === "patrol" ? "巡检" : "运输"}任务并绑定路线 ${task.routeName}`, tone: "blue" as const },
    { id: "e2", title: "任务分配", time: task.updatedAt, description: `分配给 ${task.robotName}`, tone: "neutral" as const },
    { id: "e3", title: "执行中", time: "刚刚", description: task.currentStep, tone: task.status === "running" ? "success" as const : "neutral" as const },
  ];
  return (
    <div className="workspace">
      <div className="ws-section-title"><span>事件时间线</span></div>
      <Timeline entries={entries} />
    </div>
  );
}
