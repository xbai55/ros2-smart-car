import { Activity, Cpu, Gauge, MemoryStick, Network, Server } from "lucide-react";
import { useRobotStream } from "../hooks/useRobotStream";
import { Panel, ProgressBar, StatusDot } from "../components/ui";
import { ObjectHeader } from "../components/shared";

export function SystemPage() {
  const { status, connection } = useRobotStream();
  const nodes = Object.entries(status.nodes);

  const resources = [
    { icon: Cpu, label: "CPU", value: 38, hint: "x86_64 · 4 核" },
    { icon: MemoryStick, label: "内存", value: 61, hint: "3.9 / 6.4 GB" },
    { icon: Gauge, label: "GPU", value: 24, hint: "Jetson · CUDA 可用" },
    { icon: Network, label: "网络", value: 12, hint: "延迟 8 ms" },
  ];

  return (
    <div className="page">
      <ObjectHeader kicker="System" title="系统状态" subtitle="计算资源、网络与 ROS2 节点的运行健康" badges={[{ label: connection === "connected" ? "实时在线" : "离线", tone: connection === "connected" ? "success" : "warning" }]} />

      <div className="system-grid">
        <Panel title="计算资源" kicker="Resources" className="list-panel">
          <div className="resource-list">
            {resources.map((r) => {
              const Icon = r.icon;
              return (
                <div key={r.label} className="resource-item">
                  <span className="resource-icon"><Icon size={16} /></span>
                  <div className="resource-main"><em>{r.label}</em><ProgressBar value={r.value} tone={r.value > 80 ? "danger" : r.value > 60 ? "warning" : "success"} /></div>
                  <div className="resource-value"><strong>{r.value}%</strong><em>{r.hint}</em></div>
                </div>
              );
            })}
          </div>
        </Panel>

        <Panel title="ROS2 节点健康" kicker="Nodes" className="list-panel">
          {nodes.length ? (
            <div className="node-list">
              {nodes.map(([name, value]) => (
                <div key={name} className="sys-node">
                  <StatusDot tone={value === "ok" ? "success" : "danger"} />
                  <span>{name}</span>
                  <em>{value}</em>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-state"><Server size={26} /><strong>未检测到 ROS2 节点</strong><span>请确认 system_status_node 已启动</span></div>
          )}
        </Panel>

        <Panel title="控制链路" kicker="Safety Chain" className="list-panel">
          <div className="chain-list">
            <ChainStep label="Flutter / Web" desc="业务指令入口" active />
            <ChainStep label="FastAPI / Gateway" desc="指令转发与权限校验" active />
            <ChainStep label="decision_controller" desc="唯一 /cmd_vel 仲裁节点" active />
            <ChainStep label="Safety Check" desc="急停 · 雷达超时 · 近障停车" active />
            <ChainStep label="/cmd_vel" desc="底盘速度输出" tone={connection === "connected" ? "ok" : "off"} />
          </div>
        </Panel>
      </div>
    </div>
  );
}

function ChainStep({ label, desc, active, tone }: { label: string; desc: string; active?: boolean; tone?: "ok" | "off" }) {
  return (
    <div className="chain-step">
      <StatusDot tone={tone === "off" ? "warning" : active ? "success" : "neutral"} />
      <div><strong>{label}</strong><em>{desc}</em></div>
    </div>
  );
}
