import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent } from "react";
import type { BusinessUser } from "../services/businessApi";
import { Link, usePath } from "../lib/router";
import { AssistantConversation } from "./AssistantConversation";
import { vehiclePhases } from "./assistant/AssistantPlanCard";
import { useAssistantWorkspace } from "./assistant/useAssistantWorkspace";
import { placeAssistant } from "./assistant/petLayout";
import "./assistantPet.css";

type Point = { x: number; y: number };
type WindowState = "collapsed" | "expanded" | "large";

const pageNames = new Map([
  ["robots", "机器人"], ["tasks", "任务"], ["incidents", "异常"],
  ["maps", "地图"], ["routes", "路线"], ["slam", "实时建图"],
]);

function workspaceTop() {
  return (Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--header-h")) || 56) + 8;
}

function viewportBounds() {
  const viewport = window.visualViewport;
  return {
    left: viewport?.offsetLeft ?? 0, top: viewport?.offsetTop ?? 0,
    width: viewport?.width ?? window.innerWidth, height: viewport?.height ?? window.innerHeight,
  };
}

export function AssistantPet({ user }: { user: BusinessUser }) {
  const storageKey = `insightrover.pet-position.${user.id}`;
  const [savedPosition, setSavedPosition] = useState(() => {
    try {
      const point = JSON.parse(localStorage.getItem(storageKey) ?? "null");
      if (Number.isFinite(point?.x) && Number.isFinite(point?.y)) return point as Point;
    } catch { /* Storage is optional. */ }
    return { x: window.innerWidth - 88, y: window.innerHeight - 88 };
  });
  const [viewport, setViewport] = useState(viewportBounds);
  const [windowState, setWindowState] = useState<WindowState>("collapsed");
  const [initialized, setInitialized] = useState(false);
  const open = windowState !== "collapsed";
  const expanded = windowState === "large";
  const {launcher: position, panel: panelBounds} = placeAssistant(savedPosition, viewport, workspaceTop(), expanded);
  const openRef = useRef(false);
  const [unread, setUnread] = useState(false);
  const path = usePath();
  const drag = useRef<{ id: number; start: Point; origin: Point; moved: boolean } | null>(null);
  const suppressClick = useRef(false);
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  const restoreFocus = useRef(false);
  const markUnread = useCallback(() => { if (!openRef.current) setUnread(true); }, []);
  const {canRead, canReadMissions, canReadAssistant, canUseAssistant, robot, connection, notice, pendingPlan, executions} =
    useAssistantWorkspace(user, markUnread);

  useEffect(() => {
    const visual = window.visualViewport;
    function resize() { setViewport(viewportBounds()); }
    window.addEventListener("resize", resize);
    visual?.addEventListener("resize", resize);
    visual?.addEventListener("scroll", resize);
    return () => {
      window.removeEventListener("resize", resize);
      visual?.removeEventListener("resize", resize);
      visual?.removeEventListener("scroll", resize);
    };
  }, []);

  useEffect(() => {
    try { localStorage.setItem(storageKey, JSON.stringify(savedPosition)); } catch { /* Storage is optional. */ }
  }, [storageKey, savedPosition]);

  function start(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0 || !event.isPrimary) return;
    suppressClick.current = false;
    drag.current = { id: event.pointerId, start: { x: event.clientX, y: event.clientY }, origin: position, moved: false };
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<HTMLButtonElement>) {
    const active = drag.current;
    if (!active || active.id !== event.pointerId) return;
    const dx = event.clientX - active.start.x, dy = event.clientY - active.start.y;
    if (!active.moved && Math.hypot(dx, dy) < 5) return;
    active.moved = true;
    suppressClick.current = true;
    const next = {x: active.origin.x + dx, y: active.origin.y + dy};
    setSavedPosition(placeAssistant(next, viewport, workspaceTop(), expanded).launcher);
  }
  function end() { drag.current = null; }
  function close() {
    restoreFocus.current = true;
    openRef.current = false;
    setWindowState("collapsed");
  }

  useLayoutEffect(() => {
    if (open) panel.current?.focus({preventScroll: true});
    else if (restoreFocus.current) {
      restoreFocus.current = false;
      launcher.current?.focus({preventScroll: true});
    }
  }, [open]);

  if (!canRead && !canReadAssistant) return null;
  const activePlan = pendingPlan && executions[pendingPlan.id];
  const found = notice?.found || (activePlan?.state === "waiting_human" && activePlan.vehicle_state === "found");
  const mood = found ? "found" : notice || pendingPlan ? "waiting" : "idle";
  const [page, detail] = path.split("/").slice(1);
  const pageName = pageNames.get(page) ?? "工作台";
  const task = canRead && canReadMissions ? robot?.telemetry?.navigation_task : undefined;
  const taskPhase = task?.state && vehiclePhases[task.state];
  const context = <div className="assistant-context">
    {canRead && <span className="assistant-connection" data-online={connection === "在线"}>
      {robot?.name || "关联机器人"} · {connection}
      {robot?.telemetry?.emergency_stop === true && " · 急停"}
    </span>}
    <span>{page === "incidents" && detail ? "异常详情" : pageName}</span>
    {notice ? <div className="assistant-notice" role="status">{notice.text}
      {notice.taskId && <Link to={`/tasks/${encodeURIComponent(notice.taskId)}`}>打开任务确认</Link>}
    </div> : task?.task_id && task.run_id && taskPhase && <Link className="assistant-task-context"
      to={`/tasks/${encodeURIComponent(task.task_id)}`}>车端任务 · {taskPhase}</Link>}
  </div>;
  return <div className="assistant-pet">
    {initialized && <section ref={panel} id="assistant-popover" className="assistant-popover" role="dialog"
      aria-label="智巡助手" hidden={!open} tabIndex={-1} style={panelBounds}
      onKeyDown={event => {
        if (event.key === "Escape" && !event.nativeEvent.isComposing && event.keyCode !== 229) {
          event.stopPropagation();
          event.preventDefault();
          close();
        }
      }}>
      {canReadAssistant ? <AssistantConversation canSend={canUseAssistant} floating={{
        visible: open, expanded, close, toggleSize: () => setWindowState(expanded ? "expanded" : "large"),
        context, pending: pendingPlan, executions,
        onReply: markUnread,
      }} /> : <><header className="assistant-header"><strong>智巡助手</strong>
        <button type="button" className="assistant-icon" aria-label="收起窗口" onClick={close}>−</button></header>{context}</>}
    </section>}
    <button ref={launcher} type="button" className="assistant-launcher" data-assistant-launcher data-mood={mood}
      aria-label={open ? "收起智巡助手，可拖动图标" :
        unread || pendingPlan || notice ? "展开智巡助手，有新消息或待处理任务" : "展开智巡助手，可拖动图标"}
      aria-expanded={open} aria-controls={initialized ? "assistant-popover" : undefined}
      style={{ left: position.x, top: position.y }} onPointerDown={start} onPointerMove={move}
      onPointerUp={end} onPointerCancel={end} onLostPointerCapture={end}
      onClick={event => {
        if (event.detail !== 0 && suppressClick.current) return;
        if (open) {
          close();
          return;
        }
        openRef.current = true;
        setInitialized(true);
        setWindowState("expanded");
        setUnread(false);
      }}>
      <svg viewBox="0 0 64 64" aria-hidden="true">
        <g className="assistant-avatar-body">
        <rect x="8" y="42" width="13" height="14" rx="5" fill="#172b48"/>
        <rect x="43" y="42" width="13" height="14" rx="5" fill="#172b48"/>
        <rect x="9" y="20" width="46" height="31" rx="13" fill="#2870db"/>
        <rect x="14" y="24" width="36" height="20" rx="8" fill="#122443"/>
        <g className="assistant-avatar-eyes" fill="#baf3ff">
          <rect x="23" y="30" width="5" height="9" rx="2.5"/>
          <rect x="36" y="30" width="5" height="9" rx="2.5"/>
        </g>
        <rect x="23" y="12" width="18" height="9" rx="3" fill="#263957"/>
        <path className="assistant-avatar-radar" d="M24 9Q32 2 40 9M28 9Q32 6 36 9" fill="none" stroke="#2870db" strokeWidth="2" strokeLinecap="round"/>
        </g>
        <path className="assistant-avatar-star" d="M51 7L53 12 58 14 53 16 51 21 49 16 44 14 49 12Z" fill="#d68212"/>
      </svg>
      {(notice || pendingPlan || unread) && <span className="assistant-pet-badge" aria-hidden="true" />}
    </button>
  </div>;
}
