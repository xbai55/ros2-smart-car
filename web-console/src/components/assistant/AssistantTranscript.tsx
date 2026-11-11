import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { Activity, ArrowDown, Bot, Check, Copy, FileText, RotateCcw } from "lucide-react";
import { Link } from "../../lib/router";
import type { AssistantExecution, AssistantTool, AssistantToolResult } from "../../services/businessApi";
import { currentPlan, followsLatest, type ChatTurn } from "./chatState";
import { AssistantMarkdown } from "./AssistantMarkdown";
import { AssistantPlanCard, type PlanActions } from "./AssistantPlanCard";

const toolNames: Record<string, string> = {
  get_system_health: '检查系统健康', query_system_logs: '查询系统诊断日志', get_vision_status: '查询视觉组件',
  inspect_camera_frame: '分析现场单帧', execute_plan: '提交任务执行', control_execution: '控制本人任务',
  stop_robot: '停止车辆', update_vision_settings: '调整视觉设置', recover_vision: '恢复视觉服务',
  get_robot_context: "读取机器人状态", explain_motion_block: "检查车辆停止条件", query_incidents: "查询异常记录",
  get_incident_summary: "整理异常报告", select_report_focus: "筛选重点异常", find_places: "查询地图地点",
  find_routes: "查询巡检路线", get_execution: "查询任务进度", propose_plan: "核验任务草案",
};
const toolStates = {running: "运行中", completed: "已完成", failed: "调用失败", unavailable: "状态不可用"};

function ToolResult({result}: {result: AssistantToolResult}) {
  if (result.kind === 'system') return <details className="assistant-card">
    <summary>{result.title} · 展开证据</summary>
    <pre style={{whiteSpace: 'pre-wrap', overflowWrap: 'anywhere'}}>{JSON.stringify(result.data, null, 2)}</pre>
    <Link to="/diagnostics">查看系统诊断</Link>
  </details>;
  if (result.kind === "robot") return <article className="assistant-card">
    <div className="assistant-card-heading"><Bot size={16} aria-hidden="true" /><strong>机器人状态快照</strong>
      <span>{result.available ? "遥测可用" : "遥测不可用"}</span></div>
    {result.available && result.mode && <p>模式 · {result.mode}</p>}
    {result.available && typeof result.emergency_stop === "boolean" && <p>急停 · {result.emergency_stop ? "已启用" : "未启用"}</p>}
    {result.available && result.received_at && <small>采样时间 · {new Date(result.received_at).toLocaleString("zh-CN")}</small>}
  </article>;
  return <article className="assistant-card">
    <div className="assistant-card-heading"><FileText size={16} aria-hidden="true" /><strong>异常记录</strong>
      <span>{result.total} 条</span></div>
    {result.items.length > 0 && <ul>{result.items.map(item => <li key={item.id}>
      <Link to={`/incidents/${encodeURIComponent(item.id)}`}>{item.title}</Link> · {item.status_label}
    </li>)}</ul>}
  </article>;
}

function ToolActivity({tools, interrupted}: {tools: AssistantTool[]; interrupted: boolean}) {
  if (!tools.length) return null;
  const failed = tools.filter(tool => tool.state === "failed" || tool.state === "unavailable").length;
  const running = tools.some(tool => tool.state === "running");
  return <details className="assistant-card assistant-tool-card">
    <summary><Activity size={15} aria-hidden="true" /> <strong>工具执行</strong>
      <span>{running ? interrupted ? "结果未确认" : "调用中" : failed ? `${failed} 项未成功` : `${tools.length} 项已完成`}</span>
    </summary>
    <ul>{tools.map(tool => <li key={tool.id} data-state={tool.state}>
      {toolNames[tool.name] ?? "未识别的工具"}<span>{interrupted && tool.state === "running" ? "结果未确认" : toolStates[tool.state]}</span>
    </li>)}</ul>
  </details>;
}

function CopyReply({text}: {text: string}) {
  const [status, setStatus] = useState("");
  async function copy() {
    try { await navigator.clipboard.writeText(text); setStatus("已复制"); }
    catch { setStatus("复制失败"); }
  }
  return <button type="button" title={status || "复制回复"} aria-label={status || "复制回复"} className="assistant-icon"
    onClick={() => void copy()}>{status === "已复制" ? <Check size={14} /> : <Copy size={14} />}
    {status === "复制失败" && <small role="status">{status}</small>}</button>;
}

type ScrollPosition = {top: number; follow: boolean};

