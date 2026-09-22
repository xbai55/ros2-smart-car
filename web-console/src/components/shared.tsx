import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { Badge, EmptyState, type Tone } from "./ui";

type ObjectHeaderProps = {
  kicker?: string;
  title: string;
  subtitle?: string;
  badges?: Array<{ label: string; tone?: Tone }>;
  actions?: ReactNode;
};

export function ObjectHeader({ kicker, title, subtitle, badges, actions }: ObjectHeaderProps) {
  return (
    <header className="object-header">
      <div className="object-header-copy">
        {kicker ? <span className="object-kicker">{kicker}</span> : null}
        <h1 className="object-title">{title}</h1>
        {subtitle ? <p className="object-subtitle">{subtitle}</p> : null}
        {badges?.length ? (
          <div className="object-badges">
            {badges.map((b) => <Badge key={b.label} tone={b.tone ?? "neutral"}>{b.label}</Badge>)}
          </div>
        ) : null}
      </div>
      {actions ? <div className="object-actions">{actions}</div> : null}
    </header>
  );
}

export type Column<T> = {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  width?: string;
  align?: "left" | "right";
};

type DataTableProps<T> = {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  emptyTitle?: string;
  loading?: boolean;
};

export function DataTable<T>({ columns, rows, rowKey, onRowClick, emptyTitle = "暂无数据", loading = false }: DataTableProps<T>) {
  if (loading) {
    return (
      <div className="table-skeleton" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, i) => <div key={i} className="table-skeleton-row" />)}
      </div>
    );
  }
  if (!rows.length) return <EmptyState title={emptyTitle} />;
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((col) => (
              <th key={col.key} style={{ width: col.width, textAlign: col.align }}>{col.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={rowKey(row)} className={onRowClick ? "clickable" : ""} onClick={onRowClick ? () => onRowClick(row) : undefined}>
              {columns.map((col) => (
                <td key={col.key} style={{ textAlign: col.align }}>{col.render(row)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export type TimelineEntry = {
  id: string;
  title: string;
  time: string;
  description?: string;
  tone?: Tone;
  icon?: LucideIcon;
};

export function Timeline({ entries, className }: { entries: TimelineEntry[]; className?: string }) {
  return (
    <ol className={cn("timeline", className)}>
      {entries.map((entry) => {
        const Icon = entry.icon;
        return (
          <li key={entry.id} className="timeline-item">
            <span className={cn("timeline-dot", entry.tone ?? "neutral")}>{Icon ? <Icon size={13} /> : null}</span>
            <div className="timeline-content">
              <div className="timeline-head">
                <strong>{entry.title}</strong>
                <time>{entry.time}</time>
              </div>
              {entry.description ? <p>{entry.description}</p> : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function svgPath(points: number[], width: number, height: number, pad: number): string {
  const max = Math.max(...points, 1);
  const min = Math.min(...points, 0);
  const range = Math.max(1, max - min);
  const stepX = points.length > 1 ? (width - pad * 2) / (points.length - 1) : 0;
  return points
    .map((value, i) => {
      const x = pad + i * stepX;
      const y = height - pad - ((value - min) / range) * (height - pad * 2);
      return `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
}

export function LineChart({ series, labels, height = 180 }: { series: Array<{ name: string; color: string; data: number[] }>; labels: string[]; height?: number }) {
  const width = 720;
  const pad = 18;
  const maxVal = Math.max(...series.flatMap((s) => s.data), 1);
  const minVal = Math.min(...series.flatMap((s) => s.data), 0);
  const range = Math.max(1, maxVal - minVal);
  const gridLines = [0.25, 0.5, 0.75];
  return (
    <svg className="line-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="趋势图">
      {gridLines.map((g) => {
        const y = pad + (1 - g) * (height - pad * 2);
        return <line key={g} x1={pad} x2={width - pad} y1={y} y2={y} className="chart-grid" />;
      })}
      {labels.map((label, i) => {
        const x = pad + (i * (width - pad * 2)) / (labels.length - 1);
        return <text key={label} x={x} y={height - 3} className="chart-label" textAnchor="middle">{label}</text>;
      })}
      {series.map((s) => (
        <path key={s.name} d={svgPath(s.data, width, height, pad)} fill="none" stroke={s.color} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round" />
      ))}
      {series.flatMap((s) => s.data.map((value, i) => {
        const x = pad + (i * (width - pad * 2)) / (Math.max(1, s.data.length - 1));
        const y = height - pad - ((value - minVal) / range) * (height - pad * 2);
        return <circle key={`${s.name}-${i}`} cx={x} cy={y} r={2.6} fill={s.color} />;
      }))}
    </svg>
  );
}

export function BarChart({ values, labels, color = "#2563eb", height = 180 }: { values: number[]; labels: string[]; color?: string; height?: number }) {
  const width = 720;
  const pad = 18;
  const max = Math.max(...values, 1);
  return (
    <svg className="bar-chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="柱状图">
      {values.map((value, i) => {
        const barWidth = (width - pad * 2) / values.length;
        const barH = (value / max) * (height - pad * 2 - 14);
        const x = pad + i * barWidth + barWidth * 0.18;
        const y = height - pad - 14 - barH;
        return (
          <g key={i}>
            <rect x={x} y={y} width={barWidth * 0.64} height={barH} rx={3} fill={color} opacity={0.9} />
            <text x={x + barWidth * 0.32} y={height - 3} className="chart-label" textAnchor="middle">{labels[i]}</text>
            <text x={x + barWidth * 0.32} y={y - 5} className="chart-value" textAnchor="middle">{value}</text>
          </g>
        );
      })}
    </svg>
  );
}

export function SplitView({ railTitle, railCount, rail, children }: { railTitle: string; railCount?: number; rail: ReactNode; children: ReactNode }) {
  return (
    <div className="split-view">
      <aside className="split-list">
        <header className="split-list-head">
          <span>{railTitle}</span>
          {railCount != null ? <em>{railCount}</em> : null}
        </header>
        {rail}
      </aside>
      <section className="split-detail">{children}</section>
    </div>
  );
}

export function ObjectItem({ active, onClick, icon: Icon, title, meta, badge }: { active?: boolean; onClick?: () => void; icon?: LucideIcon; title: ReactNode; meta?: ReactNode; badge?: ReactNode }) {
  return (
    <button type="button" className={cn("obj-item", active && "active")} onClick={onClick}>
      {Icon ? <span className="obj-item-icon"><Icon size={16} /></span> : null}
      <span className="obj-item-main"><strong>{title}</strong>{meta != null ? <em>{meta}</em> : null}</span>
      {badge}
    </button>
  );
}

