import { ClipboardCheck } from "lucide-react";
import { Link } from "../../lib/router";
import type { AssistantDraft, AssistantExecution } from "../../services/businessApi";

const labels: Record<string, string> = {
  navigate: "前往地点", patrol: "沿路线巡检", deliver: "取件与交接",
  observe_target: "静止观察", patrol_search: "沿路线搜索", move_relative: "短距离前进",
};
const stepDetails: Record<string, string> = {
  deliver: "前往取件点 → 人工确认装件 → 前往送达点 → 人工确认交接",
  observe_target: "静止观察 → 发现目标后确认静止 → 等待人工处理",
  patrol_search: "巡检一圈 → 找到目标后停车 → 等待人工处理",
  move_relative: "只向前 · 速度上限 0.10 米/秒 · 最长 4.5 秒 · 里程计到距停车，异常立即停止",
};
const capabilityReasons: Record<string, string> = {
  unsupported_protocol_or_capability: "车端版本尚未支持此能力", vehicle_not_ready: "车端尚未就绪",
  telemetry_stale_or_unknown: "缺少新鲜的车端状态", active_map_required: "尚无已加载的导航地图",
  emergency_stop_active_or_unknown: "急停状态待核对", model_identity_required: "视觉模型版本待核对",
  vehicle_acceptance_required: "当前版本缺少此能力的实车验收",
};
const executionLabels: Record<string, string> = {
  queued: "已确认，等待执行", running: "执行中", paused: "已暂停",
  waiting_human: "等待人工处理", completed: "已完成", cancelled: "已取消", failed: "执行失败",
  dispatching: "正在联系车端", unconfirmed: "派发待核实", action_pending: "等待车端确认",
  cancel_requested: "取消待核实",
};
export const vehiclePhases: Record<string, string> = {
  navigating: "导航中", running: "运行中", waiting_load: "等待装件",
  waiting_handover: "等待交接", paused: "已暂停", dwelling: "驻留中", found: "已找到目标",
  observing: "观察中", searching: "搜索中", completed: "已完成", finished: "已结束",
  failed: "执行失败", fault: "故障", cancelled: "已取消", not_found: "未找到目标",
};
const humanActions: Record<string, [string, string]> = {
  waiting_load: ["loaded", "已装件"], waiting_handover: ["handover", "已交接"],
  found: ["continue_plan", "结束搜索并继续计划"],
};
const terminal = ["completed", "cancelled", "failed"];

export type PlanActions = {
  confirm: (plan: AssistantDraft, trial?: boolean) => void;
  act: (execution: AssistantExecution, action: string) => void;
  refresh: (plan: AssistantDraft) => void;
};

export function AssistantPlanCard({plan, canSend, canTrial, pending, error, actions}: {
  plan: AssistantDraft; canSend: boolean; canTrial: boolean; pending: string | null; error?: string; actions: PlanActions;
}) {
  const execution = plan.execution;
  const expired = plan.state === "expired" || plan.expires_at * 1000 <= Date.now();
  const isDraft = plan.state === "draft" && !expired;
  const isTerminal = !!execution && terminal.includes(execution.state);
  const human = execution?.state === "waiting_human" ? humanActions[execution.vehicle_state ?? ""] : undefined;
  const phase = execution && vehiclePhases[execution.vehicle_state ?? ""];
  const step = execution && plan.steps[execution.step_index];
  const first = plan.steps[0];
  const status = execution ? executionLabels[execution.state] ?? "状态待核实" : isDraft ? "等待人工确认" :
    expired ? "草案已过期" : "计划状态待核实";
  return <article className="assistant-card assistant-draft">
    <div className="assistant-card-heading"><ClipboardCheck size={16} aria-hidden="true" />
      <strong>{execution ? "业务任务" : "操作确认"}</strong><span role="status">{status}</span></div>
    {execution && <>
      {step && !isTerminal && <p>步骤 {execution.step_index + 1} / {plan.steps.length} · {labels[step.action] ?? step.action}</p>}
      {phase && <p>车端回报 · {phase}</p>}
      {execution.message && <p>{execution.message}</p>}
      <Link to={`/system/diagnostics/executions/${encodeURIComponent(execution.id)}`}>查看执行诊断</Link>
    </>}
    <details open={isDraft ? true : undefined}>
      <summary>{execution ? "查看计划步骤" : "核对计划步骤"}</summary>
      <ol>{plan.steps.map((item, index) => <li key={index}>
        {labels[item.action] ?? item.action}{item.target && ` · ${item.target}`}{item.cargo && ` · ${item.cargo}`}
        {item.resources.some(resource => resource.names.length) && ` · ${item.resources.flatMap(resource => resource.names).join(" → ")}`}
        {stepDetails[item.action] && <small className="assistant-step-detail">{stepDetails[item.action]}</small>}
        {typeof item.distance_m === "number" && <small className="assistant-step-detail">前进 {Math.round(item.distance_m * 100)} 厘米</small>}
        {!item.capability.executable && <small className="assistant-step-detail assistant-step-blocked">
          {item.capability.reasons?.map(reason => capabilityReasons[reason]).filter(Boolean).join(" · ") || "当前不可执行"}
        </small>}
      </li>)}</ol>
    </details>
    {error && <small className="assistant-error" role="alert">{error}</small>}
    {canSend && <div className="assistant-card-actions">
      {((!execution && expired) || isTerminal) && <button type="button" className="btn btn-outline"
        disabled={!!pending} onClick={() => actions.refresh(plan)}>重新核验为新草案</button>}
      {execution && !isTerminal && execution.state !== "cancel_requested" &&
        <button type="button" className="btn btn-outline" disabled={!!pending}
          onClick={() => actions.act(execution, "cancel")}>取消计划</button>}
      {execution?.state === "paused" && plan.steps.every(item => item.action !== "move_relative" && item.capability.executable) &&
        <button type="button" className="btn btn-outline" disabled={!!pending}
          onClick={() => actions.act(execution, "resume")}>核对后恢复</button>}
      {execution && human && <button type="button" className="btn btn-primary" disabled={!!pending}
        onClick={() => actions.act(execution, human[0])}>{human[1]}</button>}
      {isDraft && !execution && <button type="button" className="btn btn-outline"
        disabled={!!pending || !plan.steps.every(item => item.capability.executable)}
        onClick={() => actions.confirm(plan)}>{pending === plan.id ? "正在核验…" : "确认整份计划"}</button>}
      {isDraft && !execution && canTrial && plan.steps.length === 1 &&
        ["observe_target", "move_relative"].includes(first.action) && !first.capability.executable &&
        first.capability.supported && first.capability.ready && <div>
          <small>现场测试仅授权这份计划。请先核对场地和现场人员。</small>
          <button type="button" className="btn btn-outline" disabled={!!pending}
            onClick={() => actions.confirm(plan, true)}>确认并执行一次现场测试</button>
        </div>}
    </div>}
  </article>;
}
