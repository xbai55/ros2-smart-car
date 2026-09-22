import { useEffect, useMemo, useState } from "react";
import {
  createRobotApi,
  initialRobotStatus,
  normalizeRobotStatus,
  statusSocketUrl,
  type ConnectionState,
  type RobotStatus,
} from "../robotApi";

export function useRobotStream() {
  const api = useMemo(() => createRobotApi(), []);
  const [status, setStatus] = useState<RobotStatus>(initialRobotStatus);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    let socket: WebSocket | undefined;
    let reconnectTimer: number | undefined;

    const connect = async () => {
      setConnection("connecting");
      try {
        const snapshot = await api.getStatus();
        if (active) { setStatus(normalizeRobotStatus(snapshot)); setError(""); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "状态接口不可用");
      }
      if (!active) return;
      socket = new WebSocket(statusSocketUrl(window.location));
      socket.onopen = () => { if (active) setConnection("connected"); };
      socket.onmessage = (event) => {
        if (!active) return;
        try {
          setStatus(normalizeRobotStatus(JSON.parse(event.data) as Partial<RobotStatus>));
          setError("");
        } catch {
          setError("收到无法解析的状态数据");
        }
      };
      socket.onerror = () => { if (active) setConnection("disconnected"); };
      socket.onclose = () => {
        if (!active) return;
        setConnection("disconnected");
        reconnectTimer = window.setTimeout(connect, 1500);
      };
    };

    void connect();
    return () => {
      active = false;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      socket?.close();
    };
  }, [api]);

  const invoke = async (operation: () => Promise<unknown>) => {
    try { await operation(); } catch { /* 控制失败由后端状态回显 */ }
  };

  return {
    status,
    connection,
    error,
    setMode: (mode: string) => invoke(() => api.setMode(mode)),
    sendCommand: (command: string) => invoke(() => api.sendCommand(command)),
    setEmergencyStop: (enabled: boolean) => invoke(() => api.setEmergencyStop(enabled)),
    setSpeed: (scale: number) => invoke(() => api.setSpeed(scale)),
  };
}
