export type BusinessUser = { id: string; username: string; display_name: string; role: { name: string; permissions: Array<{ name: string }> } | null };
export type SafetyCorridor = { id: string; name: string; map_key: string; polygon: number[][]; axis_yaw: number; required_free_width_m: number };
export type BusinessSession = { access_token: string; refresh_token: string; user: BusinessUser };
export type ManagedMap = { id: string; name: string; floor: string; description: string; width: number; height: number; resolution?: number; origin?: number[]; active: boolean; image_url: string | null; image_key?: string | null; created_at: string; updated_at: string | null; metadata: Record<string, unknown> };
export type SlamMapDraft = { request_id: string; name: string; floor: string; description: string };
export type MapEdit = { type: "despeckle"; max_cells: number } | { type: "wall"; start: { x: number; y: number }; end: { x: number; y: number }; width_m: number }
  | { type: "paint" | "keepout" | "candidate"; shape: "brush" | "line" | "rectangle" | "cells"; points: {x:number;y:number}[]; value: -1|0|100; width_m?:number; filled?:boolean; max_cells?:number };
export type MapPreview = { preview_url:string; changed_cells:number; changed_area_m2:number; digest:string; diff_url:string; keepout_url:string|null; effective_keepout_url:string|null; radius_m:number };
export type CleanupCandidate = {id:string; cells:number[][]; area_m2:number};
export type RosMapPair = {filename:string; yaml:string; pgm_base64:string};
export type MapOptimization = { request_id: string; name: string; operations: MapEdit[] };
export function createMapRequestId() {
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,value=>value.toString(16).padStart(2,"0")).join("");
  return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;
}
export type MapPlace = { id: string; map_id: string; name: string; x: number; y: number; yaw: number };
export type PlaceInput = Pick<MapPlace, "name" | "x" | "y" | "yaw">;
export type ManagedRoute = { id: string; name: string; map_id: string | null; waypoints: unknown[]; points: unknown[]; created_at?: string; updated_at?: string | null };
export type BusinessIncident = { id: string; title: string; type: string; severity: string; status: string; description: string; location: string; robot_id: string | null; occurred_at: string | null; created_at: string | null; handled_at: string | null; resolved_at: string | null; handle_result: string; resolution_note: string; image_url: string | null; media_keys?: string[]; evidence?: Record<string, unknown> };
export type ManagedRobot = { id: string; name: string; robot_code: string; status: string };
export type TaskInput = { name: string; description: string; robot_id: string | null; map_id: string | null; route_id: string | null };
export type PatrolTaskInput = TaskInput & { target_area: string; priority: "low" | "normal" | "high" | "urgent" };
export type MissionTaskInput = TaskInput & { cargo_name: string; start_location: string; end_location: string; pickup_code: string };
export type BusinessTask = { execution?: import("../robotApi").NavigationTaskState | null; id: string; name: string; status: string; progress: number | null; robot_id: string | null; route_id: string | null; map_id?: string | null; created_at: string | null; updated_at: string | null; description: string; target_area?: string; priority?: string; cargo_name?: string; start_location?: string; end_location?: string; pickup_code?: string };
export type AccountRecord = { id: string; username: string; display_name: string; active: boolean; roles: string[] };
export type RoleRecord = { id: string; name: string; description: string; permissions: Array<{ name: string }> };
export type NotificationRecord = { id: string; kind: string; title: string; body: string; ref_id: string | null; read: boolean; created_at: string | null };
export type AuditRecord = { id: string; user_id: string | null; action: string; resource: string; resource_id: string | null; created_at: string | null };

const SESSION_KEY = "insightrover.business-session";
const listeners = new Set<() => void>();
function readSession(): BusinessSession | null {
  try {
    const raw = typeof window !== "undefined" ? window.localStorage.getItem(SESSION_KEY) : null;
    const value = raw ? JSON.parse(raw) : null;
    return value?.access_token && value?.refresh_token && value?.user ? value : null;
  } catch { return null; }
}
let session = readSession();
export function getBusinessSession() { return session; }
export function subscribeBusinessSession(callback: () => void) { listeners.add(callback); return () => { listeners.delete(callback); }; }
function setSession(next: BusinessSession | null) {
  session = next;
  if (typeof window !== "undefined") {
    if (next) window.localStorage.setItem(SESSION_KEY, JSON.stringify(next));
    else window.localStorage.removeItem(SESSION_KEY);
  }
  listeners.forEach(callback => callback());
}
export function clearBusinessSession() { setSession(null); }
if (typeof window !== "undefined") window.addEventListener("storage", event => {
  if (event.key === SESSION_KEY) { session = readSession(); listeners.forEach(callback => callback()); }
});