export function AssistantTranscript({sessionId, turns, visible, expanded, loading, generating, emptyContent, executions,
  canSend, canTrial, planPending, planErrors, planActions, retry, regenerate}: {
  sessionId: string | null; turns: ChatTurn[]; visible: boolean; expanded: boolean; loading: boolean; generating: boolean;
  emptyContent: ReactNode; executions: Record<string, AssistantExecution>; canSend: boolean; canTrial: boolean;
  planPending: string | null; planErrors: Record<string, string>; planActions: PlanActions;
  retry: (turn: ChatTurn) => void; regenerate: (turn: ChatTurn) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const content = useRef<HTMLDivElement>(null);
  const positions = useRef(new Map<string | null, ScrollPosition>());
  const [away, setAway] = useState(false);
  useLayoutEffect(() => {
    const node = scroller.current;
    const inner = content.current;
    if (!visible || !node || !inner) return;
    const saved = positions.current.get(sessionId);
    node.scrollTop = saved?.follow === false ? saved.top : node.scrollHeight;
    setAway(saved?.follow === false);
    const observer = new ResizeObserver(() => {
      if (positions.current.get(sessionId)?.follow !== false) node.scrollTop = node.scrollHeight;
    });
    observer.observe(inner);
    observer.observe(node);
    return () => observer.disconnect();
  }, [sessionId, visible, expanded]);
  useLayoutEffect(() => {
    if (visible && scroller.current && positions.current.get(sessionId)?.follow !== false) {
      scroller.current.scrollTop = scroller.current.scrollHeight;
    }
  }, [sessionId, visible, turns, executions, loading]);

  return <div className="assistant-transcript-region">
    <div ref={scroller} role="log" aria-label="助手对话" aria-live="off" tabIndex={0} className="assistant-transcript"
      onScroll={() => {
        const node = scroller.current;
        if (!visible || !node || node.clientHeight === 0) return;
        const follow = followsLatest(node.scrollTop, node.clientHeight, node.scrollHeight);
        positions.current.set(sessionId, {top: node.scrollTop, follow});
        setAway(!follow);
      }}>
      <div ref={content} className="assistant-messages">
        {!turns.length && (loading ? <p className="assistant-muted" role="status">正在加载会话…</p> : emptyContent)}
        {turns.map((turn, index) => {
          const plan = currentPlan(turn, executions);
          const draft = turn.generation;
          const status = draft?.state;
          const interrupted = status === "failed" || status === "cancelled";
          const text = turn.reply?.text ?? draft?.text;
          const tools = turn.reply?.tools ?? draft?.tools ?? [];
          return <div key={turn.client_id} className="assistant-turn">
            <p className="assistant-user-message">{turn.text}</p>
            <div className="assistant-answer">
              <ToolActivity tools={tools} interrupted={interrupted} />
              {text && <div className="assistant-answer-body"><AssistantMarkdown text={text} /></div>}
              {tools.map(tool => tool.result && <ToolResult key={tool.id} result={tool.result} />)}
              {turn.reply?.operations?.map((op, i) => <article className="assistant-card" key={i}>
                <strong>{toolNames[op.name] ?? '操作结果'}</strong><p>{op.state === 'accepted' ? '已受理，等待执行回执' :
                  op.state === 'unconfirmed' ? '结果未确认，请先查询状态' : op.state === 'completed' ? '已完成' : op.state}</p>
                {(op.error || op.message) && <p>{op.error || op.message}</p>}
              </article>)}
              {turn.reply ? <div className="assistant-message-meta">
                <small>已完成</small><CopyReply text={turn.reply.text} />
                {canSend && !generating && !plan && !turn.reply.report_id && !turn.reply.tools?.length && !turn.reply.operations?.length && index === turns.length - 1 &&
                  <button type="button" className="assistant-icon" title="重新生成回复" aria-label="重新生成回复"
                    onClick={() => regenerate(turn)}><RotateCcw size={14} /></button>}
              </div> : <div className={status === "failed" ? "assistant-card assistant-error" : "assistant-message-meta"}
                role={status === "failed" ? "alert" : "status"}>
                {status === "using_tools" ? "正在调用工具…" : status === "generating" ? "正在生成回复…" :
                  status === "cancelled" ? "已停止回复" : status === "failed" ? draft?.error || "回复失败" : "此消息尚无回复"}
                {canSend && !generating && (!status || interrupted) &&
                  <button type="button" className="btn btn-outline" onClick={() => retry(turn)}>重试原消息</button>}
              </div>}
              {turn.reply?.report_id && <Link className="assistant-card assistant-report"
                to={`/assistant/reports/${encodeURIComponent(turn.reply.report_id)}`}>
                <FileText size={16} aria-hidden="true" /><strong>异常分析报告</strong><span>查看详情</span>
              </Link>}
              {plan && <AssistantPlanCard plan={plan} canSend={canSend} canTrial={canTrial} pending={planPending}
                error={planErrors[plan.id]} actions={planActions} />}
            </div>
          </div>;
        })}
      </div>
    </div>
    {away && <button type="button" className="assistant-jump" onClick={() => {
      if (scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight;
      positions.current.set(sessionId, {top: scroller.current?.scrollTop ?? 0, follow: true});
      setAway(false);
    }}><ArrowDown size={14} /> 回到最新</button>}
  </div>;
}
