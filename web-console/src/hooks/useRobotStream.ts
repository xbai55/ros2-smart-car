import { createContext, createElement, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createRobotApi, initialRobotStatus, normalizeRobotStatus, statusSocketUrl, type ConnectionState, type RobotStatus, type MappingSaveResult } from "../robotApi";
import { LIVE_ROBOT_ID, percentToScale, canDrive, validThreshold } from "../liveControl";
import type { MapSnapshot, MotionMappingSettings } from "../robotApi";
import { statusSocketTimedOut } from "../statusConnection";
import { MapSessionGate, startMapPolling, captureInitialMapYaw } from "../mapSession";
import { businessApi, getBusinessSession, type SlamMapDraft } from "../services/businessApi";

function useSharedRobot() {
  const api = useMemo(() => createRobotApi(), []);
  const [status, setStatus] = useState<RobotStatus>(initialRobotStatus);
  const [connection, setConnection] = useState<ConnectionState>("connecting");
  const [connectionError, setConnectionError] = useState("");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(0);
  const [receivedAt, setReceivedAt] = useState(0);
  const [savedMap, setSavedMap] = useState<MappingSaveResult | null>(null);
  const [mapSnapshot, setMapSnapshot] = useState<MapSnapshot | null>(null);
  const [mapError, setMapError] = useState("");
  const [mapSessionKey, setMapSessionKey] = useState(0);
  const [initialMapYaw, setInitialMapYaw] = useState<number | null>(null);
  const mapGate = useRef(new MapSessionGate());
  const mapRef = useRef<MapSnapshot | null>(null);
  const clearMap = useCallback(() => { mapRef.current = null; setMapSnapshot(null); setMapError(""); setInitialMapYaw(null); setMapSessionKey(n => n + 1); }, []);
  const statusRef = useRef(status);
  const connectedRef = useRef(false);
  const alive = useRef(true);
  const latestFrame = useRef(0);
  const updateStatus = useCallback((value: RobotStatus) => { statusRef.current = value; setStatus(value); }, []);

  useEffect(() => {
    alive.current = true;
    let active = true, socket: WebSocket | undefined, reconnect: number | undefined;
    let socketStartedAt = 0;
    const accept = (snapshot: Partial<RobotStatus>) => {
      if (!active || typeof snapshot.mode !== "string") return;
      const value = normalizeRobotStatus(snapshot);
      if (!mapGate.current.restarting && snapshot.mapping && snapshot.mapping.session_id !== mapGate.current.session) {
        if (!mapGate.current.changeSession(snapshot.mapping.session_id)) return;
        clearMap();
      }
      updateStatus(value);
      latestFrame.current = Date.now();
      setReceivedAt(latestFrame.current);
      connectedRef.current = value.network === "connected";
      setConnection(connectedRef.current ? "connected" : "disconnected");
      setConnectionError(connectedRef.current ? "" : "车端已连接，等待有效的机器人状态");
    };
    const connect = async () => {
      if (!active) return;
      setConnection("connecting");
      latestFrame.current = 0;
      try { accept(await api.getStatus()); } catch {
        if (active) {
          connectedRef.current = false;
          setConnection("disconnected");
          setConnectionError("无法连接小车，请检查小车是否开机及网络连接。正在重试连接。");
        }
      }
      if (!active) return;
      socket = new WebSocket(statusSocketUrl(window.location));
      socketStartedAt = Date.now();
      socket.onmessage = event => { try { accept(JSON.parse(event.data)); } catch { if (active) setConnectionError("车端状态格式异常"); } };
      socket.onerror = () => { if (active) { connectedRef.current = false; setConnection("disconnected"); } };
      socket.onclose = () => {
        if (!active) return;
        connectedRef.current = false; setConnection("disconnected"); setConnectionError("与小车的连接已断开，正在重连");
        reconnect = window.setTimeout(() => void connect(), 1500);
      };
    };
    void connect();
    const watchdog = window.setInterval(() => {
      if (socket && statusSocketTimedOut(socket.readyState, latestFrame.current, socketStartedAt, Date.now())) {
        connectedRef.current = false; setConnection("disconnected"); setConnectionError("实时状态已超时，运动控制暂停");
        socket?.close();
      }
    }, 500);
    return () => { active = false; alive.current = false; connectedRef.current = false; clearInterval(watchdog); if (reconnect) clearTimeout(reconnect); socket?.close(); };
  }, [api, updateStatus, clearMap]);

  const mapAvailable = status.map.ok || status.map.width > 0 || status.mode === "mapping" || status.navigation.ready;
  useEffect(() => {
    if (connection !== "connected" || !mapAvailable) { if (mapRef.current) setMapError(connection !== "connected" ? "连接已断开，显示最近地图" : "地图暂未更新，显示最近地图"); return; }
    return startMapPolling({
      request: signal => api.getMap(AbortSignal.any([signal, AbortSignal.timeout(5000)])),
      gate: mapGate.current, current: () => mapRef.current,
      receive: snapshot => { mapRef.current = snapshot; setMapSnapshot(snapshot); }, failed: setMapError,
    }, { now: Date.now, later: (callback, delay) => window.setTimeout(callback, delay), cancel: timer => clearTimeout(timer as number) });
  }, [api, connection, mapAvailable, mapSessionKey]);
  useEffect(() => {
    setInitialMapYaw(previous => captureInitialMapYaw(previous, mapSnapshot, status.mapping, status.map_pose, connection === "connected", !!mapError));
  }, [mapSnapshot, status.mapping, status.map_pose, connection, mapError]);

  const perform = useCallback(async <T,>(operation: () => Promise<T>, label: string, silent = false): Promise<T | null> => {
    if (!connectedRef.current) { if (!silent) setError("小车未连接，操作未发送"); return null; }
    if (!silent) { setPending(n => n + 1); setError(""); setMessage(""); }
    try {
      const result = await operation();
      if (alive.current && !silent && label) setMessage(label);
      return result;
    } catch (reason) {
      if (alive.current) setError(reason instanceof Error ? reason.message : "操作失败，请重试");
      return null;
    } finally { if (alive.current && !silent) setPending(n => Math.max(0, n - 1)); }
  }, []);
  const sendCommand = useCallback(async (command: string) => {
    if (command !== "stop" && !canDrive(statusRef.current, connectedRef.current)) return false;
    return (await perform(() => api.sendCommand(command), "", true)) !== null;
  }, [api, perform]);
  const setMode = useCallback(async (mode: string) => {
    window.dispatchEvent(new Event("robot-control-stop"));
    await sendCommand("stop");
    if (mode !== "stop" && statusRef.current.emergency_stop) { setError("请先解除急停"); return false; }
    if (mode === "mapping" && !await perform(() => api.setSpeed(percentToScale(statusRef.current.speed_scale * 100, true)), "")) return false;
    return (await perform(() => api.setMode(mode), "模式指令已发送，等待实时状态确认")) !== null;
  }, [api, perform, sendCommand]);
  const setEmergencyStop = useCallback(async (enabled: boolean) => {
    window.dispatchEvent(new Event("robot-control-stop"));
    if (!enabled) {
      if (!await perform(() => api.setMode("stop"), "")) return false;
      await sendCommand("stop");
    }
    return (await perform(() => api.setEmergencyStop(enabled), enabled ? "急停指令已发送" : "已解除急停，保持停止模式")) !== null;
  }, [api, perform, sendCommand]);
  const setSpeed = useCallback(async (percent: number) => {
    const scale = percentToScale(percent, statusRef.current.mode === "mapping");
    return (await perform(() => api.setSpeed(scale), `速度比例已设置为 ${Math.round(scale * 100)}%`)) !== null;
  }, [api, perform]);
  const setMotionSettings = useCallback(async (changes: Partial<MotionMappingSettings>) => {
    if (changes.turn_speed !== undefined) {
      window.dispatchEvent(new Event("robot-control-stop"));
      await sendCommand("stop");
    }
    const result = await perform(() => api.setMotionSettings(changes), changes.turn_speed !== undefined
      ? "转弯速度已设置，等待实时状态确认" : "建图距离已保存，下次开始建图生效");
    if (result) updateStatus({ ...statusRef.current, motion_settings: result.settings });
    return result !== null;
  }, [api, perform, sendCommand, updateStatus]);
  const setModeObstacleStopDistance = useCallback(async (mode: string, distance: number) => {
    if (!validThreshold(distance)) { setError("防撞距离必须为 0–5 米"); return false; }
    return (await perform(() => api.setModeObstacleStopDistance(mode, distance), `防撞距离已设置为 ${distance.toFixed(2)} m`)) !== null;
  }, [api, perform]);
  const restartMapping = useCallback(async () => {
    window.dispatchEvent(new Event("robot-control-stop"));
    const s = statusRef.current;
    if (s.emergency_stop || !s.lidar.ok || !s.odom.ok || !s.tf.ok) { setError("请先解除急停并检查雷达、里程计及 TF"); return false; }
    await sendCommand("stop");
    if (!await perform(() => api.setSpeed(percentToScale(s.speed_scale * 100, true)), "")) return false;
    setSavedMap(null);
    mapGate.current.beginRestart();
    clearMap();
    const result = await perform(() => api.restartMapping(), "建图已启动，静止等待地图初始化");
    mapGate.current.finishRestart(result?.session_id ?? result?.mapping?.session_id ?? null);
    // Resume polling even when restart fails or an older backend has no session ID.
    setMapSessionKey(n => n + 1);
    if (result?.mapping) updateStatus({ ...statusRef.current, mapping: result.mapping });
    if (!result) await perform(() => api.setMode("stop"), "", true);
    return result !== null;
  }, [api, perform, sendCommand, clearMap, updateStatus]);
  const saveMapping = useCallback(async (draft: SlamMapDraft) => {
    if (!getBusinessSession()) { setError("请先登录系统账户，再将地图保存到地图管理"); return false; }
    window.dispatchEvent(new Event("robot-control-stop"));
    await sendCommand("stop");
    const result = await perform(() => businessApi.saveSlamMap({ ...draft, robot_id: LIVE_ROBOT_ID }), "地图已保存，可在地图管理查看和选用");
    if (result) setSavedMap({ ok: true, message: "地图已登记", map_id: result.id, name: result.name,
      yaml_path: String(result.metadata.vehicle_yaml_path || ""), pgm_path: String(result.metadata.vehicle_pgm_path || "") });
    return result !== null;
  }, [perform, sendCommand]);
  return { status, connection, connectionError, error, message, pending: pending > 0, receivedAt, savedMap, mapSnapshot, mapError, mapStale: !!mapSnapshot && (!!mapError || connection !== "connected"), mapSessionKey, initialMapYaw, api, boundRobotId: LIVE_ROBOT_ID, sendCommand, setMode, setEmergencyStop, setSpeed, setMotionSettings, setModeObstacleStopDistance, restartMapping, saveMapping };
}
type RobotStream = ReturnType<typeof useSharedRobot>;
const RobotContext = createContext<RobotStream | null>(null);
export function RobotStreamProvider({ children }: { children: ReactNode }) {
  return createElement(RobotContext.Provider, { value: useSharedRobot() }, children);
}
export function useRobotStream() {
  const robot = useContext(RobotContext);
  if (!robot) throw new Error("RobotStreamProvider is required");
  return robot;
}
