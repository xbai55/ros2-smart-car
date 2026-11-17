import { useEffect, useRef, useState } from "react";
import { businessApi, type BusinessTask } from "../../services/businessApi";
import type { NavigationTaskState } from "../../robotApi";
import { useBusinessSession } from "../../hooks/useBusinessSession";
import { Link } from "../../lib/router";
import { acceptTaskState } from "../../navigationTaskState";

export function TaskExecutionControls({ task, kind }: { task: BusinessTask; kind: "delivery" | "patrol" }) {
  const session = useBusinessSession();
  const [state, setState] = useState<NavigationTaskState | null>(task.execution || null);
  const current = useRef(state); current.current = state;
  const [recreate, setRecreate] = useState(false);
  const [error, setError] = useState(""), [busy, setBusy] = useState(false);
  const manage = !!session?.user.role?.permissions.some(p => p.name === (kind === "delivery" ? "missions.manage" : "patrol.manage"));
  useEffect(() => {
    current.current=task.execution || null; setState(task.execution || null); setRecreate(false);
    let active = true, timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (current.current?.poll_required === false || (current.current?.next_poll_at || 0)>Date.now()/1000) {
        if(active) timer=setTimeout(() => void poll(),2500);
        return;
      }
      try { const value = await businessApi.getTaskExecution(kind, task.id); if (active) { setState(previous => acceptTaskState(previous, value)); setError(""); } }
      catch (e) { if (active) setError((e as Error).message); }
      if (active) timer = setTimeout(() => void poll(), 2500);
    };
    if (task.execution) void poll();
    return () => { active = false; clearTimeout(timer); };
  }, [kind, task.id]);
  async function act(action: string) {
    if (!state?.run_id || busy) return;
    setBusy(true); setError("");
    try {
      const next = await businessApi.taskExecutionAction(kind, task.id, state.run_id, action === 'recreate' ? 'cancel' : action);
      setState(previous => acceptTaskState(previous, next));
      if (action === 'recreate') {
        if(next.state !== 'cancelled') throw new Error('旧请求尚未确认取消');
        setRecreate(true);
      }
    }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  const actions: Record<string, [string, string][]> = {
    unconfirmed: [["retry", "核对并重试原请求"]], waiting_load: [["loaded", "已装件，开始运输"]], prepared: [["start", "开始巡航"]],
    planning: [["pause", "暂停"]], running: [["pause", "暂停"]], returning: [["pause", "暂停"]], dwelling: [["pause", "暂停"]], paused: [["resume", "重新规划并恢复"]],
    waiting_handover: [["handover", state?.return_to_start ? "已取件，返回起点" : "已取件，完成任务"]],
  };
  return <section className="navigation-setup"><strong>实车执行</strong>{!state ? <p>尚未配置地图目标。<Link to="/robots/r-001/run">进入地图与导航，选择此业务任务并配置目标</Link></p> : <>
    <p role="status">{state.message}</p>{state.updated_at && <small>车端记录时间：{new Date(state.updated_at * 1000).toLocaleString("zh-CN")}</small>}
    {manage && <div className="map-row-actions">{(actions[state.state] || []).map(([action, label]) => <button key={action} className="btn btn-outline" disabled={busy || !!error && action !== "retry" || state.sync_state === "cancel_pending"} onClick={() => void act(action)}>{label}</button>)}{!new Set(["idle", "completed", "cancelled", "failed"]).has(state.state) && <button className="btn btn-outline" disabled={busy} onClick={() => void act("cancel")}>取消并停车</button>}{!["idle","completed","cancelled","failed"].includes(state.state) && <button className="btn btn-outline" disabled={busy} onClick={() => void act('recreate')}>取消旧任务并重新创建</button>}</div>}
    {state && ["completed","failed","cancelled"].includes(state.state) && !recreate && <Link to="/robots/r-001/run">进入地图新建任务</Link>}
    {recreate && <p>旧请求已确认取消。<Link to="/robots/r-001/run">进入地图并新建任务</Link></p>}
  </>}{error && <p role="alert" className="navigation-error">状态未确认：{error}</p>}</section>;
}
