import { AlertTriangle, ArrowLeft, Check, CheckCircle2, Eye, X } from "lucide-react";
import { useState } from "react";
import { Link, navigate } from "../lib/router";
import { useData } from "../hooks/useData";
import { adapters } from "../services/adapters";
import { Badge, Button, EmptyState, Panel, StatusDot } from "../components/ui";
import { DataTable, ObjectHeader, ObjectItem, SplitView, Timeline, type Column } from "../components/shared";
import type { Incident, IncidentLevel, IncidentStatus } from "../types/domain";

const levelTone = (level: IncidentLevel) => (level === "critical" ? "danger" : level === "warning" ? "warning" : "info");
const levelLabel = (level: IncidentLevel) => (level === "critical" ? "严重" : level === "warning" ? "警告" : "提示");
const statusLabel: Record<IncidentStatus, string> = { open: "待确认", confirmed: "已确认", resolving: "处理中", resolved: "已解决", dismissed: "已忽略" };

export function IncidentsPage() {
  const { data, loading } = useData(() => adapters.listIncidents());
  const [level, setLevel] = useState<IncidentLevel | "all">("all");
  const [status, setStatus] = useState<IncidentStatus | "all">("all");

  const incidents = (data ?? []).filter((i) => (level === "all" || i.level === level) && (status === "all" || i.status === status));

  const columns: Column<Incident>[] = [
    { key: "title", header: "异常", render: (i) => <div className="cell-strong"><strong>{i.title}</strong><em>{i.type}</em></div> },
    { key: "level", header: "级别", render: (i) => <Badge tone={levelTone(i.level)}>{levelLabel(i.level)}</Badge> },
    { key: "location", header: "位置", render: (i) => i.location },
    { key: "confidence", header: "置信度", render: (i) => <span className="cell-count">{i.confidence}%</span> },
    { key: "robot", header: "机器人", render: (i) => i.robotName },
    { key: "time", header: "发现时间", render: (i) => i.detectedAt },
    { key: "status", header: "状态", render: (i) => <Badge tone={i.status === "open" ? "danger" : i.status === "resolved" ? "success" : i.status === "dismissed" ? "neutral" : "warning"}>{statusLabel[i.status]}</Badge> },
  ];

  return (
    <div className="page">
      <ObjectHeader kicker="Incidents" title="异常中心" subtitle="AI 检测事件与人工确认、处置、关闭的完整闭环" badges={[{ label: `${(data ?? []).filter((i) => i.status === "open").length} 待处理`, tone: "danger" }]} />
      <Panel className="list-panel" bodyClassName="panel-flush">
        <div className="list-toolbar">
          <div className="filter-tabs">
            {(["all", "critical", "warning", "info"] as const).map((l) => (
              <button key={l} type="button" className={level === l ? "on" : ""} onClick={() => setLevel(l)}>{l === "all" ? "全部级别" : levelLabel(l)}</button>
            ))}
          </div>
          <div className="filter-tabs">
            {(["all", "open", "confirmed", "resolving", "resolved", "dismissed"] as const).map((s) => (
              <button key={s} type="button" className={status === s ? "on" : ""} onClick={() => setStatus(s)}>{s === "all" ? "全部状态" : statusLabel[s]}</button>
            ))}
          </div>
        </div>
        <DataTable columns={columns} rows={incidents} rowKey={(i) => i.id} loading={loading} emptyTitle="暂无异常" onRowClick={(i) => { window.location.hash = `/incidents/${i.id}`; }} />
      </Panel>
    </div>
  );
}

