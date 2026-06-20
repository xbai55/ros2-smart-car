import { BarChart3 } from "lucide-react";
import { modes, type ModeId } from "../data/consoleData";
import type { ConnectionState } from "../robotApi";

type Props = { currentMode: ModeId; connection: ConnectionState; onModeChange: (mode: ModeId) => void };

export function Sidebar({ currentMode, connection, onModeChange }: Props) {
  const connected = connection === "connected";
  return (
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark"><span>SC</span></div><div><h1>Smart Car</h1><p>Yahboom ROSMASTER X3</p></div></div>
      <nav className="mode-nav" aria-label="车辆模式">
        {modes.map((mode) => {
          const Icon = mode.icon;
          return (
            <button key={mode.id} className={`mode-item ${mode.id === currentMode ? "active" : ""}`} type="button" onClick={() => onModeChange(mode.id)}>
              <span className="mode-icon"><Icon size={23} /></span>
              <span className="mode-copy"><strong>{mode.name}</strong><small>{mode.description}</small></span>
            </button>
          );
        })}
      </nav>
      <div className="ws-card">
        <div className="ws-status">
          <span className={`status-dot ${connected ? "green" : ""}`} />
          <div><span>WebSocket</span><strong>{connected ? "已连接" : connection === "connecting" ? "连接中" : "已断开"}</strong></div>
        </div>
        <div className="signal-bars" aria-hidden="true">{[18,28,40,56,72,52,34].map((height,index)=><i key={index} style={{height:`${connected ? height : 10}%`}} />)}</div>
        <BarChart3 className="ws-watermark" size={72} />
      </div>
    </aside>
  );
}
