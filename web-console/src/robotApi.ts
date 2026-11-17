import type { CalibrationPair, NavigationConfig, NavigationPlan, NavigationState, Point, Pose } from "./labNavigation";
import { vehicleControlRequest } from "./services/businessApi";
export type ConnectionState = "connecting" | "connected" | "disconnected";
export type RadarPoint = { x: number; y: number; distance: number };
export type AvoidanceSettings = { enabled: boolean; trigger_distance_m: number; protection_mode?: "basic" | "full" };
export type VisionStatus = { supported: boolean; state: string; message: string; mobile_ready: boolean; inference_ms?: number; frame_age_ms?: number; detections: {label:string;confidence:number;passage?:string}[] };
export type SearchStatus = { state:string; message:string; run_id:string|null; travel?: "stationary" | "patrol"; evidence?:{save_error?:string;event_id:string} };
type SearchCapability = {executable:boolean; reasons:string[]};
export type VisionSettings = {enabled:boolean;clutter_enabled:boolean;clutter_prompts:string[];imgsz:number};
export type AvoidanceStatus = {
  supported: boolean; confirmed: boolean; available: boolean;
  sensors_ready?: boolean;
  protection_supported?: boolean; protection_protocol?: number; motion_epoch?: string; command_valid_until?: number;
  config_rejection?: string | null;
  recovery_required?: boolean; interruption_reason?: string | null; scan_fault?: string | null;
  velocity?: {ok: boolean; age_sec: number | null; linear_speed_xy: number | null; angular_speed: number | null};
  output?: {allowed: boolean; reasons: string[]; requested?: number[]; applied?: number[]; recovery?: string};
  settings: AvoidanceSettings; requested?: AvoidanceSettings | null;
  state: string; reason: string; direction?: "left" | "right" | null;
  front_clearance_m?: number | null; instance_id?: string;
  build_id?: string;
  scan_health?: {valid_ratio?:number;scan_rate_hz?:number|null;consecutive_healthy?:number};
  sampling_gap_inferred?: {rays:number;distance_cap_min_m:number;distance_cap_max_m:number}|null;
  missing_data_policy?: {mode:string;active?:boolean;device_proven?:boolean};
  assumed_clear?: {kind:string;rays:number;distance_cap_m?:number;device_proven:boolean}|null;
  blocking_point_m?: [number, number] | null;
  coverage?: { kind: string; motion?: string };
  last_stop_event?: { state: string; reason: string; timestamp?: number; mode?: string } | null;
};
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
  child_frame_id: string; linear_speed: number; linear_speed_xy?: number; angular_speed: number;
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
  map_session_id?: string | null; asset_digest?: string | null;
  ok: boolean; message: string; x: number; y: number; yaw: number;
  frame_id: string; child_frame_id: string; updated_at: number | null;
  age_sec?: number | null;
};
export type MapSnapshot = {
  asset_digest?: string;
  session_id?: string | null;
  revision?: number;
  header: { frame_id: string; stamp: { sec: number; nanosec: number } };
  info: { width: number; height: number; resolution: number; origin: { x: number; y: number; yaw: number } };
  data: number[];
  updated_at: number;
};
export type MotionMappingSettings = { turn_speed: number; max_laser_range: number };
export type MappingState = { session_id: string | null; state: "idle" | "starting" | "waiting_map" | "ready" | "error"; started_at: number | null; error: string | null; max_laser_range?: number; configured_max_laser_range?: number };
export type MappingRestartResult = { ok: boolean; pid: number; message: string; session_id?: string | null; mapping?: MappingState };
export type MappingSaveResult = { ok: boolean; message: string; yaml_path: string; pgm_path: string; map_id?: string; name?: string };
export type ColorConfig = { name: string; hsv_low: [number, number, number]; hsv_high: [number, number, number] };
export type ColorTarget = { visible?: boolean; found?: boolean; offset?: number; area?: number; bounding_box?: [number, number, number, number] | null; raw?: string };
export type RobotStatus = {
  network?: "connected" | "stale" | "disconnected" | "unknown";
  ros2_status_age_sec?: number | null;
  battery?: number | null;
  mode: string; emergency_stop: boolean; front_distance: number | null; detection: string;
  motion_settings?: MotionMappingSettings;
  avoidance?: AvoidanceStatus;
  manual_turn_speed?: number;
  mode_obstacle_stop_distances: Record<string, number>;
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
  mapping: MappingState;
  navigation: NavigationState;
};
export const initialRobotStatus: RobotStatus = {
  mode: "stop", emergency_stop: false, front_distance: null, detection: "", network: "unknown", battery: null,
  mode_obstacle_stop_distances: { stop: 0, manual: 0, auto: 0.45, mapping: 0, navigation: 0.45, color_track: 0.45, object_follow: 0.45 },
  color_target: null,
  camera: { ok: null, message: "等待视频" }, nodes: {}, last_command: "stop", speed_scale: 1,
  color_config: { name: "green", hsv_low: [35, 60, 60], hsv_high: [90, 255, 255] },
  updated_at: 0, lane_offset: 0, radar_points: [],
  lidar: { ok: false, message: "no_data", scan_age_sec: null, scan_rate_hz: 0, valid_count: 0, valid_ratio: 0, frame_id: "" },
  map: { ok: false, message: "no_map", map_age_sec: null, width: 0, height: 0, resolution: 0, frame_id: "" },
  odom: { ok: false, message: "no_odom", odom_age_sec: null, frame_id: "", child_frame_id: "", linear_speed: 0, angular_speed: 0 },
  cmd_vel: { ok: false, message: "no_cmd_vel", age_sec: null, linear_x: 0, linear_y: 0, angular_z: 0, updated_at: null },
  tf: { ok: false, message: "unavailable", checked_at: null, parent_frame: "odom", child_frame: "base_link" },
  map_pose: { ok: false, message: "unavailable", x: 0, y: 0, yaw: 0, frame_id: "map", child_frame_id: "base_link", updated_at: null },
  mapping_quality: { ok: false, level: "bad", message: "lidar,map,odom,tf", issues: ["lidar", "map", "odom", "tf"] },
  mapping: { session_id: null, state: "idle", started_at: null, error: null },
  navigation: { ready: false, state: "idle", message: "等待车端导航服务", goal_id: null, goal: null, path: [], distance_remaining: null, estimated_time_remaining: null },
};

