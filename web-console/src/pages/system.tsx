import { useRobotStream } from "../hooks/useRobotStream";
import { EmptyState, Panel, StatusDot } from "../components/ui";
import { ObjectHeader } from "../components/shared";
export function SystemPage() {
  const { status, connection } = useRobotStream();
  const online = connection === "connected";
  const nodes = online ? Object.entries(status.nodes) : [];
  const health = [{ name: "雷达", state: status.lidar }, { name: "里程计", state: status.odom }, { name: "坐标变换", state: status.tf }, { name: "速度输出", state: status.cmd_vel }];
  return <div className="page"><ObjectHeader kicker="System" title="系统状态" subtitle="车端实时传感器与节点状态" badges={[{ label: online ? "实车在线" : "未连接", tone: online ? "success" : "neutral" }]}/><div className="system-grid"><Panel title="计算资源"><EmptyState title="资源指标未采集" hint="车端当前未提供 CPU、内存、GPU 使用率和网络延迟。"/></Panel><Panel title="ROS2 节点健康">{nodes.length ? nodes.map(([name, value]) => <div key={name} className="sys-node"><StatusDot tone={value === "ok" ? "success" : "warning"}/><span>{name}</span><em>{value}</em></div>) : <EmptyState title="暂无实时节点数据"/>}</Panel><Panel title="传感器与控制输出">{health.map(h => <div key={h.name} className="sys-node"><StatusDot tone={!online ? "neutral" : h.state.ok ? "success" : "warning"}/><span>{h.name}</span><em>{online ? h.state.message : "未连接"}</em></div>)}<div className="sys-node"><span>急停锁定</span><em>{online ? status.emergency_stop ? "已锁定" : "未锁定" : "未知"}</em></div></Panel></div></div>;
}
