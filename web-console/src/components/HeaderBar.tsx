import { AlertTriangle } from "lucide-react";

type Props = { emergency: boolean; updatedAt: number; error: string; onEmergency: () => void };

export function HeaderBar({ emergency, updatedAt, error, onEmergency }: Props) {
  const timestamp = updatedAt ? new Date(updatedAt * 1000).toLocaleTimeString("zh-CN", { hour12: false }) : "--:--:--";
  return (
    <header className="header-bar">
      <div className="title-block"><span>ROS2 Web Console</span><div className="title-row"><h1>实时驾驶与感知控制</h1><p>REAL-TIME DRIVING &amp; PERCEPTION CONTROL</p></div></div>
      <div className="header-actions">
        {error ? <div className="emergency-banner">{error}</div> : emergency ? <div className="emergency-banner">急停已触发，底盘输出锁定为零</div> : null}
        <div className="update-pill"><span>状态更新 {timestamp}</span><span className={`status-dot ${updatedAt ? "green" : ""}`} /></div>
        <button className="emergency-btn" type="button" onClick={onEmergency}>
          <AlertTriangle size={30} />
          <span><strong>{emergency ? "解除急停" : "急停"}</strong><small>EMERGENCY STOP</small></span>
        </button>
      </div>
    </header>
  );
}
