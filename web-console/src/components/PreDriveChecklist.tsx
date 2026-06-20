import { Check, CircleX, ShieldCheck } from "lucide-react";
import type { ConnectionState, RobotStatus } from "../robotApi";
import type { VideoState } from "./LiveCameraPanel";

type Props = { status: RobotStatus; connection: ConnectionState; videoState: VideoState };

export function PreDriveChecklist({ status, connection, videoState }: Props) {
  const checks = [
    { label: "WebSocket 与后端连接", ok: connection === "connected" },
    { label: "system_status_node 在线", ok: status.nodes.system_status_node === "ok" },
    { label: "雷达已有实时点云", ok: status.radar_points.length > 0 },
    { label: "摄像头已有视频帧", ok: videoState === "connected" }
  ];
  return (
    <section className="checklist hud-panel">
      <h2>发车前检查</h2>
      <div className="checklist-grid">{checks.map((item)=>(
        <article key={item.label} className={item.ok ? "" : "check-failed"}>
          <ShieldCheck size={19}/><span>{item.label}</span>{item.ok ? <Check size={18}/> : <CircleX size={18}/>}
        </article>
      ))}</div>
    </section>
  );
}