export function IncidentDetailPage({ id }: { id: string }) {
  const { data: incident } = useData(() => adapters.getIncident(id), [id]);
  const incidentsQuery = useData(() => adapters.listIncidents());
  const [status, setStatus] = useState<IncidentStatus | null>(null);
  if (!incident) return <div className="page"><EmptyState title="未找到该异常" /></div>;
  const incidents = incidentsQuery.data ?? [];

  const effective = status ?? incident.status;
  const timeline = [
    { id: "t1", title: "AI 检测上报", time: incident.detectedAt, description: `${incident.type} · 置信度 ${incident.confidence}%`, tone: "danger" as const },
    { id: "t2", title: "现场证据留存", time: incident.detectedAt, description: "已截取相机帧与地图位置快照", tone: "neutral" as const },
    ...(effective !== "open" ? [{ id: "t3", title: "人工确认", time: "4 分钟前", description: "操作员已确认异常属实", tone: "warning" as const }] : []),
    ...(effective === "resolving" || effective === "resolved" ? [{ id: "t4", title: "开始处置", time: "10 分钟前", description: "已通知现场负责人处理", tone: "blue" as const }] : []),
    ...(effective === "resolved" ? [{ id: "t5", title: "处置完成", time: "12 分钟前", description: "现场复核通过，异常关闭", tone: "success" as const }] : []),
  ];

  return (
    <div className="page">
      <Link to="/incidents" className="back-link"><ArrowLeft size={15} />异常中心</Link>
      <ObjectHeader
        kicker={`Incident · ${incident.id}`}
        title={incident.title}
        subtitle={`${incident.type} · ${incident.location}`}
        badges={[{ label: levelLabel(incident.level), tone: levelTone(incident.level) }, { label: statusLabel[effective], tone: effective === "open" ? "danger" : effective === "resolved" ? "success" : "warning" }]}
        actions={
          <>
            {effective === "open" ? <Button size="sm" variant="primary" icon={CheckCircle2} onClick={() => setStatus("confirmed")}>确认</Button> : null}
            {effective === "confirmed" ? <Button size="sm" variant="primary" icon={Eye} onClick={() => setStatus("resolving")}>开始处理</Button> : null}
            {effective === "resolving" ? <Button size="sm" variant="primary" icon={Check} onClick={() => setStatus("resolved")}>标记解决</Button> : null}
            {effective === "open" || effective === "confirmed" ? <Button size="sm" variant="ghost" icon={X} onClick={() => setStatus("dismissed")}>忽略</Button> : null}
          </>
        }
      />
      <SplitView railTitle="异常" railCount={incidents.length} rail={incidents.map((i) => (
        <ObjectItem key={i.id} active={i.id === incident.id} icon={AlertTriangle} title={i.title} meta={`${i.robotName} · ${i.location}`} badge={<Badge tone={levelTone(i.level)}>{levelLabel(i.level)}</Badge>} onClick={() => navigate(`/incidents/${i.id}`)} />
      ))}>
        <div className="workspace">
          <div className="workspace-stats">
            <div className="ws-stat"><em>级别</em><strong>{levelLabel(incident.level)}</strong></div>
            <div className="ws-stat"><em>位置</em><strong>{incident.location}</strong></div>
            <div className="ws-stat"><em>发现时间</em><strong>{incident.detectedAt}</strong></div>
            <div className="ws-stat"><em>上报机器人</em><strong>{incident.robotName}</strong></div>
            <div className="ws-stat"><em>置信度</em><strong>{incident.confidence}%</strong></div>
          </div>
          <div className="ws-split ws-split-map">
            <div className="ws-media-cell">
              <div className="ws-section-title"><span>现场证据 · Evidence</span></div>
              <div className="evidence-frame">
                <div className="evidence-visual">
                  <span className="evidence-ai">AI Detection</span>
                  <div className="evidence-box" style={{ left: "24%", top: "28%", width: "30%", height: "46%" }}>
                    <span className="evidence-tag">{incident.title.split("·")[0].trim()} {incident.confidence}%</span>
                  </div>
                  <div className="evidence-scan" />
                </div>
              </div>
              <div className="evidence-meta">
                <span><StatusDot tone={levelTone(incident.level)} />{incident.type}</span>
                <span>置信度 {incident.confidence}%</span>
                <span>来源 {incident.robotName}</span>
              </div>
            </div>
            <div className="ws-section">
              <div className="ws-section-title"><span>异常信息</span></div>
              <p className="incident-desc">{incident.description}</p>
              <div className="ws-section-title"><span>处理时间线</span></div>
              <Timeline entries={timeline} />
            </div>
          </div>
        </div>
      </SplitView>
    </div>
  );
}
