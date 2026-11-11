import { SystemHealthCard } from "./assistant/SystemHealthCard";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Bot, History, Maximize2, Minimize2, Minus, Plus } from "lucide-react";
import { businessApi, type AssistantExecution } from "../services/businessApi";
import { Link } from "../lib/router";
import { useBusinessSession } from "../hooks/useBusinessSession";
import { useAssistantChat } from "./assistant/useAssistantChat";
import { AssistantComposer, suggestions } from "./assistant/AssistantComposer";
import { AssistantTranscript } from "./assistant/AssistantTranscript";
import { rememberExecution } from "./assistant/chatState";
import type { PlanActions } from "./assistant/AssistantPlanCard";

const noExecutions: Record<string, AssistantExecution> = {};
type Floating = {
  visible: boolean; expanded: boolean; close: () => void; toggleSize: () => void; context: ReactNode;
  pending?: {id: string; sessionId: string} | null;
  executions: Record<string, AssistantExecution>; onReply: (id: string) => void;
};

export function AssistantConversation({ canSend, floating }: {canSend: boolean; floating?: Floating}) {
  const session = useBusinessSession();
  const permissions = new Set(session?.user.role?.permissions.map(p => p.name) ?? []);
  const canTrial = ["assistant.settings", "assistant.use", "robots.manage", "robots.control"].every(p => permissions.has(p));
  const visible = floating?.visible ?? true;
  const chat = useAssistantChat(session?.user.id ?? "", !!floating, visible, floating?.onReply);
  const [history, setHistory] = useState(false);
  const [pending, setPending] = useState<string | null>(null);
  const [planErrors, setPlanErrors] = useState<Record<string, string>>({});
  const [localExecutions, setLocalExecutions] = useState<Record<string, AssistantExecution>>(noExecutions);
  const lock = useRef<string>(null);
  const recentPlan = useRef<string | undefined>(undefined);
  const selected = chat.sessions.find(item => item.id === chat.sessionId);
  const title = selected?.title || chat.turns[0]?.text.slice(0, 64) || (chat.sessionId ? "未命名会话" : "新会话");
  const preferred = floating?.pending?.sessionId;
  const preferredPlan = floating?.pending?.id;
  const refreshChat = chat.refresh;

  useEffect(() => {
    if (preferredPlan && preferredPlan !== recentPlan.current && visible && preferred === chat.sessionId) {
      recentPlan.current = preferredPlan;
      refreshChat();
    }
  }, [preferredPlan, preferred, visible, chat.sessionId, refreshChat]);

  async function planAction(id: string, run: () => Promise<AssistantExecution | undefined>) {
    if (lock.current) return;
    lock.current = id;
    setPending(id);
    setPlanErrors(errors => ({...errors, [id]: ""}));
    try {
      const execution = await run();
      if (execution) setLocalExecutions(current => rememberExecution(current, execution));
    } catch (error) {
      setPlanErrors(errors => ({...errors, [id]: error instanceof Error ? error.message : "操作未确认"}));
    } finally {
      lock.current = null;
      setPending(null);
    }
  }

  const planActions: PlanActions = {
    confirm: (plan, trial) => void planAction(plan.id, async () => {
      if (trial) await businessApi.authorizeAssistantTrial(plan);
      return businessApi.confirmAssistantPlan(plan);
    }),
    act: (execution, action) => void planAction(execution.plan_id, () => businessApi.assistantExecutionAction(execution, action)),
    refresh: plan => void planAction(plan.id, async () => {
      await businessApi.refreshAssistantPlan(plan);
      chat.refresh();
      return undefined;
    }),
  };
  const liveExecutions = floating?.executions ?? noExecutions;
  const executions = useMemo(() => Object.values(liveExecutions).reduce(rememberExecution, localExecutions),
    [liveExecutions, localExecutions]);

  function select(id: string | null) {
    chat.select(id);
    setHistory(false);
  }

  return <div className="assistant-conversation">
    {permissions.has("diagnostics.read") && permissions.has("robots.read") && <SystemHealthCard visible={visible} />}
    {floating && <header className="assistant-header">
      <span className="assistant-header-avatar"><Bot size={20} aria-hidden="true" /></span>
      <div className="assistant-heading"><strong>智巡助手</strong><span title={title}>{title}</span></div>
      <div className="assistant-header-actions">
        {canSend && <button type="button" className="assistant-icon" title="新建会话" aria-label="新建会话"
          disabled={chat.creating} onClick={() => select(null)}><Plus size={18} /></button>}
        <button type="button" className="assistant-icon" title="会话历史" aria-label="会话历史"
          aria-expanded={history} onClick={() => setHistory(value => !value)}><History size={17} /></button>
        <button type="button" className="assistant-icon" title={floating.expanded ? "恢复窗口尺寸" : "扩大窗口"}
          aria-label={floating.expanded ? "恢复窗口尺寸" : "扩大窗口"} onClick={floating.toggleSize}>
          {floating.expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
        <button type="button" className="assistant-icon" title="收起窗口" aria-label="收起窗口" onClick={() => {
          setHistory(false);
          floating.close();
        }}><Minus size={19} /></button>
      </div>
    </header>}
    {(!floating || history) && <div className="assistant-history-select">
      <label>会话 <select value={chat.sessionId ?? ""} disabled={chat.creating} onChange={event => select(event.target.value || null)}>
        <option value="">{canSend ? "新会话" : "选择会话"}</option>
        {chat.sessionId && !selected && <option value={chat.sessionId}>{title}</option>}
        {chat.sessions.map(item => <option key={item.id} value={item.id}>
          {item.title ? `${item.title} · ` : ""}{new Date(item.created_at).toLocaleString("zh-CN")}
        </option>)}
      </select></label>
      {floating && <Link to="/assistant/history" onClick={() => { setHistory(false); floating.close(); }}>打开历史页面</Link>}
    </div>}
    {floating?.context}
    {preferred && preferred !== chat.sessionId && <div className="assistant-pending">
      <button type="button" className="btn btn-outline" disabled={chat.creating} onClick={() => select(preferred)}>查看待确认会话</button>
    </div>}
    <AssistantTranscript sessionId={chat.sessionId} turns={chat.turns} visible={visible} expanded={!!floating?.expanded}
      loading={chat.loading} generating={chat.generating} executions={executions} canSend={canSend}
      canTrial={canTrial} planPending={pending} planErrors={planErrors} planActions={planActions}
      retry={turn => void chat.send(turn.text, turn)} regenerate={turn => void chat.send(turn.text)}
      emptyContent={<div className="assistant-empty">
        <Bot size={28} aria-hidden="true" />
        <strong>{canSend ? "有什么需要我协助？" : "暂无对话记录"}</strong>
        {canSend && <><p>可以查询机器人、分析异常，或起草巡检计划。</p>
          <div className="assistant-suggestions">{suggestions.map(text => <button type="button" key={text} onClick={event => {
            chat.setInput(text);
            event.currentTarget.closest(".assistant-conversation")?.querySelector<HTMLElement>("[data-assistant-input]")?.focus();
          }}>{text}</button>)}</div></>}
      </div>} />
    {chat.error && <div className="assistant-load-error" role="alert"><span>{chat.error}</span>
      <button type="button" className="btn btn-outline" onClick={chat.refresh}>刷新会话</button></div>}
    {canSend && <AssistantComposer input={chat.input} change={chat.setInput} send={() => void chat.send(chat.input)}
      generating={chat.generating} disabled={chat.loading || chat.creating} stop={chat.stop} visible={visible} />}
  </div>;
}
