import { Check, CircleDashed, PackageCheck, PackageOpen, Truck } from "lucide-react";
import type { TransportStage } from "../../types/domain";
import { cn } from "../../lib/cn";

const STAGES: Array<{ id: TransportStage; label: string }> = [
  { id: "pickup", label: "前往取件" },
  { id: "loading", label: "等待放件" },
  { id: "transit", label: "运输中" },
  { id: "arrived", label: "到达" },
  { id: "handover", label: "等待交接" },
  { id: "done", label: "完成" },
];

export function MissionStepper({ stage }: { stage?: TransportStage }) {
  const currentIndex = stage ? STAGES.findIndex((s) => s.id === stage) : 0;
  const normalized = currentIndex < 0 ? 0 : currentIndex;
  return (
    <ol className="mission-stepper">
      {STAGES.map((step, i) => {
        const done = i < normalized;
        const active = i === normalized;
        return (
          <li key={step.id} className={cn("step", done && "done", active && "active")}>
            <span className="step-dot">
              {done ? <Check size={13} /> : active ? <PackageOpen size={13} /> : <CircleDashed size={13} />}
            </span>
            <span className="step-label">{step.label}</span>
            {i < STAGES.length - 1 ? <span className="step-line" /> : null}
          </li>
        );
      })}
    </ol>
  );
}
