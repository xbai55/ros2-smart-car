import { useEffect, useRef, useState, type FormEvent } from "react";
import { businessApi, createMapRequestId, type AssistantDraft, type AssistantExecution, type AssistantTurn } from "../services/businessApi";
import { Link } from "../lib/router";
import { useBusinessSession } from "../hooks/useBusinessSession";

const labels: Record<string, string> = {
  navigate: "前往地点", patrol: "沿路线巡检", deliver: "取件与交接",
  observe_target: "静止观察", patrol_search: "沿路线搜索",
  move_relative: "短距离前进",
};

const stepDetails: Record<string, string> = {
  deliver: "前往取件点 → 人工确认装件 → 前往送达点 → 人工确认交接",
  observe_target: "静止观察 → 发现目标后确认静止 → 等待人工处理",
  patrol_search: "巡检一圈 → 找到目标后停车 → 等待人工处理",
  move_relative: "只向前 · 速度上限0.10米/秒 · 最长4.5秒 · 里程计到距停车，异常立即停止",
};

const capabilityReasons: Record<string, string> = {
  unsupported_protocol_or_capability: "车端版本尚未支持此能力",
  vehicle_not_ready: "车端尚未就绪",
  telemetry_stale_or_unknown: "缺少新鲜的车端状态",
  active_map_required: "尚无已加载的导航地图",
  emergency_stop_active_or_unknown: "急停状态待核对",
  model_identity_required: "视觉模型版本待核对",
  vehicle_acceptance_required: "当前版本缺少此能力的实车验收",
};

const executionLabels: Record<string, string> = {
  queued: "已确认 · 等待执行", running: "执行中", paused: "已暂停",
  waiting_human: "等待人工处理", completed: "已完成", cancelled: "已取消", failed: "执行失败",
  dispatching: "正在联系车端", unconfirmed: "派发待核实", action_pending: "等待车端确认",
  cancel_requested: "取消待核实",
};
const humanActions: Record<string, [string, string]> = {
  waiting_load: ["loaded", "已装件"],
  waiting_handover: ["handover", "已交接"],
  found: ["continue_plan", "结束搜索并继续计划"],
};

