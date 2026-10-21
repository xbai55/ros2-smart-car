import { useEffect, useRef, useState } from "react";
import { businessApi, createMapRequestId, type ManagedMap } from "../../services/businessApi";
import { useBusinessSession } from "../../hooks/useBusinessSession";
import { useData } from "../../hooks/useData";
import { createRobotApi, type NavigationRuntimeState, type NavigationTaskState } from "../../robotApi";
import type { Calibration, DrawingDescriptor, Place, Point } from "../../labNavigation";
import { Link } from "../../lib/router";
import { acceptTaskState } from "../../navigationTaskState";
import { CorridorSetup } from './CorridorSetup';

type Api = ReturnType<typeof createRobotApi>;
const finished = new Set(["idle", "completed", "failed", "cancelled"]);

export function NavigationSetup({ api, maps, online, locked, locating, setLocating, initialPoint, selectedMapId, onSelectMap, onRuntime, direct = false }: {
  api: Api; maps: ManagedMap[]; online: boolean; locked: boolean; locating: boolean; setLocating: (value: boolean) => void; initialPoint: Point | null; selectedMapId?: string; onSelectMap?: (id: string) => void; onRuntime?: (value: NavigationRuntimeState) => void; direct?: boolean;
}) {
  const session = useBusinessSession();
  const [runtime, setRuntime] = useState<NavigationRuntimeState | null>(null);
  const [assetId, setAssetId] = useState(""), [yaw, setYaw] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const chosenAssetId = selectedMapId ?? assetId;
  useEffect(() => { if (runtime) onRuntime?.(runtime); }, [runtime, onRuntime]);
  const slamMaps = maps.filter(m => m.metadata.source === "slam");
  const manage = !!session?.user.role?.permissions.some(p => p.name === "maps.manage");
  useEffect(() => { if (!assetId && slamMaps.length) setAssetId(slamMaps[0].id); }, [maps, assetId]);
  useEffect(() => {
    if (!online) return;
    let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try { const value = await api.getNavigationRuntime(); if (active) setRuntime(value); }
      catch { /* Loading a legacy vehicle leaves the established single-goal UI available. */ }
      if (active) timer = setTimeout(() => void poll(), 1500);
    };
    void poll(); return () => { active = false; clearTimeout(timer); };
  }, [api, online]);
  async function action(work: () => Promise<NavigationRuntimeState>) {
    setBusy(true); setError("");
    try { setRuntime(await work()); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <details className="navigation-setup" open={!runtime?.localized || !!selectedMapId && !!runtime?.map_id && selectedMapId !== runtime.map_id}>
    <summary>加载地图与初始定位</summary>
    <p>{runtime?.message || "新建图可使用当前会话；历史地图需先加载并重新定位。"}</p>
    <div className="navigation-operation-row"><label>导航使用的 SLAM 地图<select aria-label="导航栅格地图" value={chosenAssetId} disabled={locked || busy} onChange={e => { if (onSelectMap) onSelectMap(e.target.value); else setAssetId(e.target.value); }}><option value="">请选择</option>{slamMaps.map(m => <option key={m.id} value={m.id}>{m.name}</option>)}</select></label>
      <button className="btn btn-outline" disabled={!online || !manage || !chosenAssetId || locked || busy || !runtime?.control_session_id} onClick={() => void action(() => businessApi.loadNavigationMap(chosenAssetId, runtime!.control_session_id!))}>加载并启动定位</button>
      <button className="btn btn-outline" disabled={!online || !runtime?.digest || locked || busy} onClick={() => setLocating(!locating)}>{locating ? "取消选位" : "在 SLAM 图中设置当前位置"}</button>
      {initialPoint && <><span>位置：{initialPoint.x.toFixed(2)}, {initialPoint.y.toFixed(2)} m</span><label>车头朝向（度）<input aria-label="初始定位朝向" type="number" min={-180} max={180} value={yaw} onChange={e => setYaw(Number(e.target.value))}/></label><button className="btn btn-primary" disabled={locked || busy} onClick={() => void action(() => api.setInitialPose({ ...initialPoint, yaw: yaw * Math.PI / 180 }, runtime!.digest!))}>发送初始位置</button></>}
    </div>
    <small>加载时小车须处于停止状态。初始朝向按 SLAM 坐标填写：沿 X 正方向为 0°，沿 Y 正方向为 90°；画布旋转会改变屏幕方向。请核对雷达与墙体重合。{direct ? "定位就绪后可直接选点导航，无需上传平面图或四点对齐。" : "需要叠加参考平面图时，再进行图纸对齐。"}</small>
    {locating && <p role="status">请点击 SLAM 图中小车实际所在位置，然后填写车头朝向。</p>}
    {error && <p className="navigation-error" role="alert">{error}</p>}
  </details>;
}

export function NavigationTaskPanel({ api, online, aligned, calibration, drawing, mapKey, target, mapId, controlSessionId, onActive }: {
  api: Api; online: boolean; aligned: boolean; calibration: Calibration | null; drawing: DrawingDescriptor; mapKey: string;
  target: Place | null; mapId?: string; controlSessionId?: string | null; onActive: (active: boolean) => void;
}) {
  const session = useBusinessSession();
  const [kind, setKind] = useState<"delivery" | "patrol">("delivery"), [returning, setReturning] = useState(false);
  const [cycles, setCycles] = useState(1), [dwellSec, setDwellSec] = useState(5);
  const [queue, setQueue] = useState<Place[]>([]), [name, setName] = useState("文件运输");
  const [robotId, setRobotId] = useState(""), [taskId, setTaskId] = useState("");
  const [task, setTask] = useState<NavigationTaskState>({ state: "idle", message: "选择目的地后创建运输，或添加多个巡航站点" });
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [pollError, setPollError] = useState("");
  const requestId = useRef(createMapRequestId());
  const catalog = useData(async () => {
    if (!session) return { robots: [], tasks: [] };
    const permissions = session.user.role?.permissions.map(p => p.name) || [];
    const robots = await businessApi.listRobots();
    const records = kind === "delivery" ? permissions.includes("missions.read") ? await businessApi.listMissionTasks() : [] : permissions.includes("patrol.read") ? await businessApi.listPatrolTasks() : [];
    return { robots, tasks: records.filter(t => ["queued", "pending"].includes(t.status)) };
  }, [session?.user.id, kind]);
  const active = !finished.has(task.state);
  const permitted = !!session?.user.role?.permissions.some(p => p.name === (kind === "delivery" ? "missions.manage" : "patrol.manage"));
  useEffect(() => { onActive(active); }, [active, onActive]);
  useEffect(() => {
    setQueue([]); requestId.current = createMapRequestId();
  }, [mapKey, drawing.id, drawing.revision, calibration?.matrix.join(",")]);
  useEffect(() => {
    if (!online) return;
    let alive = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        let value = await api.getNavigationTask();
        if (value.task_id && value.kind && session) value = await businessApi.getTaskExecution(value.kind, value.task_id);
        if (alive) { setTask(previous => acceptTaskState(previous, value)); setPollError(""); }
      } catch (e) { if (alive) setPollError((e as Error).message); }
      if (alive) timer = setTimeout(() => void poll(), 1200);
    };
    void poll(); return () => { alive = false; clearTimeout(timer); };
  }, [api, online, session?.user.id]);
  async function create() {
    if (!calibration || !aligned || active || busy) return;
    const points = kind === "delivery" ? target ? [target] : [] : queue;
    if (!points.length) return;
    setBusy(true); setError("");
    try {
      const result = await businessApi.createNavigationTask({ run_id: requestId.current, task_id: taskId || undefined, kind, name,
        robot_id: robotId, map_id: mapId, map_key: mapKey, control_session_id: controlSessionId, calibration_matrix: calibration.matrix,
        calibration_drawing: drawing, waypoints: points, return_to_start: returning,
        ...(kind === 'patrol' ? {cycles, dwell_sec: dwellSec} : {}) });
      setTask(previous => acceptTaskState(previous, result)); requestId.current = createMapRequestId();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function act(action: string) {
    if (!task.task_id || !task.run_id || !task.kind || busy) return;
    setBusy(true); setError("");
    try { const next = await businessApi.taskExecutionAction(task.kind, task.task_id, task.run_id, action); setTask(previous => acceptTaskState(previous, next)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const actions: Record<string, [string, string][]> = {
    waiting_load: [["loaded", "已装件，开始运输"]], prepared: [["start", "开始巡航"]],
    planning: [["pause", "暂停"]], running: [["pause", "暂停"]], returning: [["pause", "暂停"]], dwelling: [["pause", "暂停"]],
    paused: [["resume", "重新规划并恢复"]], waiting_handover: [["handover", task.return_to_start ? "已取件，返回起点" : "已取件，完成任务"]],
  };
  return <section className="navigation-task-panel">
    <strong>文件运输与多点巡航</strong>
    <CorridorSetup target={target} calibration={calibration} mapKey={mapKey} controlSessionId={controlSessionId} locked={active || !online}/>
    {!active && <>
      <label>任务类型<select aria-label="导航任务类型" value={kind} onChange={e => { const next = e.target.value as typeof kind; setKind(next); setName(next === "delivery" ? "文件运输" : "多点巡航"); setTaskId(""); }}><option value="delivery">文件运输</option><option value="patrol">多点巡航</option></select></label>
      <label>业务任务<select aria-label="关联业务任务" value={taskId} onChange={e => setTaskId(e.target.value)}><option value="">新建任务</option>{catalog.data?.tasks.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
      {!taskId && <><label>任务名称<input maxLength={128} value={name} onChange={e => setName(e.target.value)}/></label><label>关联小车<select aria-label="执行任务的小车" value={robotId} onChange={e => setRobotId(e.target.value)}><option value="">请选择</option>{catalog.data?.robots.map(r => <option key={r.id} value={r.id}>{r.name}</option>)}</select></label></>}
      {kind === "patrol" ? <><button className="btn btn-outline" disabled={!target || queue.length >= 30} onClick={() => { if (target) setQueue([...queue, { ...target }]); }}>将当前目的地加入巡航</button><ol>{queue.map((p, i) => <li key={i}>{p.name}<button aria-label={`移除第${i + 1}站`} onClick={() => setQueue(queue.filter((_, n) => n !== i))}>移除</button></li>)}</ol></> : <p>送达：{target?.name || "请在地图上选择目的地"}</p>}
      {kind === 'patrol' && <><label>巡航圈数<input type="number" min={1} max={100} step={1} value={cycles} onChange={e => setCycles(Number(e.target.value))}/></label><label>每站停留（秒）<input type="number" min={0} max={600} value={dwellSec} onChange={e => setDwellSec(Number(e.target.value))}/></label><p>按站点顺序巡航，停留时持续观察；报警后继续执行。实际达到20米、10分钟后才满足文档的距离与时间指标。</p></>}
      <label><input type="checkbox" checked={returning} onChange={e => setReturning(e.target.checked)}/>{kind === 'patrol' ? '完成后返回巡航起点' : '完成后返回装件起点'}</label>
      <button className="btn btn-primary navigation-action" disabled={!permitted || !online || !aligned || busy || !!pollError || (!taskId && !robotId) || !(kind === "delivery" ? target : queue.length)} onClick={() => void create()}>{busy ? "正在创建…" : "创建执行任务"}</button>
    </>}
    <p role="status">{task.message}</p>
    {task.goals && <small>已完成检查点 {task.completed_stops || 0} / {task.total_stops || task.goals.length}；里程 {task.distance_m?.toFixed(1) ?? '—'} m；执行时长 {Math.floor(task.elapsed_sec || 0)} 秒</small>}
    {active && (actions[task.state] || []).map(([action, label]) => <button key={action} className="btn btn-primary navigation-action" disabled={busy || !online || !!pollError} onClick={() => void act(action)}>{label}</button>)}
    {active && <button className="btn btn-outline navigation-action" disabled={busy || !online} onClick={() => void act("cancel")}>取消任务并停车</button>}
    {task.task_id && <Link to={`/tasks/${task.task_id}`}>查看业务任务记录</Link>}
    {(error || pollError || catalog.error) && <p className="navigation-error" role="alert">{error || pollError || catalog.error}</p>}
    {!session && <p>登录系统账户后可保存并执行任务。</p>}
  </section>;
}
