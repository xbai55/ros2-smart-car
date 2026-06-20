import type { ReactNode } from "react";

type HudPanelProps = {
  children: ReactNode;
  className?: string;
  title?: string;
  subtitle?: string;
  action?: ReactNode;
};

export function HudPanel({ children, className = "", title, subtitle, action }: HudPanelProps) {
  return (
    <section className={`hud-panel ${className}`}>
      {(title || subtitle || action) && (
        <div className="panel-heading">
          <div>
            {title && <p className="panel-kicker">{title}</p>}
            {subtitle && <h2>{subtitle}</h2>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}