export function AssistantConversation({ canSend, preferredSession, update, onQueryingChange }: {
  canSend: boolean; preferredSession?: string; update?: AssistantExecution; onQueryingChange?: (querying: boolean) => void;
}) {
  const session = useBusinessSession();
  const permissions = new Set(session?.user.role?.permissions.map(p => p.name) ?? []);
  const canTrial = ["assistant.settings", "assistant.use", "robots.manage", "robots.control"].every(p => permissions.has(p));
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessions, setSessions] = useState<{id: string; created_at: string}[]>([]);
  const [turns, setTurns] = useState<AssistantTurn[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [confirming, setConfirming] = useState<string | null>(null);
  const attempt = useRef<{ id: string; text: string } | null>(null);

  useEffect(() => { onQueryingChange?.(busy || loading); }, [busy, loading, onQueryingChange]);

  useEffect(() => {
    const controller = new AbortController();
    businessApi.assistantSessions(controller.signal).then(result => {
      setSessions(result.items);
      setSessionId(current => current ?? preferredSession ?? result.items[0]?.id ?? null);
    }).catch(error => {
      if (!controller.signal.aborted) setError(error.message);
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (preferredSession && preferredSession !== sessionId && !busy && !confirming && !input.trim()) select(preferredSession);
    // Switch when a new confirmation event arrives, without forcing later history selections.
  }, [preferredSession]);

  useEffect(() => {
    if (!sessionId) return;
    const controller = new AbortController();
    businessApi.assistantMessages(sessionId, controller.signal).then(result => {
      if (!controller.signal.aborted) setTurns(current => {
        const saved = new Set(result.items.map(item => item.client_id));
        const replies = new Map(current.filter(item => item.reply).map(item => [item.client_id, item]));
        return [...result.items.map(item => {
          const local = replies.get(item.client_id);
          return local && (!item.reply || (local.reply?.plan?.execution?.version ?? 0) >
            (item.reply.plan?.execution?.version ?? 0)) ? local : item;
        }),
          ...current.filter(item => !saved.has(item.client_id))];
      });
    }).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [sessionId]);

  async function send(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy || loading) return;
    setBusy(true);
    setError("");
    if (attempt.current?.text !== text) attempt.current = { id: createMapRequestId(), text };
    try {
      let id = sessionId;
      if (!id) {
        const created = await businessApi.createAssistantSession();
        id = created.id;
        setSessionId(created.id);
        setSessions(items => [{id: created.id, created_at: new Date().toISOString()}, ...items]);
      }
      const result = await businessApi.sendAssistantMessage(id, attempt.current.id, text);
      setTurns(items => [...items.filter(item => item.client_id !== result.client_id), result]);
      setInput("");
      attempt.current = null;
    } catch (error) {
      setError(error instanceof Error ? error.message : "暂时无法获取助手回复");
    } finally {
      setBusy(false);
    }
  }

  function select(id: string | null) {
    setTurns([]);
    setError("");
    setInput("");
    attempt.current = null;
    setSessionId(id);
  }

  function applyExecution(execution: AssistantExecution) {
    setTurns(items => items.map(turn => {
      const plan = turn.reply?.plan;
      if (!turn.reply || !plan || plan.id !== execution.plan_id ||
          (plan.execution && plan.execution.version > execution.version)) return turn;
      return {...turn, reply: {...turn.reply, plan: {...plan, state: "confirmed", execution}}};
    }));
  }

  useEffect(() => { if (update) applyExecution(update); }, [update]);

  async function confirm(plan: AssistantDraft, trial = false) {
    if (confirming) return;
    setConfirming(plan.id);
    setError("");
    try {
      if (trial) await businessApi.authorizeAssistantTrial(plan);
      applyExecution(await businessApi.confirmAssistantPlan(plan));
    }
    catch (error) { setError(error instanceof Error ? error.message : "无法确认这份计划"); }
    finally { setConfirming(null); }
  }

  async function act(execution: AssistantExecution, action: string) {
    if (confirming) return;
    setConfirming(execution.plan_id);
    setError("");
    try { applyExecution(await businessApi.assistantExecutionAction(execution, action)); }
    catch (error) { setError(error instanceof Error ? error.message : "操作未确认"); }
    finally { setConfirming(null); }
  }

  async function refresh(plan: AssistantDraft) {
    if (confirming || !sessionId) return;
    setConfirming(plan.id); setError("");
    try {
      await businessApi.refreshAssistantPlan(plan);
      const result = await businessApi.assistantMessages(sessionId);
      setTurns(result.items);
    } catch (error) { setError(error instanceof Error ? error.message : "无法重新核验任务"); }
    finally { setConfirming(null); }
  }

  return <div className="assistant-conversation">
    <div className="assistant-history-select">
      <label>会话 <select value={sessionId ?? ""} disabled={busy || loading || !!confirming} onChange={event => select(event.target.value || null)}>
        <option value="">新会话</option>
        {sessions.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("zh-CN")}</option>)}
      </select></label>
      {preferredSession && preferredSession !== sessionId && <button type="button" className="btn btn-outline"
        disabled={busy || !!confirming} onClick={() => select(preferredSession)}>查看待确认会话</button>}
    </div>
    <div role="log" aria-label="助手对话" className="assistant-transcript">
      {turns.map(turn => <div key={turn.id} className="assistant-turn">
        <p><strong>你</strong> {turn.text}</p>
        {turn.reply ? <p><strong>智巡</strong> {turn.reply.text}</p> : <small>此消息尚无回复</small>}
        {turn.reply?.report_id && <Link to={`/assistant/reports/${encodeURIComponent(turn.reply.report_id)}`}>查看异常报告</Link>}
        {turn.reply?.plan && <div className="assistant-draft">
          <strong>任务草案</strong>
          <ol>{turn.reply.plan.steps.map((step, index) => <li key={index}>
            {labels[step.action] ?? step.action}{step.target ? ` · ${step.target}` : ""}{step.cargo ? ` · ${step.cargo}` : ""}
            {step.resources.some(resource => resource.names.length) && ` · ${step.resources.flatMap(resource => resource.names).join(" → ")}`}
            {stepDetails[step.action] && <small className="assistant-step-detail">{stepDetails[step.action]}</small>}
            {typeof step.distance_m === "number" && <small>本次前进距离：{Math.round(step.distance_m * 100)}厘米</small>}
            {!step.capability.executable && <small className="assistant-step-detail assistant-step-blocked">
              {step.capability.reasons?.map(reason => capabilityReasons[reason]).filter(Boolean).join(" · ") || "当前不可执行"}
            </small>}
          </li>)}</ol>
          {canSend && (turn.reply.plan.state === "expired" ||
            (turn.reply.plan.execution && ["completed","cancelled","failed"].includes(turn.reply.plan.execution.state))) &&
            <button type="button" className="btn btn-outline" disabled={!!confirming}
              onClick={() => void refresh(turn.reply!.plan!)}>重新核验为新草案</button>}
          {turn.reply.plan.execution ? <><small role="status">
            {executionLabels[turn.reply.plan.execution.state] ?? turn.reply.plan.execution.state}
          </small>
            <a href={`#/system/diagnostics/executions/${encodeURIComponent(turn.reply.plan.execution.id)}`}>查看执行诊断</a>
            {turn.reply.plan.execution.message && <p>{turn.reply.plan.execution.message}</p>}
            {canSend && !["cancel_requested", "completed", "cancelled", "failed"].includes(turn.reply.plan.execution.state) &&
              <button type="button" className="btn btn-outline" disabled={!!confirming}
                onClick={() => void act(turn.reply!.plan!.execution!, "cancel")}>取消计划</button>}
            {canSend && turn.reply.plan.execution.state === "paused" &&
              turn.reply.plan.steps.every(step => step.action !== "move_relative" && step.capability.executable) &&
              <button type="button" className="btn btn-outline" disabled={!!confirming}
                onClick={() => void act(turn.reply!.plan!.execution!, "resume")}>核对后恢复</button>}
            {canSend && turn.reply.plan.execution.state === "waiting_human" &&
              humanActions[turn.reply.plan.execution.vehicle_state ?? ""] &&
              <button type="button" className="btn btn-primary" disabled={!!confirming}
                onClick={() => void act(turn.reply!.plan!.execution!, humanActions[turn.reply!.plan!.execution!.vehicle_state!][0])}>
                {humanActions[turn.reply.plan.execution.vehicle_state ?? ""][1]}
              </button>}
          </> : turn.reply.plan.state === "expired" || turn.reply.plan.expires_at * 1000 <= Date.now()
            ? <small>草案已过期</small>
            : <><small>草案等待人工确认</small>
              {canSend && <button type="button" className="btn btn-outline"
                disabled={!!confirming || !turn.reply.plan.steps.every(step => step.capability.executable)}
                onClick={() => void confirm(turn.reply!.plan!)}>{confirming === turn.reply.plan.id ? "正在核验…" : "确认整份计划"}</button>}
              {canSend && canTrial && turn.reply.plan.steps.length === 1 &&
                ["observe_target","move_relative"].includes(turn.reply.plan.steps[0].action) &&
                !turn.reply.plan.steps[0].capability.executable &&
                turn.reply.plan.steps[0].capability.supported && turn.reply.plan.steps[0].capability.ready &&
                <div><small>现场测试仅授权这份计划，不登记正式实车验收。请先核对场地和现场人员。</small>
                  <button type="button" className="btn btn-outline" disabled={!!confirming}
                    onClick={() => void confirm(turn.reply!.plan!, true)}>确认并执行一次现场测试</button></div>}
            </>}
        </div>}
      </div>)}
      {busy && <p role="status">正在查询与整理…</p>}
    </div>
    {error && <p role="alert">{error}</p>}
    {canSend && <form onSubmit={send} className="assistant-composer">
      <textarea aria-label="发送给智巡助手的消息" placeholder="例如：现在机器人在哪里？" maxLength={2000}
        value={input} disabled={busy || loading} onChange={event => setInput(event.target.value)} rows={2} />
      <button className="btn btn-primary" type="submit" disabled={busy || loading || !input.trim()}>发送</button>
    </form>}
  </div>;
}
