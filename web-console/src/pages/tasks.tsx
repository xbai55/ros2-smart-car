import { useEffect, useRef, useState, type FormEvent } from "react";
import { Plus, RefreshCw, X } from "lucide-react";
import { Link } from "../lib/router";
import { useData } from "../hooks/useData";
import { useBusinessSession } from "../hooks/useBusinessSession";
import { formatTime } from "../services/adapters";
import { businessApi, type BusinessSession, type BusinessTask, type PatrolTaskInput } from "../services/businessApi";
import { Badge, Button, EmptyState, Panel } from "../components/ui";
import { DataTable, ObjectHeader, type Column } from "../components/shared";
import type { TaskType } from "../types/domain";
import "../styles/tasks.css";
import { TaskExecutionControls } from "../components/robot/TaskExecutionControls";

type TaskRecord = BusinessTask & { type: TaskType };
const labels: Record<string, string> = { pending: "待执行", running: "进行中", paused: "暂停", completed: "完成", failed: "失败", cancelled: "取消", queued: "排队中", dispatched: "已派发", transporting: "运输中" };
const priorityLabels: Record<string, string> = { low: "低", normal: "普通", high: "高", urgent: "紧急" };
const can = (session: BusinessSession, permission: string) => !!session.user.role?.permissions.some(item => item.name === permission);
const typeLabel = (type: TaskType) => type === "patrol" ? "巡检" : "运输";

async function loadTasks(session: BusinessSession): Promise<TaskRecord[]> {
  const patrol = can(session, "patrol.read"), transport = can(session, "missions.read");
  if (!patrol && !transport) throw new Error("当前账户没有任务查看权限");
  const [patrols, missions] = await Promise.all([
    patrol ? businessApi.listPatrolTasks() : Promise.resolve([]),
    transport ? businessApi.listMissionTasks() : Promise.resolve([]),
  ]);
  return [...patrols.map(item => ({ ...item, type: "patrol" as const })), ...missions.map(item => ({ ...item, type: "transport" as const }))]
    .sort((a, b) => (b.created_at || "").localeCompare(a.created_at || ""));
}

async function loadCatalog(session: BusinessSession) {
  const [robots, maps, routes] = await Promise.allSettled([
    can(session, "robots.read") ? businessApi.listRobots() : Promise.reject(new Error("当前账户没有机器人查看权限")),
    can(session, "maps.read") ? businessApi.listMaps() : Promise.reject(new Error("当前账户没有地图查看权限")),
    can(session, "routes.read") ? businessApi.listRoutes() : Promise.reject(new Error("当前账户没有路线查看权限")),
  ]);
  const problem = (result: PromiseSettledResult<unknown>) => result.status === "rejected" ? (result.reason instanceof Error ? result.reason.message : String(result.reason)) : "";
  return {
    robots: robots.status === "fulfilled" ? robots.value : [],
    maps: maps.status === "fulfilled" ? maps.value : [],
    routes: routes.status === "fulfilled" ? routes.value : [],
    issues: { robots: problem(robots), maps: problem(maps), routes: problem(routes) },
  };
}

function LoginNotice() {
  return <div className="page"><ObjectHeader kicker="Tasks" title="任务中心" subtitle="创建并保存巡检和运输任务"/><Panel><EmptyState title="登录后管理任务" hint="请使用系统账户登录，任务将保存在业务数据库中。"/><div className="task-login"><Link className="btn btn-primary" to="/login?return=%2Ftasks">登录账户</Link></div></Panel></div>;
}

export function TasksPage() {
  const session = useBusinessSession();
  return session ? <TaskList key={session.user.id} session={session}/> : <LoginNotice/>;
}

function TaskList({ session }: { session: BusinessSession }) {
  const query = useData(() => loadTasks(session));
  const [type, setType] = useState("all");
  const [creating, setCreating] = useState(false);
  const [saved, setSaved] = useState<TaskRecord | null>(null);
  const allowed: TaskType[] = [];
  if (can(session, "patrol.manage")) allowed.push("patrol");
  if (can(session, "missions.manage")) allowed.push("transport");
  const columns: Column<TaskRecord>[] = [
    { key: "name", header: "任务", render: task => task.name },
    { key: "type", header: "类型", render: task => typeLabel(task.type) },
    { key: "robot", header: "关联机器人", render: task => task.robot_id || "未分配" },
    { key: "status", header: "业务状态", render: task => labels[task.status] || task.status },
    { key: "created", header: "创建时间", render: task => formatTime(task.created_at) },
  ];
  return <div className="page">
    <ObjectHeader kicker="Tasks" title="任务中心" subtitle="创建并保存业务任务，保存后可查看任务详情" actions={<>{allowed.length > 0 && <Button variant="primary" icon={Plus} onClick={() => { setSaved(null); setCreating(true); }}>新建任务</Button>}<Button icon={RefreshCw} disabled={query.loading} onClick={query.refetch}>刷新</Button></>}/>
    {saved && <div className="task-success" role="status">任务“{saved.name}”已保存。{can(session, saved.type === "patrol" ? "patrol.read" : "missions.read") && <Link to={`/tasks/${saved.id}`}>查看详情</Link>}</div>}
    {!allowed.length && <p className="task-hint">当前账户可查看任务，新建任务需要任务管理权限。</p>}
    <Panel className="list-panel" bodyClassName="panel-flush">
      <div className="list-toolbar"><div className="filter-tabs">{["all", "patrol", "transport"].map(value => <button key={value} className={type === value ? "on" : ""} onClick={() => setType(value)}>{value === "all" ? "全部" : value === "patrol" ? "巡检" : "运输"}</button>)}</div></div>
      {query.error ? <EmptyState title="任务数据不可用" hint={query.error}/> : <DataTable columns={columns} rows={(query.data || []).filter(task => type === "all" || task.type === type)} rowKey={task => task.id} loading={query.loading} emptyTitle="暂无任务记录" onRowClick={task => { window.location.hash = `/tasks/${task.id}`; }}/>}
    </Panel>
    {creating && allowed.length > 0 && <CreateTaskDialog session={session} allowed={allowed} initialType={allowed.includes(type as TaskType) ? type as TaskType : allowed[0]} onClose={() => setCreating(false)} onSaved={task => { setCreating(false); setSaved(task); setType(task.type); query.refetch(); }}/>}
  </div>;
}

