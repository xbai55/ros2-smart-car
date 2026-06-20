import type { LucideIcon } from "lucide-react";

type QuickResultCardProps = {
  title: string;
  value: string;
  description: string;
  icon: LucideIcon;
};

export function QuickResultCard({ title, value, description, icon: Icon }: QuickResultCardProps) {
  return (
    <article className="quick-card">
      <div className="quick-icon">
        <Icon size={27} />
      </div>
      <div>
        <p>{title}</p>
        <strong>{value}</strong>
        <span>{description}</span>
      </div>
    </article>
  );
}
