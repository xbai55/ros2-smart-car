import type { ActivityItem, AuditEntry, Incident, MapObject, NotificationItem, Robot, RoleItem, RouteInfo, Task, UserItem } from "../types/domain";
import { LIVE_ROBOT_ID } from "../liveControl";
import { businessApi, type BusinessIncident, type ManagedMap } from "./businessApi";

export const formatTime = (value: string | null | undefined) => value ? new Date(value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : value + "Z").toLocaleString("zh-CN") : "未记录";
// The configured physical connection is an identity, not a telemetry snapshot.
const liveRobot: Robot = { id: LIVE_ROBOT_ID, name: "智巡一号", model: "ROSMASTER X3", zone: "未记录区域", health: "offline", mode: "unknown", battery: null, speed: null, frontDistance: null, position: null, heading: null, tasks: null, incidents: null, lastSeen: "等待实车状态" };
function mapDomain(map: ManagedMap): MapObject {
  return { id: map.id, name: map.name, area: map.width && map.height ? `${map.width} × ${map.height} px` : "尚无图片", floors: null, version: null, updatedAt: formatTime(map.updated_at || map.created_at), status: map.active ? "active" : "draft" };
}
function incidentDomain(item: BusinessIncident): Incident {
  const level = item.severity === "critical" || item.severity === "high" ? "critical" : item.severity === "warning" || item.severity === "medium" ? "warning" : "info";
  const aliases: Record<string, Incident["status"]> = { acknowledged: "confirmed", handling: "resolving", processing: "resolving", ignored: "dismissed" };
  return { id: item.id, title: item.title, type: item.type, level, status: aliases[item.status] || item.status as Incident["status"], confidence: null, location: item.location || "未记录", robotName: item.robot_id || "未关联机器人", detectedAt: formatTime(item.occurred_at || item.created_at), description: item.description };
}
async function listTasks(): Promise<Task[]> {
  const [patrols, missions] = await Promise.all([businessApi.listPatrolTasks(), businessApi.listMissionTasks()]);
  return [...patrols.map(item => ({ item, type: "patrol" as const })), ...missions.map(item => ({ item, type: "transport" as const }))].map(({ item, type }) => ({ id: item.id, title: item.name, type, status: item.status as Task["status"], robotId: item.robot_id, robotName: item.robot_id || "未分配", routeName: item.route_id || "未关联路线", progress: item.progress, currentStep: item.description || "未记录说明", createdAt: formatTime(item.created_at), updatedAt: formatTime(item.updated_at) }));
}
async function listRoutes(): Promise<RouteInfo[]> {
  return (await businessApi.listRoutes()).map(item => ({ id: item.id, name: item.name, mapId: item.map_id || "", mapName: item.map_id || "未关联地图", distance: null, waypoints: item.waypoints.length, version: null, updatedAt: formatTime(item.updated_at || item.created_at) }));
}
export const adapters = {
  async listRobots(): Promise<Robot[]> { return [{ ...liveRobot }]; },
  async getRobot(id: string): Promise<Robot | undefined> { return id === LIVE_ROBOT_ID ? { ...liveRobot } : undefined; },
  listTasks,
  async getTask(id: string): Promise<Task | undefined> { return (await listTasks()).find(item => item.id === id); },
  async listIncidents(): Promise<Incident[]> { return (await businessApi.listIncidents()).map(incidentDomain); },
  async getIncident(id: string): Promise<Incident> { return incidentDomain(await businessApi.getIncident(id)); },
  async listMaps(): Promise<MapObject[]> { return (await businessApi.listMaps()).map(mapDomain); },
  async getMap(id: string): Promise<MapObject> { return mapDomain(await businessApi.getMap(id)); },
  listRoutes,
  async getRoute(id: string): Promise<RouteInfo | undefined> { return (await listRoutes()).find(item => item.id === id); },
  async listNotifications(): Promise<NotificationItem[]> { return (await businessApi.listNotifications()).map(n => ({ id: n.id, type: n.kind === "incident" ? "incident" : n.kind === "task" ? "task" : "system", title: n.title, object: n.body, time: formatTime(n.created_at), read: n.read, href: n.kind === "incident" && n.ref_id ? `/incidents/${n.ref_id}` : n.kind === "task" ? "/tasks" : "/settings" })); },
  async listAuditLogs(): Promise<AuditEntry[]> { return (await businessApi.listAuditLogs()).map(a => ({ id: a.id, actor: a.user_id || "系统", action: a.action, object: `${a.resource}${a.resource_id ? ` · ${a.resource_id}` : ""}`, time: formatTime(a.created_at), result: null })); },
  async listUsers(): Promise<UserItem[]> { return (await businessApi.listUsers()).map(u => ({ id: u.id, name: u.display_name || u.username, username: u.username, role: u.roles.join("、") || "未分配", status: u.active ? "active" : "inactive", lastLogin: "未采集" })); },
  async listRoles(): Promise<RoleItem[]> { return (await businessApi.listRoles()).map(r => ({ id: r.id, name: r.name, description: r.description, users: null, permissions: r.permissions.map(p => p.name) })); },
  async listActivity(): Promise<ActivityItem[]> { return (await businessApi.listAuditLogs()).slice(0, 5).map(a => ({ id: a.id, kind: "system", text: `${a.action} · ${a.resource}`, time: formatTime(a.created_at), href: "/settings" })); },
};