function CreateTaskDialog({ session, allowed, initialType, onClose, onSaved }: { session: BusinessSession; allowed: TaskType[]; initialType: TaskType; onClose: () => void; onSaved: (task: TaskRecord) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const submitting = useRef(false);
  const catalog = useData(() => loadCatalog(session));
  const [type, setType] = useState(initialType);
  const [name, setName] = useState(""), [description, setDescription] = useState("");
  const [robotId, setRobotId] = useState(""), [mapId, setMapId] = useState(""), [routeId, setRouteId] = useState("");
  const [targetArea, setTargetArea] = useState(""), [priority, setPriority] = useState<PatrolTaskInput["priority"]>("normal");
  const [cargo, setCargo] = useState(""), [start, setStart] = useState(""), [end, setEnd] = useState(""), [pickupCode, setPickupCode] = useState("");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => { const element = dialog.current; element?.showModal(); return () => element?.close(); }, []);
  const maps = (catalog.data?.maps || []).filter(map => map.active);
  const routes = (catalog.data?.routes || []).filter(route => route.map_id === mapId);
  function close() { if (!submitting.current) onClose(); }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (submitting.current) return;
    if (!name.trim()) { setError("请填写任务名称，不能只输入空格"); return; }
    if (!allowed.includes(type)) { setError("当前账户没有此类任务的管理权限"); return; }
    if (routeId && !routes.some(route => route.id === routeId)) { setError("所选路线不属于当前地图，请重新选择"); return; }
    submitting.current = true; setBusy(true); setError("");
    const common = { name: name.trim(), description: description.trim(), robot_id: robotId || null, map_id: mapId || null, route_id: routeId || null };
    try {
      const result = type === "patrol"
        ? await businessApi.createPatrolTask({ ...common, target_area: targetArea.trim(), priority })
        : await businessApi.createMissionTask({ ...common, cargo_name: cargo.trim(), start_location: start.trim(), end_location: end.trim(), pickup_code: pickupCode.trim() });
      onSaved({ ...result, type });
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)); }
    finally { submitting.current = false; setBusy(false); }
  }
  return <dialog ref={dialog} className="task-dialog" aria-labelledby="create-task-title" onCancel={event => { event.preventDefault(); close(); }}>
    <div className="task-dialog-heading"><h2 id="create-task-title">新建任务</h2><Button variant="ghost" aria-label="关闭新建任务" disabled={busy} onClick={close} icon={X}/></div>
    <form className="task-form" onSubmit={submit}>
      <p className="task-hint">保存后可在任务中心查看。任务保存后不会自动启动机器人。</p>
      <fieldset disabled={busy}>
        <label>任务类型<select value={type} onChange={event => setType(event.target.value as TaskType)}>{allowed.map(value => <option key={value} value={value}>{typeLabel(value)}任务</option>)}</select></label>
        <label>任务名称<input autoFocus required maxLength={128} value={name} placeholder={type === "patrol" ? "例如：实验室晚间巡检" : "例如：送文件到老师办公室"} onChange={event => setName(event.target.value)}/></label>
        <label>说明<textarea value={description} placeholder="填写任务目的或注意事项" onChange={event => setDescription(event.target.value)}/></label>
        <label>关联机器人（可选）<select value={robotId} disabled={catalog.loading || !!catalog.data?.issues.robots || !catalog.data?.robots.length} onChange={event => setRobotId(event.target.value)}><option value="">暂不分配</option>{catalog.data?.robots.map(robot => <option key={robot.id} value={robot.id}>{robot.name}{robot.robot_code ? `（${robot.robot_code}）` : ""}</option>)}</select><small>{catalog.loading ? "正在读取机器人档案…" : catalog.data?.issues.robots || (!catalog.data?.robots.length ? "暂无机器人档案，可先保存任务。" : "使用业务数据库中的机器人档案。")}</small></label>
        <div className="task-form-row">
          <label>关联地图（可选）<select value={mapId} disabled={catalog.loading || !!catalog.data?.issues.maps || !maps.length} onChange={event => { setMapId(event.target.value); setRouteId(""); }}><option value="">暂不关联</option>{maps.map(map => <option key={map.id} value={map.id}>{map.name}</option>)}</select></label>
          <label>关联路线（可选）<select value={routeId} disabled={catalog.loading || !mapId || !!catalog.data?.issues.routes || !routes.length} onChange={event => setRouteId(event.target.value)}><option value="">暂不关联</option>{routes.map(route => <option key={route.id} value={route.id}>{route.name}</option>)}</select></label>
        </div>
        <p className="task-hint">{catalog.data?.issues.maps || catalog.data?.issues.routes || (mapId ? routes.length ? "仅显示所选地图的路线。" : "该地图暂无路线，可先保存任务。" : "选择地图后可关联该地图的路线。")}</p>
        {type === "patrol" ? <div className="task-form-row"><label>巡检区域<input maxLength={128} value={targetArea} placeholder="例如：实验室一楼" onChange={event => setTargetArea(event.target.value)}/></label><label>优先级<select value={priority} onChange={event => setPriority(event.target.value as PatrolTaskInput["priority"])}>{Object.entries(priorityLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label></div> : <>
          <label>运输物品<input value={cargo} placeholder="例如：实验报告" onChange={event => setCargo(event.target.value)}/></label>
          <div className="task-form-row"><label>取件地点<input value={start} placeholder="例如：实验室门口" onChange={event => setStart(event.target.value)}/></label><label>送达地点<input value={end} placeholder="例如：老师办公室" onChange={event => setEnd(event.target.value)}/></label></div>
          <label>取件码（可选）<input maxLength={32} value={pickupCode} onChange={event => setPickupCode(event.target.value)}/></label>
        </>}
      </fieldset>
      {(error || catalog.error) && <div className="task-error" role="alert">{error || catalog.error}</div>}
      <div className="task-form-actions"><Button disabled={busy} onClick={close}>取消</Button><Button type="submit" variant="primary" disabled={busy}>{busy ? "正在保存…" : "保存任务"}</Button></div>
    </form>
  </dialog>;
}

export function TaskDetailPage({ id }: { id: string }) {
  const session = useBusinessSession();
  return session ? <TaskDetail key={`${session.user.id}:${id}`} id={id} session={session}/> : <LoginNotice/>;
}

function TaskDetail({ id, session }: { id: string; session: BusinessSession }) {
  const { data: task, loading, error } = useData(async () => (await loadTasks(session)).find(item => item.id === id), [id]);
  const catalog = useData(() => loadCatalog(session));
  const robot = catalog.data?.robots.find(item => item.id === task?.robot_id);
  const map = catalog.data?.maps.find(item => item.id === task?.map_id);
  const route = catalog.data?.routes.find(item => item.id === task?.route_id);
  return <div className="page"><Link to="/tasks" className="back-link">返回任务中心</Link>{loading ? <EmptyState title="加载中…"/> : error ? <EmptyState title="任务数据不可用" hint={error}/> : !task ? <EmptyState title="未找到该任务"/> : <>
    <ObjectHeader kicker="Task" title={task.name} subtitle="实车任务按导航反馈更新；未派发任务可在地图工作区配置目标" badges={[{ label: `${typeLabel(task.type)}任务`, tone: "blue" }]}/>
    <TaskExecutionControls task={task} kind={task.type === "patrol" ? "patrol" : "delivery"}/>
    <Panel title="任务记录"><div className="profile-list task-profile">
      <div><em>业务状态</em><strong><Badge>{labels[task.status] || task.status}</Badge></strong></div>
      <div><em>关联机器人</em><strong>{robot?.name || task.robot_id || "未分配"}</strong></div>
      <div><em>关联地图</em><strong>{map?.name || task.map_id || "未关联地图"}</strong></div>
      <div><em>关联路线</em><strong>{route?.name || task.route_id || "未关联路线"}</strong></div>
      {task.type === "patrol" ? <><div><em>巡检区域</em><strong>{task.target_area || "未填写"}</strong></div><div><em>优先级</em><strong>{priorityLabels[task.priority || ""] || task.priority || "未记录"}</strong></div></> : <><div><em>运输物品</em><strong>{task.cargo_name || "未填写"}</strong></div><div><em>取件地点</em><strong>{task.start_location || "未填写"}</strong></div><div><em>送达地点</em><strong>{task.end_location || "未填写"}</strong></div><div><em>取件码</em><strong>{task.pickup_code || "未设置"}</strong></div></>}
      <div><em>业务记录进度</em><strong>{task.progress == null ? "未记录" : task.progress + "%"}</strong></div>
      <div><em>创建时间</em><strong>{formatTime(task.created_at)}</strong></div><div><em>更新时间</em><strong>{formatTime(task.updated_at)}</strong></div><div><em>说明</em><strong>{task.description || "未填写"}</strong></div>
    </div></Panel>
  </>}</div>;
}