async function responseError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => ({}));
  const detail = body.detail;
  const message = typeof detail === "string" ? detail : detail?.message || (Array.isArray(detail) ? "输入内容有误，请检查所填内容" : `请求失败（${response.status}）`);
  return new Error(message);
}
let refreshing: Promise<void> | null = null;
async function refreshSession() {
  if (!refreshing) refreshing = (async () => {
    const previous = session;
    if (!previous) throw new Error("请先登录系统账户");
    const response = await fetch("/api/v1/auth/refresh", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: previous.refresh_token }) });
    if (!response.ok) { if (response.status === 401 && session === previous) clearBusinessSession(); throw await responseError(response); }
    const next = await response.json() as BusinessSession;
    if (session === previous) setSession(next);
  })().finally(() => { refreshing = null; });
  return refreshing;
}
async function request(path: string, options: RequestInit = {}): Promise<Response> {
  if (!session) throw new Error("请先登录系统账户");
  const send = () => fetch(`/api/v1${path}`, { ...options, headers: { ...options.headers, Authorization: `Bearer ${session?.access_token || ""}` } });
  let response: Response;
  try {
    response = await send();
    if (response.status === 401 && session) { await refreshSession(); response = await send(); }
  } catch (error) {
    if (error instanceof TypeError) throw new Error("无法连接业务服务，请检查后端是否已启动");
    throw error;
  }
  if (!response.ok) { if (response.status === 401) clearBusinessSession(); throw await responseError(response); }
  return response;
}
const jsonOptions = (method: string, data: unknown): RequestInit => ({ method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
async function json<T>(path: string, options?: RequestInit): Promise<T> { return (await request(path, options)).json(); }
const mapPath = (id: string) => `/maps/${encodeURIComponent(id)}`;

export const businessApi = {
  async login(username: string, password: string) {
    let response: Response;
    try { response = await fetch("/api/v1/auth/login", jsonOptions("POST", { username, password })); }
    catch { throw new Error("无法连接业务服务，请检查后端是否已启动"); }
    if (!response.ok) throw await responseError(response);
    setSession(await response.json());
  },
  listMaps: () => json<ManagedMap[]>("/maps"),
  saveSlamMap: (data: SlamMapDraft & { robot_id: string }) => json<ManagedMap>("/maps/slam", jsonOptions("POST", data)),
  getMapSelection: () => json<{ map_id: string | null; initialized?: boolean }>("/maps/selection"),
  selectMap: (id: string) => json<{ map_id: string }>(`${mapPath(id)}/select`, jsonOptions("POST", {})),
  async clearMapSelection() { await request("/maps/selection", { method: "DELETE" }); },
  async mapFile(id: string, kind: "yaml" | "pgm" | "grid") { return (await request(`${mapPath(id)}/files/${kind}`)).blob(); },
  getMap: (id: string) => json<ManagedMap>(mapPath(id)),
  previewMapOptimization: (id: string, data: MapOptimization, radius=.25) => json<MapPreview>(`${mapPath(id)}/optimization-preview?radius_m=${radius}`, jsonOptions("POST", data)),
  mapCleanupCandidates: (id:string, operations:MapEdit[],limit:number) => json<{candidates:CleanupCandidate[]}>(`${mapPath(id)}/cleanup-candidates?max_cells=${limit}`,jsonOptions('POST',{operations})),
  importRosMap: (name:string,map:RosMapPair,keepout?:RosMapPair) => json<ManagedMap>('/maps/import-ros',jsonOptions('POST',{name,map,keepout})),
  async exportRosMap(id:string) { return (await request(`${mapPath(id)}/export-ros`)).blob(); },
  deriveMap: (id: string, data: MapOptimization) => json<ManagedMap>(`${mapPath(id)}/derive`, jsonOptions("POST", data)),
  loadNavigationMap: (id: string, control_session_id: string) => json<import("../robotApi").NavigationRuntimeState>(`${mapPath(id)}/load-navigation`, jsonOptions("POST", { control_session_id })),
  createNavigationTask: (data: Record<string, unknown>) => json<import("../robotApi").NavigationTaskState>("/navigation-tasks", jsonOptions("POST", data)),
  getTaskExecution: (kind: string, id: string) => json<import("../robotApi").NavigationTaskState>(`/navigation-tasks/${kind}/${encodeURIComponent(id)}`),
  taskExecutionAction: (kind: string, id: string, run_id: string, action: string) => json<import("../robotApi").NavigationTaskState>(`/navigation-tasks/${kind}/${encodeURIComponent(id)}/action`, jsonOptions("POST", { run_id, action })),
  async uploadMap(file: File, name: string, floor: string, description: string) {
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) throw new Error("请选择 PNG、JPG 或 WebP 图片");
    if (!file.size || file.size > 10 * 1024 * 1024) throw new Error("图片须有内容且不能超过 10 MB");
    const query = new URLSearchParams({ name: name.trim(), floor, description });
    return json<ManagedMap>(`/maps/upload?${query}`, { method: "POST", headers: { "Content-Type": file.type }, body: file });
  },
  updateMap: (id: string, data: Pick<ManagedMap, "name" | "floor" | "description" | "active">) => json<ManagedMap>(mapPath(id), jsonOptions("PUT", data)),
  async deleteMap(id: string) { await request(mapPath(id), { method: "DELETE" }); },
  async image(id: string) { return (await request(`${mapPath(id)}/image`)).blob(); },
  listPlaces: (id: string) => json<MapPlace[]>(`${mapPath(id)}/places`),
  savePlace: (id: string, place: PlaceInput, placeId?: string) => json<MapPlace>(`${mapPath(id)}/places${placeId ? `/${encodeURIComponent(placeId)}` : ""}`, jsonOptions(placeId ? "PUT" : "POST", place)),
  async deletePlace(id: string, placeId: string) { await request(`${mapPath(id)}/places/${encodeURIComponent(placeId)}`, { method: "DELETE" }); },
  listRoutes: (mapId?: string) => json<ManagedRoute[]>(`/routes${mapId ? `?map_id=${encodeURIComponent(mapId)}` : ""}`),
  getRoute: (id: string) => json<ManagedRoute>(`/routes/${encodeURIComponent(id)}`),
  listIncidents: () => json<BusinessIncident[]>("/incidents"),
  getIncident: (id: string) => json<BusinessIncident>(`/incidents/${encodeURIComponent(id)}`),
  incidentAction: (id: string, action: string, note = "") => json<BusinessIncident>(`/incidents/${encodeURIComponent(id)}/actions`, jsonOptions("POST", { action, note })),
  async incidentImage(key: string) { return (await request(`/media/object/${key.split('/').map(encodeURIComponent).join('/')}`)).blob(); },
  safetyStatus: () => json<{state: string; message: string; capabilities?: Record<string, boolean>; configured_corridors?: number; models?: Array<{path: string; validation: string}>; inference_ms?: number; ingest?: {state: string; message: string}}>("/incidents/safety/status"),
  safetyCorridors: () => json<{corridors: SafetyCorridor[]}>("/incidents/safety/corridors"),
  saveSafetyCorridors: (value: Record<string, unknown>) => json<{corridors: SafetyCorridor[]}>("/incidents/safety/corridors", jsonOptions('POST', value)),
  listPatrolTasks: () => json<BusinessTask[]>("/patrol-tasks"),
  listMissionTasks: () => json<BusinessTask[]>("/mission-tasks"),
  createPatrolTask: (data: PatrolTaskInput) => json<BusinessTask>("/patrol-tasks", jsonOptions("POST", data)),
  createMissionTask: (data: MissionTaskInput) => json<BusinessTask>("/mission-tasks", jsonOptions("POST", data)),
  listRobots: () => json<ManagedRobot[]>("/robots"),
  listUsers: () => json<AccountRecord[]>("/users"),
  listRoles: () => json<RoleRecord[]>("/roles"),
  listNotifications: () => json<NotificationRecord[]>("/notifications"),
  markNotificationRead: (id: string) => json<NotificationRecord>(`/notifications/${encodeURIComponent(id)}/read`, jsonOptions("POST", { read: true })),
  listAuditLogs: () => json<AuditRecord[]>("/audit-logs"),
  analyticsSummary: () => json<{ patrol: { total: number; completed: number }; mission: { total: number; completed: number }; incident: { total: number; unresolved: number } }>("/analytics/summary"),
};

export function imagePoint(x: number, y: number, width: number, height: number) {
  if (![x, y, width, height].every(Number.isFinite) || x < 0 || y < 0 || x >= width || y >= height) return null;
  // Preserve the exclusive upper bound even when rounding near the image edge.
  return { x: Math.min(width - 0.001, Math.round(x * 1000) / 1000), y: Math.min(height - 0.001, Math.round(y * 1000) / 1000) };
}
