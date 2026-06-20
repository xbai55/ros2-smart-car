import { ChevronDown, ChevronUp } from "lucide-react";
import type { ConnectionState, RobotStatus } from "../robotApi";
import type { VideoState } from "./LiveCameraPanel";
import { HudPanel } from "./HudPanel";

type Props = { expanded: boolean; onToggle: () => void; status: RobotStatus; connection: ConnectionState; videoState: VideoState };

export function PerceptionHealthPanel({ expanded, onToggle, status, connection, videoState }: Props) {
  const nodeCount = Object.values(status.nodes).filter((value) => value === "ok").length;
  const healthItems = [
    { title: "节点在线", value: `${nodeCount} / ${Object.keys(status.nodes).length}` },
    { title: "当前颜色配置", value: `${status.color_config.name} ${status.color_config.hsv_low.join(",")} / ${status.color_config.hsv_high.join(",")}` },
    { title: "视频源", value: videoState === "connected" ? "已连接" : videoState === "error" ? "故障" : "等待中" },
    { title: "控制通道", value: connection }
  ];
  return (
    <HudPanel className="health-panel" title="Perception & Health" subtitle="感知与节点健康">
      <div className="health-grid">{healthItems.map((item)=><div key={item.title} className="health-item"><span>{item.title}</span><strong>{item.value}</strong></div>)}</div>
      <button className={`json-toggle ${expanded ? "open" : ""}`} type="button" onClick={onToggle}>
        <span>system_status_node</span><span>真实 JSON 状态</span>{expanded ? <ChevronUp size={17}/> : <ChevronDown size={17}/>}
      </button>
      {expanded ? <pre className="json-view">{JSON.stringify(status, null, 2)}</pre> : null}
    </HudPanel>
  );
}
