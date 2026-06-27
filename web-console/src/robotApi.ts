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
export type OdomHealth = {
  ok: boolean; message: string; odom_age_sec: number | null; frame_id: string;
  child_frame_id: string; linear_speed: number; angular_speed: number;
};
export type CmdVelStatus = {
  ok: boolean; message: string; age_sec: number | null;
  linear_x: number; linear_y: number; angular_z: number; updated_at: number | null;
};
export type TfHealth = {
  ok: boolean; message: string; checked_at: number | null; parent_frame: string; child_frame: string;
};
export type MappingQuality = {
  ok: boolean; level: "good" | "warn" | "bad"; message: string; issues: string[];
};
export type MapPose = {
  ok: boolean; message: string; x: number; y: number; yaw: number;
  frame_id: string; child_frame_id: string; updated_at: number | null;
};
export type MapSnapshot = {
  header: { frame_id: string; stamp: { sec: number; nanosec: number } };
  info: { width: number; height: number; resolution: number; origin: { x: number; y: number; yaw: number } };
  data: number[];
  updated_at: number;
};
export type MappingRestartResult = { ok: boolean; pid: number; message: string };
export type MappingSaveResult = { ok: boolean; message: string; yaml_path: string; pgm_path: string };
export type ColorConfig = { name: string; hsv_low: [number, number, number]; hsv_high: [number, number, number] };
export type ColorTarget = { visible?: boolean; offset?: number; area?: number; raw?: string };
export type RobotStatus = {
  mode: string; emergency_stop: boolean; front_distance: number | null; detection: string;
  color_target: ColorTarget | null; camera: { ok: boolean | null; message: string };
  nodes: Record<string, string>; last_command: string; speed_scale: number;
  color_config: ColorConfig; updated_at: number; lane_offset: number; radar_points: RadarPoint[];
  lidar: LidarHealth;
  map: MapHealth;
  odom: OdomHealth;
  cmd_vel: CmdVelStatus;
  tf: TfHealth;
  map_pose: MapPose;
  mapping_quality: MappingQuality;
};
export const initialRobotStatus: RobotStatus = {
  mode: "stop", emergency_stop: false, front_distance: null, detection: "", color_target: null,
  camera: { ok: null, message: "等待视频" }, nodes: {}, last_command: "stop", speed_scale: 1,
  color_config: { name: "green", hsv_low: [35, 60, 60], hsv_high: [90, 255, 255] },
  updated_at: 0, lane_offset: 0, radar_points: [],
  lidar: { ok: false, message: "no_data", scan_age_sec: null, scan_rate_hz: 0, valid_count: 0, valid_ratio: 0, frame_id: "" },
  map: { ok: false, message: "no_map", map_age_sec: null, width: 0, height: 0, resolution: 0, frame_id: "" },
  odom: { ok: false, message: "no_odom", odom_age_sec: null, frame_id: "", child_frame_id: "", linear_speed: 0, angular_speed: 0 },
  cmd_vel: { ok: false, message: "no_cmd_vel", age_sec: null, linear_x: 0, linear_y: 0, angular_z: 0, updated_at: null },
  tf: { ok: false, message: "unavailable", checked_at: null, parent_frame: "odom", child_frame: "base_link" },
  map_pose: { ok: false, message: "unavailable", x: 0, y: 0, yaw: 0, frame_id: "map", child_frame_id: "base_link", updated_at: null },
  mapping_quality: { ok: false, level: "bad", message: "lidar,map,odom,tf", issues: ["lidar", "map", "odom", "tf"] }
};

export function normalizeRobotStatus(snapshot: Partial<RobotStatus>): RobotStatus {
  return {
    ...initialRobotStatus,
    ...snapshot,
    camera: { ...initialRobotStatus.camera, ...snapshot.camera },
    color_config: { ...initialRobotStatus.color_config, ...snapshot.color_config },
    lidar: { ...initialRobotStatus.lidar, ...snapshot.lidar },
    map: { ...initialRobotStatus.map, ...snapshot.map },
    odom: { ...initialRobotStatus.odom, ...snapshot.odom },
    cmd_vel: { ...initialRobotStatus.cmd_vel, ...snapshot.cmd_vel },
    tf: { ...initialRobotStatus.tf, ...snapshot.tf },
    map_pose: { ...initialRobotStatus.map_pose, ...snapshot.map_pose },
    mapping_quality: { ...initialRobotStatus.mapping_quality, ...snapshot.mapping_quality },
    nodes: { ...initialRobotStatus.nodes, ...snapshot.nodes },
    lane_offset: snapshot.lane_offset ?? initialRobotStatus.lane_offset,
    radar_points: snapshot.radar_points ?? initialRobotStatus.radar_points,
  };
}

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
    saveMapping: () => post<MappingSaveResult>("/api/mapping/save", {}),
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
