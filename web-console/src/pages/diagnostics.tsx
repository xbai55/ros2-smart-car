import { useEffect, useRef, useState } from "react";
import { Link } from "../lib/router";
import { useBusinessSession } from "../hooks/useBusinessSession";
import { diagnosticRequest, diagnosticExport, diagnosticClientEvent } from "../services/businessApi";
import { mergeDiagnostics, stopReasons, type DiagnosticEvent, type DiagnosticPage } from "../diagnosticsState";
import { EmptyState } from "../components/ui";
import { ObjectHeader } from "../components/shared";
import "./diagnostics.css";

const labels: Record<string, string> = { host: "主机", jetson: "车端", desktop: "桌面程序", frontend: "控制台" };
const local = (value: string) => new Date(value).toLocaleString();
const reason = (event: DiagnosticEvent) => stopReasons[event.reason_code] ?? event.reason_code;
const filters = { level: "", module: "", robot_id: "", task_id: "", q: "", start: "", end: "" };

function ExecutionDiagnostics({ id }: { id: string }) {
  const [data, setData] = useState<DiagnosticPage>();
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    diagnosticRequest<DiagnosticPage>(`/executions/${encodeURIComponent(id)}`, controller.signal)
      .then(setData).catch(error => { if (!controller.signal.aborted) setError(error.message); });
    return () => controller.abort();
  }, [id]);
  return <div className="page diagnostics"><ObjectHeader kicker="InsightRover" title="执行诊断" subtitle={id} />
    {error && <p role="alert">{error}</p>}
    {!data && !error && <p role="status">正在加载执行记录</p>}
    {data && <>
      <ul>{[...data.items].reverse().map(event => <li key={event.event_id}>{local(event.occurred_at)} · {event.message} · {reason(event)}</li>)}</ul>
      {data.business_events?.length ? <ul>{data.business_events.map(item => <li key={item.id}>{local(item.occurred_at)} · {item.kind}</li>)}</ul> : null}
      {!data.items.length && !data.business_events?.length && <EmptyState title="当前保留期内暂无执行记录" />}
    </>}
  </div>;
}

export function DiagnosticsPage({ executionId, initialTask = "" }: { executionId?: string; initialTask?: string }) {
  const session = useBusinessSession();
  if (executionId) return <ExecutionDiagnostics key={executionId} id={executionId} />;
  const perms = session?.user.role?.permissions.map(item => item.name) ?? [];
  if (!perms.includes("diagnostics.read")) return <div className="page"><EmptyState title="无权查看系统运行日志" /></div>;
  return <DiagnosticCenter key={`${session?.user.id}:${initialTask}`} initialTask={initialTask}
    canExport={perms.includes("diagnostics.export")} />;
}

