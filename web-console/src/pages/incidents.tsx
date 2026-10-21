import { useEffect, useState } from "react";
import { Link } from "../lib/router";
import { IncidentEvidence, SafetyRecognitionStatus } from "../components/robot/SafetyRecognitionStatus";
import { useData } from "../hooks/useData";
import { businessApi } from "../services/businessApi";
import { formatTime } from "../services/adapters";
import { Badge, EmptyState, Panel } from "../components/ui";
import { DataTable, ObjectHeader, type Column } from "../components/shared";
import type { BusinessIncident } from "../services/businessApi";
const labels: Record<string, string> = { open: "待确认", acknowledged: "已确认", handling: "处理中", resolved: "已解决", dismissed: "已忽略" };
export function IncidentsPage() {
  const { data, loading, error, refetch } = useData(() => businessApi.listIncidents());
  useEffect(() => { const timer = setInterval(refetch, 5000); return () => clearInterval(timer); }, [refetch]);
  const columns: Column<BusinessIncident>[] = [
    { key: "title", header: "异常", render: i => <div className="cell-strong"><strong>{i.title}</strong><em>{i.type}</em></div> },
    { key: "severity", header: "级别", render: i => i.severity },
    { key: "location", header: "位置", render: i => i.location || "未记录" },
    { key: "robot", header: "上报机器人", render: i => i.robot_id || "未关联" },
    { key: "time", header: "发生时间", render: i => formatTime(i.occurred_at || i.created_at) },
    { key: "status", header: "状态", render: i => <Badge tone="neutral">{labels[i.status] || i.status}</Badge> },
  ];
  return <div className="page"><ObjectHeader kicker="Incidents" title="异常中心" subtitle="查看巡检异常、现场证据与处理记录"/><SafetyRecognitionStatus/><Panel className="list-panel" bodyClassName="panel-flush">{error ? <EmptyState title="异常数据不可用" hint={error}/> : <DataTable columns={columns} rows={data || []} rowKey={i => i.id} loading={loading} emptyTitle="暂无异常记录" onRowClick={i => { window.location.hash = `/incidents/${i.id}`; }}/>}</Panel></div>;
}
export function IncidentDetailPage({ id }: { id: string }) {
  const { data: item, loading, error, refetch } = useData(() => businessApi.getIncident(id), [id]);
  const [pending, setPending] = useState(false), [actionError, setActionError] = useState(""), [note, setNote] = useState("");
  async function act(action: string) { if (["resolve", "dismiss"].includes(action) && !note.trim()) { setActionError("请填写处理或忽略原因"); return; } setPending(true); setActionError(""); try { await businessApi.incidentAction(id, action, note.trim()); refetch(); } catch (e) { setActionError((e as Error).message); } finally { setPending(false); } }
  return <div className="page"><Link to="/incidents" className="back-link">返回异常中心</Link>{loading ? <EmptyState title="加载中…"/> : error ? <EmptyState title="异常数据不可用" hint={error}/> : !item ? <EmptyState title="未找到该异常"/> : <><ObjectHeader kicker="Incident" title={item.title} subtitle={`${item.type} · ${item.location || "未记录位置"}`} badges={[{ label: labels[item.status] || item.status, tone: "neutral" }]} actions={<>{item.status === "open" && <button className="btn btn-primary" disabled={pending} onClick={() => void act("confirm")}>确认</button>}{["open", "acknowledged"].includes(item.status) && <button className="btn btn-outline" disabled={pending} onClick={() => void act("handle")}>开始处理</button>}{["open", "acknowledged", "handling"].includes(item.status) && <><button className="btn btn-outline" disabled={pending} onClick={() => void act("resolve")}>标记解决</button><button className="btn btn-outline" disabled={pending} onClick={() => void act("dismiss")}>忽略</button></>}</>}/>{actionError && <p role="alert">{actionError}</p>}<label>处理说明<textarea aria-label="异常处理说明" maxLength={2000} value={note} onChange={e => setNote(e.target.value)}/></label><Panel title="异常记录"><p>{item.description || "未记录说明"}</p><div className="profile-list"><div><em>发生时间</em><strong>{formatTime(item.occurred_at || item.created_at)}</strong></div><div><em>处理时间</em><strong>{formatTime(item.handled_at)}</strong></div><div><em>解决时间</em><strong>{formatTime(item.resolved_at)}</strong></div><div><em>处理记录</em><strong>{item.handle_result || item.resolution_note || "未记录"}</strong></div></div></Panel><IncidentEvidence item={item}/></>}</div>;
}
