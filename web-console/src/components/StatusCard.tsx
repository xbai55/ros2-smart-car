import type { LucideIcon } from "lucide-react";

type StatusCardProps = {
  title: string;
  value: string;
  description: string;
  icon: LucideIcon;
  variant?: "normal" | "danger" | "success";
};

export function StatusCard({ title, value, description, icon: Icon, variant = "normal" }: StatusCardProps) {
  return (
    <article className={`status-card ${variant}`}>
      <div className="status-icon">
        <Icon size={32} />
      </div>
      <div>
        <p>{title}</p>
        <strong>{value}</strong>
        <span>{description}</span>
      </div>
    </article>
  );
}
