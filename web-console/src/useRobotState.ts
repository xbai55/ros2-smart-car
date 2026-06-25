import { useCallback, useEffect, useMemo, useState } from "react";
import { createRobotApi, initialRobotStatus, statusSocketUrl, type ColorConfig, type ConnectionState, type RobotStatus } from "./robotApi";
import { loadSavedColor, saveColor } from "./colorPersistence";

export function useRobotState() {
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
        const savedColor = loadSavedColor(window.localStorage);
        if (savedColor) await api.setColorConfig(savedColor);
        const snapshot = await api.getStatus();
        if (active) { setStatus(snapshot); setError(""); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "状态接口不可用");
      }
      if (!active) return;
      socket = new WebSocket(statusSocketUrl(window.location));
      socket.onopen = () => active && setConnection("connected");
      socket.onmessage = (event) => {
        if (!active) return;
        try { setStatus(JSON.parse(event.data) as RobotStatus); setError(""); }
        catch { setError("收到无法解析的状态数据"); }
      };
      socket.onerror = () => active && setConnection("disconnected");
      socket.onclose = () => {
        if (!active) return;
        setConnection("disconnected");
        reconnectTimer = window.setTimeout(connect, 1500);
      };
    };
    void connect();
    return () => { active = false; if (reconnectTimer) clearTimeout(reconnectTimer); socket?.close(); };
  }, [api]);

  const run = useCallback(async <T,>(operation: () => Promise<T>, apply: (value: T) => void) => {
    try { const value = await operation(); apply(value); setError(""); return value; }
    catch (reason) { setError(reason instanceof Error ? reason.message : "控制请求失败"); throw reason; }
  }, []);

  return {
    status, connection, error,
    setMode: (mode: string) => run(() => api.setMode(mode), (v) => setStatus((s) => ({ ...s, mode: v.mode }))),
    sendCommand: (command: string) => run(() => api.sendCommand(command), (v) => setStatus((s) => ({ ...s, last_command: v.command }))),
    setEmergencyStop: (enabled: boolean) => run(() => api.setEmergencyStop(enabled), (v) => setStatus((s) => ({ ...s, emergency_stop: v.emergency_stop, mode: v.emergency_stop ? "stop" : s.mode }))),
    setSpeed: (scale: number) => run(() => api.setSpeed(scale), (v) => setStatus((s) => ({ ...s, speed_scale: v.speed_scale }))),
    restartMapping: () => run(() => api.restartMapping(), () => setStatus((s) => ({
      ...s,
      mode: "mapping",
      last_command: "stop",
      map: { ok: false, message: "restarting", map_age_sec: null, width: 0, height: 0, resolution: 0, frame_id: "" }
    }))),
    setColorConfig: (config: ColorConfig) => run(() => api.setColorConfig(config), (v) => {
      saveColor(window.localStorage, v.color_config);
      setStatus((s) => ({ ...s, color_config: v.color_config }));
    })
  };
}
