import { CheckCircle2, Link2, OctagonAlert, Wifi, WifiOff } from "lucide-react";
import { useRobotStream } from "../../hooks/useRobotStream";
import { MODE_LABELS } from "../../liveControl";
import { cn } from "../../lib/cn";
export function LiveConnectionBar() {
  const robot = useRobotStream(), connected = robot.connection === "connected";
  return <div className="live-connection-bar">
    <span className={cn("live-state-pill", connected ? "online" : "offline")}>{connected ? <Wifi size={14}/> : <WifiOff size={14}/>} {connected ? "实车在线" : robot.connection === "connecting" ? "正在连接小车" : "实车未连接"}</span>
    <span><Link2 size={13}/>智巡一号 · r-001</span>
    <span>{connected ? MODE_LABELS[robot.status.mode] ?? robot.status.mode : "等待实时状态"}</span>
    <span className="live-last-seen">{robot.receivedAt ? "更新于 " + new Date(robot.receivedAt).toLocaleTimeString("zh-CN", {hour12:false}) : "尚未收到数据"}</span>
    <button type="button" className={cn("live-emergency", robot.status.emergency_stop && "latched")} disabled={!connected} onClick={() => void robot.setEmergencyStop(!robot.status.emergency_stop)}><OctagonAlert size={15}/>{robot.status.emergency_stop ? "解除急停" : "紧急停止"}</button>
  </div>;
}
export function LiveFeedback() {
  const { error, message, connectionError, connection } = useRobotStream();
  const failure = error || (connection !== "connected" ? connectionError : "");
  return failure ? <div className="live-feedback failure" role="alert"><OctagonAlert size={16}/><span>{failure}</span></div>
    : message ? <div className="live-feedback success" role="status"><CheckCircle2 size={16}/><span>{message}</span></div> : null;
}