export function normalizeRobotStatus(snapshot: Partial<RobotStatus>): RobotStatus {
  return {
    ...initialRobotStatus,
    ...snapshot,
    camera: { ...initialRobotStatus.camera, ...snapshot.camera },
    color_config: { ...initialRobotStatus.color_config, ...snapshot.color_config },
    mode_obstacle_stop_distances: { ...initialRobotStatus.mode_obstacle_stop_distances, ...snapshot.mode_obstacle_stop_distances },
    lidar: { ...initialRobotStatus.lidar, ...snapshot.lidar },
    map: { ...initialRobotStatus.map, ...snapshot.map },
    odom: { ...initialRobotStatus.odom, ...snapshot.odom },
    cmd_vel: { ...initialRobotStatus.cmd_vel, ...snapshot.cmd_vel },
    tf: { ...initialRobotStatus.tf, ...snapshot.tf },
    map_pose: { ...initialRobotStatus.map_pose, ...snapshot.map_pose },
    mapping_quality: { ...initialRobotStatus.mapping_quality, ...snapshot.mapping_quality },
    mapping: { ...initialRobotStatus.mapping, ...snapshot.mapping },
    navigation: { ...initialRobotStatus.navigation, ...snapshot.navigation },
    nodes: { ...initialRobotStatus.nodes, ...snapshot.nodes },
    lane_offset: snapshot.lane_offset ?? initialRobotStatus.lane_offset,
    radar_points: snapshot.radar_points ?? initialRobotStatus.radar_points,
  };
}

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
export type NavigationRuntimeState = { state: string; message: string; map_id: string | null; digest: string | null; localized: boolean; pose_at?: number | null; control_session_id?: string };
export type NavigationTaskState = { state: string; message: string; run_id?: string; task_id?: string; kind?: "delivery" | "patrol"; goals?: Pose[]; completed_stops?: number; index?: number; returning?: boolean; return_to_start?: boolean; updated_at?: number; version?: number; total_stops?: number; cycles?: number; distance_m?: number; elapsed_sec?: number; dwell_remaining_sec?: number; acceptance_met?: boolean };
async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { const value = await response.json(); message = value.detail ?? value.message ?? message; } catch { /* non-JSON error */ }
    throw new Error(message);
  }
  const value = await response.json();
  if (value?.ok === false) throw new Error(value.message ?? "车端未接受操作");
  return value as T;
}
export function createRobotApi(fetchImpl: FetchLike = fetch) {
  if (fetchImpl === fetch) {
    fetchImpl = (url, options) => vehicleControlRequest(String(url), options ?? {});
  }
  const post = <T>(url: string, body: unknown, timeout = 5000) => fetchImpl(url, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body), signal: AbortSignal.timeout(timeout)
  }).then((response) => readJson<T>(response));
  let drive: { id: string; sequence: number } | null = null;
  let driveGeneration = 0;
  const clientId = typeof globalThis.crypto?.randomUUID === 'function' ? globalThis.crypto.randomUUID()
    : `driver-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  const selectDrive = async <T extends { drive_id?: string; drive_seq_floor?: number }>(url: string, body: unknown, timeout: number) => {
    const generation = ++driveGeneration;
    const previousDrive = drive;
    drive = null;
    const result = await post<T>(url, body, timeout);
    if (generation === driveGeneration && result.drive_id) {
      drive = { id: result.drive_id, sequence: Math.max(result.drive_seq_floor ?? 0, previousDrive?.id === result.drive_id ? previousDrive.sequence : 0) };
    }
    return result;
  };
  return {
    getVision: () => fetchImpl('/api/vision/status', {cache:'no-store',signal:AbortSignal.timeout(5000)}).then(r=>readJson<VisionStatus>(r)),
    getVisionSettings: () => fetchImpl('/api/vision/settings', {cache:'no-store',signal:AbortSignal.timeout(5000)}).then(r=>readJson<VisionSettings>(r)),
    setVisionSettings: (value:Partial<VisionSettings>) => post<VisionSettings>('/api/vision/settings',value),
    getSearch: () => fetchImpl('/api/search', {cache:'no-store',signal:AbortSignal.timeout(5000)}).then(r=>readJson<SearchStatus>(r)),
    getSearchCapabilities: () => fetchImpl('/api/search/capabilities', {cache:'no-store',signal:AbortSignal.timeout(5000)})
      .then(r=>readJson<{observe_target:SearchCapability; patrol_search:SearchCapability}>(r)),
    startSearch: (value:unknown) => post<SearchStatus>('/api/search/start',value,30000),
    searchAction: (run_id:string,action:string) => post<SearchStatus>('/api/search/action',{run_id,action}),
    getAvoidance: () => fetchImpl('/api/avoidance', { cache: 'no-store', signal: AbortSignal.timeout(5000) }).then(r => readJson<AvoidanceStatus>(r)),
    setAvoidance: (changes: Partial<AvoidanceSettings> | {acknowledge: string}) => post<AvoidanceStatus>('/api/avoidance', changes),
    getNavigationRuntime: () => fetchImpl("/api/navigation/runtime", { cache: "no-store", signal: AbortSignal.timeout(5000) }).then(r => readJson<NavigationRuntimeState>(r)),
    getNavigationCapability: () => fetchImpl("/api/navigation/capabilities", { cache: "no-store", signal: AbortSignal.timeout(5000) })
      .then(r => readJson<{navigate: SearchCapability}>(r)).then(value => value.navigate),
    setInitialPose: (pose: Pose, asset_digest: string) => post<NavigationRuntimeState>("/api/navigation/initial-pose", { ...pose, asset_digest }),
    getNavigationTask: () => fetchImpl("/api/navigation/task", { cache: "no-store", signal: AbortSignal.timeout(5000) }).then(r => readJson<NavigationTaskState>(r)),
    getNavigationConfig: () => fetchImpl("/api/navigation/config", { cache: "no-store", signal: AbortSignal.timeout(5000) }).then(r => readJson<NavigationConfig>(r)),
    calibrateNavigation: (anchors: CalibrationPair[], map_key: string, drawing?: import("./labNavigation").DrawingDescriptor) => post<NavigationConfig>("/api/navigation/calibration", { anchors, map_key, ...(drawing ? { drawing } : {}) }),
    addNavigationPlace: (name: string, drawing: Point, yaw: number, context?: { map_key: string; calibration_matrix: number[]; calibration_drawing: import("./labNavigation").DrawingDescriptor }) => post<NavigationConfig>("/api/navigation/places", { name, drawing, yaw, ...context }),
    removeNavigationPlace: (id: string) => fetchImpl(`/api/navigation/places/${encodeURIComponent(id)}`, { method: "DELETE", signal: AbortSignal.timeout(5000) }).then(r => readJson<NavigationConfig>(r)),
    planNavigation: (goal: Pose, map_key: string, calibration_matrix: number[], drawing?: import("./labNavigation").DrawingDescriptor) => post<NavigationPlan>("/api/navigation/plan", { goal, map_key, calibration_matrix, ...(drawing ? { calibration_drawing: drawing } : {}) }, 45000),
    startNavigation: (plan_id: string) => post<{ ok: boolean; goal_id: string }>("/api/navigation/start", { plan_id }, 45000),
    cancelNavigation: () => post<{ ok: boolean }>("/api/navigation/cancel", {}),
    getStatus: () => fetchImpl("/api/status", { cache: "no-store", signal: AbortSignal.timeout(5000) }).then((response) => readJson<RobotStatus>(response)),
    getMap: (signal?: AbortSignal) => fetchImpl("/api/map", { cache: "no-store", signal: signal ?? AbortSignal.timeout(5000) }).then((response) => readJson<MapSnapshot>(response)),
    restartMapping: () => selectDrive<MappingRestartResult & { drive_id?: string }>("/api/mapping/restart", {}, 50000),
    setMotionSettings: (changes: Partial<MotionMappingSettings>) => post<{ok: boolean; settings: MotionMappingSettings}>("/api/mapping/settings", changes),
    saveMapping: () => post<MappingSaveResult>("/api/mapping/save", {}),
    setMode: (mode: string) => selectDrive<{ mode: string; drive_id?: string }>("/api/mode", mode === "stop" ? {mode} : {mode, client_id: clientId}, 10000),
    sendCommand: async (command: string) => {
      if (drive) {
        return post<{ command: string }>("/api/command", { command, drive_id: drive.id, drive_seq: ++drive.sequence });
      }
      if (command !== "stop") throw new Error("请先选择手动驾驶或开始建图");
      return post<{ command: string }>("/api/command", { command });
    },
    setEmergencyStop: (enabled: boolean) => {
      if (enabled) { ++driveGeneration; drive = null; }
      return post<{ emergency_stop: boolean }>("/api/emergency-stop", { enabled });
    },
    setSpeed: (scale: number) => post<{ speed_scale: number }>("/api/speed", { scale }),
    setModeObstacleStopDistance: (mode: string, distance: number) => post<{ mode_obstacle_stop_distances: Record<string, number> }>("/api/mode-obstacle-stop-distance", { mode, distance }),
    setColorConfig: (config: ColorConfig) => post<{ color_config: ColorConfig }>("/api/color-target", config)
  };
}
export function statusSocketUrl(location: Pick<Location, "protocol" | "host">) {
  return `${location.protocol === "https:" ? "wss:" : "ws:"}//${location.host}/ws/status`;
}
