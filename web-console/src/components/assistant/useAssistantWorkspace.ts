import { useEffect, useRef, useState } from "react";
import { businessApi, readAssistantEvents, type AssistantExecution, type BusinessUser, type RobotContext } from "../../services/businessApi";
import { rememberExecution } from "./chatState";

type Notice = { key: string; text: string; taskId?: string; found?: true };
type PendingPlan = { id: string; sessionId: string; expiresAt?: number };

function restorePending(key: string): PendingPlan | null {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "null");
    if (typeof value?.id !== "string" || typeof value?.sessionId !== "string" ||
        value.id.length > 128 || value.sessionId.length > 128) return null;
    if (value.expiresAt !== undefined && (!Number.isFinite(value.expiresAt) || value.expiresAt <= Date.now())) return null;
    return { id: value.id, sessionId: value.sessionId, ...(value.expiresAt ? { expiresAt: value.expiresAt } : {}) };
  } catch { return null; }
}

function restoreNotices(key: string) {
  try {
    const value = JSON.parse(localStorage.getItem(key) ?? "[]");
    if (Array.isArray(value)) return new Set<string>(value.filter(item => typeof item === "string").slice(-64));
  } catch { /* Storage is optional. */ }
  return new Set<string>();
}

export function useAssistantWorkspace(user: BusinessUser, markUnread: () => void) {
  const pendingKey = `insightrover.pet-pending.${user.id}`;
  const noticesKey = `insightrover.pet-notices.${user.id}`;
  const [robot, setRobot] = useState<RobotContext | null>(null);
  const [connection, setConnection] = useState("连接中");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [pendingPlan, setPendingPlan] = useState(() => restorePending(pendingKey));
  const restoredPending = useRef(pendingPlan);
  const [executions, setExecutions] = useState<Record<string, AssistantExecution>>({});
  const seen = useRef(restoreNotices(noticesKey));
  const permissions = user.role?.permissions.map(p => p.name) ?? [];
  const canRead = permissions.includes("robots.read");
  const canReadMissions = permissions.includes("missions.read");
  const canReadAssistant = permissions.includes("assistant.read");
  const canUseAssistant = permissions.includes("assistant.use");

  useEffect(() => {
    try {
      if (pendingPlan) localStorage.setItem(pendingKey, JSON.stringify(pendingPlan));
      else localStorage.removeItem(pendingKey);
    } catch { /* Storage is optional. */ }
  }, [pendingKey, pendingPlan]);

  useEffect(() => {
    const saved = restoredPending.current;
    if (!saved) return;
    if (!canReadAssistant || !canUseAssistant) {
      setPendingPlan(null);
      return;
    }
    const controller = new AbortController();
    businessApi.assistantPlan(saved.id, controller.signal).then(plan => {
      const waiting = plan.execution?.state === "waiting_human" ||
        (plan.state === "draft" && plan.expires_at * 1000 > Date.now());
      if (!controller.signal.aborted && !waiting) setPendingPlan(current => current === saved ? null : current);
    }).catch(error => {
      if (!controller.signal.aborted && (error.status === 403 || error.status === 404)) {
        setPendingPlan(current => current === saved ? null : current);
      }
    });
    return () => controller.abort();
  }, [canReadAssistant, canUseAssistant]);

  useEffect(() => {
    if (!canReadAssistant) return;
    const controller = new AbortController();
    const cursorKey = `insightrover.assistant-cursor.${user.id}`;
    let cursor = 0;
    try {
      const value = Number(localStorage.getItem(cursorKey));
      if (Number.isSafeInteger(value) && value >= 0) cursor = value;
    } catch { /* Storage is optional. */ }
    let timer: ReturnType<typeof setTimeout>;
    async function checkPlan(planId: string) {
      try {
        return await businessApi.assistantPlan(planId, AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]));
      } catch (error) {
        if (error instanceof Error && "status" in error && (error.status === 403 || error.status === 404)) return;
        throw error;
      }
    }
    async function connect() {
      try {
        await readAssistantEvents(cursor, async (id, event) => {
          const payload = event.payload;
          if (event.kind.startsWith("execution.") && typeof payload.plan_id === "string" && typeof payload.version === "number") {
            setExecutions(current => rememberExecution(current, payload as unknown as AssistantExecution));
            markUnread();
            if (canUseAssistant && event.kind === "execution.waiting_human" && typeof payload.session_id === "string") {
              const planId = payload.plan_id, sessionId = payload.session_id;
              const plan = await checkPlan(planId);
              if (!controller.signal.aborted && plan?.execution?.state === "waiting_human" &&
                  plan.execution.version === payload.version) {
                setPendingPlan({id: planId, sessionId});
              }
            } else {
              setPendingPlan(current => current?.id === payload.plan_id ? null : current);
            }
          }
          if (canUseAssistant && event.kind === "plan.confirmation_required" &&
              typeof payload.id === "string" && typeof payload.session_id === "string" &&
              typeof payload.expires_at === "number" && payload.expires_at * 1000 > Date.now()) {
            const plan = await checkPlan(payload.id);
            if (!controller.signal.aborted && plan?.state === "draft" && plan.expires_at * 1000 > Date.now()) {
              setPendingPlan({id: payload.id, sessionId: payload.session_id, expiresAt: plan.expires_at * 1000});
            }
          }
          if (!controller.signal.aborted) {
            cursor = id;
            try { localStorage.setItem(cursorKey, String(cursor)); } catch { /* Storage is optional. */ }
          }
        }, controller.signal);
      } catch { /* Reconnect with the last received event ID. */ }
      if (!controller.signal.aborted) timer = setTimeout(connect, 1200);
    }
    void connect();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [canReadAssistant, canUseAssistant, user.id, markUnread]);

  useEffect(() => {
    if (!pendingPlan?.expiresAt) return;
    const timer = setTimeout(() => setPendingPlan(current => current === pendingPlan ? null : current),
      Math.max(0, pendingPlan.expiresAt - Date.now()));
    return () => clearTimeout(timer);
  }, [pendingPlan]);

  useEffect(() => {
    if (!canRead) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      try {
        const result = await businessApi.getBoundRobotContext(AbortSignal.any([controller.signal, AbortSignal.timeout(5000)]));
        if (controller.signal.aborted) return;
        const data = result.available ? result.telemetry : null;
        setRobot({...result, telemetry: data});
        setConnection(data ? "在线" : result.reason === "telemetry_pending" ? "连接中" :
          result.reason === "vehicle_unavailable" ? "离线" : "状态未确认");
        const task = data?.navigation_task;
        const search = data?.search;
        let next: Notice | null = null;
        if (canReadMissions && task?.kind === "delivery" && task.run_id && task.task_id &&
            (task.state === "waiting_load" || task.state === "waiting_handover")) {
          next = { key: `${task.run_id}:${task.state}`, taskId: task.task_id,
            text: task.state === "waiting_load" ? "运输任务等待确认装件" : "运输任务等待确认交接" };
        } else if (search?.state === "found" && search.run_id) {
          next = { key: `${search.run_id}:found`, found: true, text: "目标已找到，车端已确认停车，等待人工处理" };
        }
        setNotice(next);
        if (next && !seen.current.has(next.key)) {
          if (seen.current.size >= 64) seen.current.delete(seen.current.values().next().value!);
          seen.current.add(next.key);
          try { localStorage.setItem(noticesKey, JSON.stringify([...seen.current])); } catch { /* Storage is optional. */ }
          markUnread();
        }
      } catch {
        if (!controller.signal.aborted) {
          setConnection("状态未确认");
          setRobot(current => current && {...current, available: false, telemetry: null});
          setNotice(null);
        }
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 2500);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [canRead, canReadMissions, noticesKey, markUnread]);

  return {canRead, canReadMissions, canReadAssistant, canUseAssistant, robot, connection, notice, pendingPlan, executions};
}
