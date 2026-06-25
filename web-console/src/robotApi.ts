export type ConnectionState = "connecting" | "connected" | "disconnected";
export type RadarPoint = { x: number; y: number; distance: number };
export type LidarHealth = {
  ok: boolean; message: string; scan_age_sec: number | null; scan_rate_hz: number;
  valid_count: number; valid_ratio: number; frame_id: string;
};
export type MapHealth = {
  ok: boolean; message: string; map_age_sec: number | null; width: number;
  height: number; resolution: number; frame_id: string;
};
export type MapSnapshot = {
  header: { frame_id: string; stamp: { sec: number; nanosec: number } };
  info: { width: number; height: number; resolution: number; origin: { x: number; y: number; yaw: number } };
  data: number[];
  updated_at: number;
};
export type MappingRestartResult = { ok: boolean; pid: number; message: string };
export type ColorConfig = { name: string; hsv_low: [number, number, number]; hsv_high: [number, number, number] };
export type ColorTarget = { visible?: boolean; offset?: number; area?: number; raw?: string };
export type RobotStatus = {
  mode: string; emergency_stop: boolean; front_distance: number | null; detection: string;
  color_target: ColorTarget | null; camera: { ok: boolean | null; message: string };
  nodes: Record<string, string>; last_command: string; speed_scale: number;
  color_config: ColorConfig; updated_at: number; lane_offset: number; radar_points: RadarPoint[];
  lidar: LidarHealth;
  map: MapHealth;
};
export const initialRobotStatus: RobotStatus = {
  mode: "stop", emergency_stop: false, front_distance: null, detection: "", color_target: null,
  camera: { ok: null, message: "等待视频" }, nodes: {}, last_command: "stop", speed_scale: 1,
  color_config: { name: "green", hsv_low: [35, 60, 60], hsv_high: [90, 255, 255] },
  updated_at: 0, lane_offset: 0, radar_points: [],
  lidar: { ok: false, message: "no_data", scan_age_sec: null, scan_rate_hz: 0, valid_count: 0, valid_ratio: 0, frame_id: "" },
  map: { ok: false, message: "no_map", map_age_sec: null, width: 0, height: 0, resolution: 0, frame_id: "" }
};
type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { message = ((await response.json()) as { detail?: string }).detail ?? message; } catch { /* non-JSON error */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}
export function createRobotApi(fetchImpl: FetchLike = fetch) {
  const post = <T>(url: string, body: unknown) => fetchImpl(url, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body)
  }).then((response) => readJson<T>(response));
  return {
    getStatus: () => fetchImpl("/api/status", { cache: "no-store" }).then((response) => readJson<RobotStatus>(response)),
    getMap: () => fetchImpl("/api/map", { cache: "no-store" }).then((response) => readJson<MapSnapshot>(response)),
    restartMapping: () => post<MappingRestartResult>("/api/mapping/restart", {}),
    setMode: (mode: string) => post<{ mode: string }>("/api/mode", { mode }),
    sendCommand: (command: string) => post<{ command: string }>("/api/command", { command }),
    setEmergencyStop: (enabled: boolean) => post<{ emergency_stop: boolean }>("/api/emergency-stop", { enabled }),
    setSpeed: (scale: number) => post<{ speed_scale: number }>("/api/speed", { scale }),
    setColorConfig: (config: ColorConfig) => post<{ color_config: ColorConfig }>("/api/color-target", config)
  };
}
export function statusSocketUrl(location: Pick<Location, "protocol" | "host">) {
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/status`;
}
