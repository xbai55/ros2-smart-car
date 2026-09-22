import type { LucideIcon } from "lucide-react";
import { AlertCircle, Inbox } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/cn";

export type Tone = "neutral" | "blue" | "success" | "warning" | "danger" | "info";

const toneClass: Record<Tone, string> = {
  neutral: "tone-neutral",
  blue: "tone-blue",
  success: "tone-success",
  warning: "tone-warning",
  danger: "tone-danger",
  info: "tone-info",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return <span className={cn("badge", toneClass[tone], className)}>{children}</span>;
}

export function StatusDot({ tone = "neutral", className }: { tone?: Tone; className?: string }) {
  return <span className={cn("status-dot", toneClass[tone], className)} aria-hidden="true" />;
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "outline" | "ghost" | "danger";
  size?: "sm" | "md";
  icon?: LucideIcon;
};

export function Button({ variant = "outline", size = "md", icon: Icon, className, children, ...rest }: ButtonProps) {
  return (
    <button type="button" className={cn("btn", `btn-${variant}`, `btn-${size}`, className)} {...rest}>
      {Icon ? <Icon size={size === "sm" ? 14 : 16} /> : null}
      {children}
    </button>
  );
}

type PanelProps = {
  title?: string;
  kicker?: string;
  action?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
};

export function Panel({ title, kicker, action, className, bodyClassName, children }: PanelProps) {
  return (
    <section className={cn("panel", className)}>
      {(title || kicker || action) ? (
        <header className="panel-head">
          <div className="panel-head-title">
            {kicker ? <span className="panel-kicker">{kicker}</span> : null}
            {title ? <h3 className="panel-title">{title}</h3> : null}
          </div>
          {action ? <div className="panel-action">{action}</div> : null}
        </header>
      ) : null}
      <div className={cn("panel-body", bodyClassName)}>{children}</div>
    </section>
  );
}

export function ProgressBar({ value, tone = "blue", className }: { value: number; tone?: Tone; className?: string }) {
  const safe = Math.max(0, Math.min(100, value));
  return (
    <div className={cn("progress", className)} role="progressbar" aria-valuenow={Math.round(safe)} aria-valuemin={0} aria-valuemax={100}>
      <div className={cn("progress-fill", toneClass[tone])} style={{ width: `${safe}%` }} />
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <span className={cn("skeleton", className)} aria-hidden="true" />;
}

export function EmptyState({ title, hint, className }: { title: string; hint?: string; className?: string }) {
  return (
    <div className={cn("empty-state", className)}>
      <Inbox size={26} strokeWidth={1.6} />
      <strong>{title}</strong>
      {hint ? <span>{hint}</span> : null}
    </div>
  );
}

export function ErrorState({ title, onRetry }: { title: string; onRetry?: () => void }) {
  return (
    <div className="empty-state error">
      <AlertCircle size={26} strokeWidth={1.6} />
      <strong>{title}</strong>
      {onRetry ? <Button size="sm" variant="outline" onClick={onRetry}>重试</Button> : null}
    </div>
  );
}

export type TabItem = { id: string; label: string; icon?: LucideIcon };

export function Tabs({ items, active, onChange, className }: { items: TabItem[]; active: string; onChange: (id: string) => void; className?: string }) {
  return (
    <div className={cn("tabs", className)} role="tablist">
      {items.map((item) => {
        const Icon = item.icon;
        const isActive = item.id === active;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            className={cn("tab", isActive && "active")}
            onClick={() => onChange(item.id)}
          >
            {Icon ? <Icon size={15} /> : null}
            {item.label}
          </button>
        );
      })}
    </div>
  );
}

export function Metric({ label, value, hint, tone = "blue", icon: Icon }: { label: string; value: ReactNode; hint?: string; tone?: Tone; icon?: LucideIcon }) {
  return (
    <div className={cn("metric", toneClass[tone])}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      {hint ? <div className="metric-hint">{hint}</div> : null}
      {Icon ? <Icon className="metric-icon" size={22} strokeWidth={1.6} /> : null}
    </div>
  );
}
