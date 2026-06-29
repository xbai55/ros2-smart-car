import { ChevronDown, ChevronUp, Crosshair, Hexagon, Radio, Server, Video, Wifi } from "lucide-react";
import type { ConnectionState, RobotStatus } from "../robotApi";
import type { VideoState } from "./LiveCameraPanel";
import { HudPanel } from "./HudPanel";

type Props = { expanded: boolean; onToggle: () => void; status: RobotStatus; connection: ConnectionState; videoState: VideoState };

export function SystemSummaryPanel({ expanded, onToggle, status, connection, videoState }: Props) {
  const nodeCount = Object.values(status.nodes).filter((value) => value === "ok").length;
  const nodeTotal = Object.keys(status.nodes).length;
  const target = status.color_target;
  const videoLabel = videoState === "connected" ? "已连接" : videoState === "error" ? "故障" : "等待中";
  const colorValue = target?.visible ? `visible ${(target.offset ?? 0).toFixed(4)}` : "未检测";
  const items = [
    { title: "最近命令", value: status.last_command || "stop", detail: "来自后端状态", icon: Radio },
    { title: "YOLO 结果", value: status.detection || "无目标", detail: "/vision/detection", icon: Hexagon },
    { title: "颜色目标", value: colorValue, detail: "/vision/color_target", icon: Crosshair },
    { title: "节点在线", value: `${nodeCount} / ${nodeTotal}`, detail: "system_status_node", icon: Server },
    { title: "视频源", value: videoLabel, detail: "/video_feed", icon: Video },
    { title: "控制通道", value: connection, detail: "WebSocket", icon: Wifi }
  ];

  return (
    <HudPanel className="system-summary-panel" title="System Summary" subtitle="感知与节点汇总">
      <div className="summary-grid">
        {items.map((item) => {
          const Icon = item.icon;
          return <article key={item.title} className="summary-item"><Icon size={21}/><span>{item.title}</span><strong>{item.value}</strong><small>{item.detail}</small></article>;
        })}
      </div>
      <div className="summary-color-line">
        <span>颜色配置</span><strong>{status.color_config.name} {status.color_config.hsv_low.join(",")} / {status.color_config.hsv_high.join(",")}</strong>
      </div>
      <button className={`json-toggle ${expanded ? "open" : ""}`} type="button" onClick={onToggle}>
        <span>system_status_node</span><span>真实 JSON 状态</span>{expanded ? <ChevronUp size={17}/> : <ChevronDown size={17}/>}
      </button>
      {expanded ? <pre className="json-view">{JSON.stringify(status, null, 2)}</pre> : null}
    </HudPanel>
  );
}