function DiagnosticCenter({ initialTask, canExport }: { initialTask: string; canExport: boolean }) {
  const [mode, setMode] = useState<"stops" | "events">(initialTask ? "events" : "stops");
  const [draft, setDraft] = useState({ ...filters, task_id: initialTask });
  const [active, setActive] = useState(draft);
  const [live, setLive] = useState(true);
  const [version, refresh] = useState(0);
  const [items, setItems] = useState<DiagnosticEvent[]>([]);
  const [next, setNext] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [gap, setGap] = useState(false);
  const [selected, select] = useState<DiagnosticEvent>();
  const [related, setRelated] = useState<DiagnosticEvent[]>([]);
  const [detailError, setDetailError] = useState("");
  const [exporting, setExporting] = useState(false);
  const [exportNote, setExportNote] = useState("");
  const [health, setHealth] = useState<{ status: string; vehicle?: { status: string; gaps?: string[] } }>();
  const liveRef = useRef(live);
  liveRef.current = live;
  const after = useRef<string | undefined>(undefined);
  const current = useRef(0);
  const olderRequest = useRef<AbortController | undefined>(undefined);
  const params = new URLSearchParams();
  Object.entries(active).forEach(([key, value]) => {
    if (value) params.set(key, key === "start" || key === "end" ? new Date(value).toISOString() : value);
  });
  const base = `/${mode}?${params}`;
  const rolling = !active.start && !active.end;
  const periodic = live && rolling;

  useEffect(() => {
    const controller = new AbortController();
    const epoch = ++current.current;
    let timer: number | undefined;
    let failed = false;
    let delay = 2000;
    let nextHealth = 0;
    after.current = undefined;
    setLoading(true);
    setItems([]);
    setNext(undefined);
    setGap(false);
    setError("");
    select(undefined);
    const cycle = async () => {
      if (!liveRef.current && after.current) {
        if (rolling) timer = window.setTimeout(cycle, 2000);
        return;
      }
      try {
        if (Date.now() >= nextHealth) {
          nextHealth = Date.now() + 10000;
          void diagnosticRequest<typeof health>('/health', controller.signal).then(setHealth).catch(() => {});
        }
        const marker = after.current;
        const data = await diagnosticRequest<DiagnosticPage>(
          marker ? `${base}&after=${encodeURIComponent(marker)}` : base, controller.signal);
        if (controller.signal.aborted || epoch !== current.current) return;
        if (data.reset) {
          after.current = undefined;
          setGap(true);
          setItems([]);
          setNext(undefined);
        } else {
          setItems(previous => mergeDiagnostics(previous, data.items));
          after.current = data.after;
          if (!marker) setNext(data.next_cursor);
        }
        if (failed) void diagnosticClientEvent("diagnostic_reconnected").catch(() => {});
        failed = false;
        delay = data.reset ? 0 : 2000;
        setError("");
      } catch (error) {
        if (controller.signal.aborted) return;
        if (!failed) void diagnosticClientEvent("diagnostic_disconnected").catch(() => {});
        failed = true;
        delay = Math.min(delay * 2, 30000);
        setError(error instanceof Error ? error.message : "诊断查询失败");
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false);
          if (rolling) timer = window.setTimeout(cycle, delay);
        }
      }
    };
    void cycle();
    return () => {
      controller.abort();
      olderRequest.current?.abort();
      window.clearTimeout(timer);
    };
  }, [base, rolling, version]);

  useEffect(() => {
    const controller = new AbortController();
    setRelated([]);
    setDetailError("");
    if (selected?.episode_id || selected?.trace_id) {
      const beginning = new Date(Math.max(Date.parse(selected.occurred_at) - 3600000, Date.now() - 14 * 86400000 + 60000)).toISOString();
      const endpoint = selected.episode_id ? `/events?episode_id=${encodeURIComponent(selected.episode_id)}&start=${encodeURIComponent(beginning)}`
        : `/traces/${encodeURIComponent(selected.trace_id!)}`;
      diagnosticRequest<DiagnosticPage>(endpoint, controller.signal)
        .then(data => setRelated([...data.items].reverse()))
        .catch(() => { if (!controller.signal.aborted) setDetailError("无法加载关联时间线"); });
    }
    return () => controller.abort();
  }, [selected]);

  async function older() {
    if (!next || olderRequest.current) return;
    setLive(false);
    const controller = new AbortController();
    olderRequest.current = controller;
    try {
      const data = await diagnosticRequest<DiagnosticPage>(`${base}&cursor=${encodeURIComponent(next)}`, controller.signal);
      if (controller.signal.aborted) return;
      if (data.reset) { refresh(value => value + 1); return; }
      setItems(previous => previous.length >= 500 ? data.items : mergeDiagnostics(previous, data.items));
      setNext(data.next_cursor);
    } catch {
      if (!controller.signal.aborted) setError("加载历史日志失败");
    } finally { olderRequest.current = undefined; }
  }

  async function download(format: "zip" | "ndjson") {
    const end = active.end ? new Date(active.end) : new Date();
    const start = active.start ? new Date(active.start) : new Date(+end - 86400000);
    setExporting(true);
    setExportNote("");
    try {
      const response = await diagnosticExport({ start: start.toISOString(), end: end.toISOString(), format, robot_id: active.robot_id || undefined });
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url;
      link.download = `insightrover-diagnostics.${format}`;
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setExportNote(response.headers.get("X-Diagnostics-Truncated") === "true" ? "已下载，结果达到导出上限。" : "已生成下载文件。");
    } catch (error) {
      setExportNote(error instanceof Error ? error.message : "导出失败");
    } finally { setExporting(false); }
  }

  const events = mode === "stops" ? items.filter(event =>
    ["motion.zero", "motion.blocked", "stop.requested"].includes(event.event_type)) : items;
  return <div className="page diagnostics">
    <ObjectHeader kicker="InsightRover" title="日志与诊断" subtitle="查看停车证据、运行事件和关联链路" />
    <div className="diagnostics-actions">
      <button type="button" aria-pressed={mode === "stops"} onClick={() => setMode("stops")}>故障诊断</button>
      <button type="button" aria-pressed={mode === "events"} onClick={() => setMode("events")}>系统日志</button>
      <button type="button" onClick={() => refresh(value => value + 1)}>刷新</button>
      <button type="button" disabled={!!(active.start || active.end)} onClick={() => setLive(value => !value)}>{live ? "暂停实时更新" : "恢复实时更新"}</button>
      {canExport && <><button type="button" disabled={exporting} onClick={() => void download("zip")}>导出诊断包</button>
        <button type="button" disabled={exporting} onClick={() => void download("ndjson")}>导出日志</button></>}
    </div>
    <form className="diagnostics-filters" onSubmit={event => { event.preventDefault(); setActive(draft); }}>
      <label>级别<select value={draft.level} onChange={e => setDraft({ ...draft, level: e.target.value })}>
        <option value="">全部</option>{["DEBUG", "INFO", "WARN", "ERROR", "CRITICAL"].map(value => <option key={value}>{value}</option>)}
      </select></label>
      {([["module", "模块"], ["robot_id", "机器人 ID"], ["task_id", "任务 ID"], ["q", "关键词"], ["start", "开始时间"], ["end", "结束时间"]] as const)
        .map(([key, label]) => <label key={key}>{label}<input type={key === "start" || key === "end" ? "datetime-local" : "text"}
          value={draft[key]} maxLength={96} onChange={e => setDraft({ ...draft, [key]: e.target.value })} /></label>)}
      <button type="submit">应用筛选</button>
    </form>
    {health?.vehicle && health.vehicle.status !== "ready" && <p role="status">车端日志覆盖有限（{health.vehicle.status}）</p>}
    {gap && <p role="status">保留窗口已变化，列表已重新加载。</p>}
    {exportNote && <p role="status">{exportNote}</p>}
    {error && <p role="alert">{error}。{periodic ? "正在等待重连。" : ""}</p>}
    {loading && <p role="status">正在加载诊断记录</p>}
    {!loading && !error && !events.length && <EmptyState title="当前范围内暂无记录" hint="可调整筛选或时间范围" />}
    {!!events.length && <div className="diagnostics-scroll"><table><thead><tr>
      {["时间", "级别", "来源", "模块", "事件"].map(title => <th key={title} scope="col">{title}</th>)}
    </tr></thead><tbody>{events.map(event => <tr key={event.event_id}>
      <td>{local(event.occurred_at)}</td><td><span className={`diagnostic-level ${event.level}`}>{event.level}</span></td>
      <td>{labels[event.source] ?? event.source}</td><td>{event.module}</td>
      <td><button type="button" onClick={() => select(event)}>{event.message} · {reason(event)}</button></td>
    </tr>)}</tbody></table></div>}
    {next && <button type="button" onClick={() => void older()}>加载更早的记录</button>}
    {selected && <section className="diagnostics-detail" aria-label="日志详情">
      <button type="button" onClick={() => select(undefined)}>关闭详情</button>
      <h2>{selected.message}</h2><p>{reason(selected)}</p>
      {typeof selected.context.winner_module === 'string' && <p>最终生效模块 {selected.context.winner_module}</p>}
      {typeof selected.context.lease_blocked === 'boolean' && <p>控制权 {selected.context.lease_blocked ? '已阻断' : '有活动租约'}</p>}
      {selected.episode_id && ![...items, ...related].some(event => event.episode_id === selected.episode_id &&
        (event.event_type === 'motion.stationary' || event.context.stationary_confirmed === true)) && <p>暂无里程计静止确认</p>}
      {selected.episode_id && !related.length && <ul>{items.filter(event => event.episode_id === selected.episode_id).reverse()
        .map(event => <li key={event.event_id}>{local(event.occurred_at)} · {event.message} · {reason(event)}</li>)}</ul>}
      {selected.robot_id && <Link to={`/robots/${encodeURIComponent(selected.robot_id)}`}>机器人详情</Link>}
      {selected.task_id && <Link to={`/tasks/${encodeURIComponent(selected.task_id)}`}>任务详情</Link>}
      {selected.trace_id && <p>Trace ID <code>{selected.trace_id}</code></p>}
      <pre>{JSON.stringify(selected.context, null, 2)}</pre>
      {selected.exception != null && <pre>{JSON.stringify(selected.exception, null, 2)}</pre>}
      {detailError && <p role="alert">{detailError}</p>}
      {!!related.length && <ol>{related.map(event => <li key={event.event_id}>{local(event.occurred_at)} · {event.message} · {reason(event)}</li>)}</ol>}
    </section>}
  </div>;
}
