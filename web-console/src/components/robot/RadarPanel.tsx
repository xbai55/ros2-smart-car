import { useRobotStream } from "../../hooks/useRobotStream";
import { Panel } from "../ui";
import { RadarCanvas } from "./RadarCanvas";

/** Reuses the provider's scan without opening another connection. */
export function RadarPanel({ className = "" }: { className?: string }) {
  const { status, connection } = useRobotStream();
  const ready = connection === "connected" && status.lidar.ok;
  const metrics = [
    { label: "有效扫描点", value: ready ? `${status.lidar.valid_count} 点` : "—" },
    { label: "扫描频率", value: ready ? `${status.lidar.scan_rate_hz.toFixed(1)} Hz` : "—" },
    { label: "数据年龄", value: ready && status.lidar.scan_age_sec != null ? `${status.lidar.scan_age_sec.toFixed(2)} s` : "—" },
  ];
  return (
    <Panel title="雷达点云" kicker="360° · Live LiDAR" className={`live-radar-panel ${className}`} bodyClassName="panel-flush"
      action={<span className={`scan-state ${ready ? "online" : "offline"}`}>{ready ? "实时扫描" : "等待扫描"}</span>}>
      <RadarCanvas />
      <dl className="radar-readouts" aria-label="雷达扫描指标">
        {metrics.map(metric => <div key={metric.label}><dt>{metric.label}</dt><dd>{metric.value}</dd></div>)}
      </dl>
    </Panel>
  );
}
