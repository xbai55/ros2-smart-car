import type {
  ActivityItem,
  AssetItem,
  AuditEntry,
  Incident,
  MapObject,
  NotificationItem,
  Robot,
  RoleItem,
  RouteInfo,
  Task,
  UserItem,
} from "../types/domain";

const delay = (ms = 360) => new Promise<void>((resolve) => setTimeout(resolve, ms));

const robots: Robot[] = [
  { id: "r-001", name: "智巡一号", model: "ROSMASTER X3", zone: "A 区 · 化学实验室", health: "online", mode: "patrol", battery: 82, speed: 35, frontDistance: 1.24, position: { x: 38, y: 54 }, heading: 42, tasks: 3, incidents: 1, lastSeen: "刚刚" },
  { id: "r-002", name: "智巡二号", model: "ROSMASTER X3", zone: "B 区 · 物理实验室", health: "online", mode: "transport", battery: 64, speed: 55, frontDistance: 0.86, position: { x: 62, y: 31 }, heading: 128, tasks: 2, incidents: 0, lastSeen: "刚刚" },
  { id: "r-003", name: "智巡三号", model: "ROSMASTER X3", zone: "C 区 · 机房", health: "degraded", mode: "stop", battery: 21, speed: 0, frontDistance: null, position: { x: 20, y: 78 }, heading: 260, tasks: 0, incidents: 2, lastSeen: "2 分钟前" },
  { id: "r-004", name: "智巡四号", model: "ROSMASTER X3", zone: "D 区 · 公共走廊", health: "charging", mode: "stop", battery: 97, speed: 0, frontDistance: null, position: { x: 74, y: 66 }, heading: 0, tasks: 0, incidents: 0, lastSeen: "1 分钟前" },
  { id: "r-005", name: "智巡五号", model: "ROSMASTER X3", zone: "仓库 · 待命", health: "offline", mode: "stop", battery: 0, speed: 0, frontDistance: null, position: { x: 8, y: 12 }, heading: 0, tasks: 0, incidents: 0, lastSeen: "3 小时前" },
];

const tasks: Task[] = [
  { id: "t-101", title: "A 区实验室例行巡检", type: "patrol", status: "running", robotId: "r-001", robotName: "智巡一号", routeName: "A 区巡检路线 v3", progress: 62, currentStep: "化学实验室 · 通风柜检查", createdAt: "今天 14:20", updatedAt: "刚刚", transportStage: undefined },
  { id: "t-102", title: "文件运输：报告送往行政楼", type: "transport", status: "running", robotId: "r-002", robotName: "智巡二号", routeName: "实验楼 → 行政楼", progress: 45, currentStep: "运输中 · 途经物理实验室", createdAt: "今天 14:05", updatedAt: "2 分钟前", transportStage: "transit" },
  { id: "t-103", title: "B 区消防通道巡检", type: "patrol", status: "pending", robotId: null, robotName: "待分配", routeName: "B 区巡检路线 v2", progress: 0, currentStep: "等待调度", createdAt: "今天 13:50", updatedAt: "今天 13:50", transportStage: undefined },
  { id: "t-104", title: "文件运输：试剂清单到仓库", type: "transport", status: "paused", robotId: "r-001", robotName: "智巡一号", routeName: "实验室 → 仓库", progress: 71, currentStep: "等待取件确认", createdAt: "今天 11:30", updatedAt: "18 分钟前", transportStage: "loading" },
  { id: "t-105", title: "C 区机房温湿度巡检", type: "patrol", status: "completed", robotId: "r-003", robotName: "智巡三号", routeName: "C 区巡检路线 v1", progress: 100, currentStep: "已完成", createdAt: "昨天 18:40", updatedAt: "昨天 19:02", transportStage: undefined },
  { id: "t-106", title: "文件运输：试卷送教务处", type: "transport", status: "completed", robotId: "r-002", robotName: "智巡二号", routeName: "实验楼 → 教务处", progress: 100, currentStep: "已完成", createdAt: "昨天 16:10", updatedAt: "昨天 16:32", transportStage: "done" },
  { id: "t-107", title: "D 区走廊夜间巡检", type: "patrol", status: "failed", robotId: "r-004", robotName: "智巡四号", routeName: "D 区巡检路线 v2", progress: 33, currentStep: "异常中止：LiDAR 遮挡", createdAt: "昨天 22:00", updatedAt: "昨天 22:08", transportStage: undefined },
];

const incidents: Incident[] = [
  { id: "i-301", title: "检测到未佩戴护目镜人员", type: "AI 检测 · 人员安全", level: "critical", status: "open", confidence: 96, location: "A 区 · 化学实验室", robotName: "智巡一号", detectedAt: "刚刚", description: "YOLO 检测到实验区内人员未佩戴护目镜，已留存现场画面并触发告警。" },
  { id: "i-302", title: "检测到烟雾/高温异常", type: "AI 检测 · 火灾风险", level: "critical", status: "confirmed", confidence: 88, location: "C 区 · 机房", robotName: "智巡三号", detectedAt: "4 分钟前", description: "热成像区域温度超过阈值，疑似设备过热，已通知机房管理员。" },
  { id: "i-303", title: "紧急出口被杂物占用", type: "通道占用", level: "warning", status: "resolving", confidence: 91, location: "B 区 · 消防通道", robotName: "智巡二号", detectedAt: "12 分钟前", description: "LiDAR 检测到消防通道存在持续障碍物，可能影响疏散。" },
  { id: "i-304", title: "试剂瓶倾倒风险", type: "AI 检测 · 物品状态", level: "warning", status: "open", confidence: 79, location: "A 区 · 化学实验室", robotName: "智巡一号", detectedAt: "25 分钟前", description: "视觉检测到台面试剂瓶倾斜，建议人工复核摆放状态。" },
  { id: "i-305", title: "夜间门禁未闭合", type: "门禁异常", level: "info", status: "resolved", confidence: 100, location: "D 区 · 东门", robotName: "智巡四号", detectedAt: "昨天 22:04", description: "巡检发现东侧安全门未闭合，已通知安保并确认关闭。" },
  { id: "i-306", title: "地面水渍（滑倒风险）", type: "环境异常", level: "warning", status: "dismissed", confidence: 74, location: "B 区 · 走廊", robotName: "智巡二号", detectedAt: "昨天 15:20", description: "视觉检测到地面反光区域，经复核为清洁后未干水渍，已忽略。" },
];

const maps: MapObject[] = [
  { id: "m-001", name: "实验楼一层", area: "1280 m²", floors: 1, version: 3, updatedAt: "今天 10:12", status: "active" },
  { id: "m-002", name: "实验楼二层", area: "1180 m²", floors: 1, version: 2, updatedAt: "昨天 17:30", status: "active" },
  { id: "m-003", name: "综合楼 · 行政层", area: "960 m²", floors: 1, version: 1, updatedAt: "09-20", status: "draft" },
];

const routes: RouteInfo[] = [
  { id: "rt-001", name: "A 区巡检路线 v3", mapId: "m-001", mapName: "实验楼一层", distance: 86, waypoints: 8, version: 3, updatedAt: "今天 09:40" },
  { id: "rt-002", name: "实验楼 → 行政楼", mapId: "m-001", mapName: "实验楼一层", distance: 142, waypoints: 6, version: 2, updatedAt: "今天 09:40" },
  { id: "rt-003", name: "B 区巡检路线 v2", mapId: "m-002", mapName: "实验楼二层", distance: 74, waypoints: 6, version: 2, updatedAt: "昨天 16:20" },
  { id: "rt-004", name: "C 区机房巡检 v1", mapId: "m-002", mapName: "实验楼二层", distance: 58, waypoints: 5, version: 1, updatedAt: "09-18" },
];

const notifications: NotificationItem[] = [
  { id: "n-1", type: "incident", title: "未佩戴护目镜告警", object: "智巡一号 · A 区", time: "刚刚", read: false, href: "/incidents/i-301" },
  { id: "n-2", type: "incident", title: "烟雾/高温异常确认", object: "智巡三号 · C 区", time: "4 分钟前", read: false, href: "/incidents/i-302" },
  { id: "n-3", type: "task", title: "文件运输到达取件点", object: "智巡二号 · 行政楼", time: "6 分钟前", read: false, href: "/tasks/t-102" },
  { id: "n-4", type: "system", title: "智巡三号电量低于 25%", object: "系统提示", time: "18 分钟前", read: true, href: "/robots/r-003" },
  { id: "n-5", type: "task", title: "B 区巡检任务已创建", object: "调度中心", time: "昨天", read: true, href: "/tasks/t-103" },
];

const auditLogs: AuditEntry[] = [
  { id: "a-1", actor: "管理员 · 陈老师", action: "创建巡检任务", object: "A 区实验室例行巡检", time: "今天 14:20", result: "success" },
  { id: "a-2", actor: "管理员 · 陈老师", action: "确认异常", object: "烟雾/高温异常", time: "今天 14:08", result: "success" },
  { id: "a-3", actor: "操作员 · 小李", action: "触发急停", object: "智巡一号", time: "今天 13:55", result: "success" },
  { id: "a-4", actor: "操作员 · 小李", action: "切换模式", object: "智巡一号 → 巡检", time: "今天 13:48", result: "success" },
  { id: "a-5", actor: "系统", action: "任务失败重试", object: "D 区走廊夜间巡检", time: "昨天 22:08", result: "failure" },
];

const users: UserItem[] = [
  { id: "u-1", name: "陈老师", username: "admin", role: "管理员", status: "active", lastLogin: "今天 14:20" },
  { id: "u-2", name: "小李", username: "operator", role: "操作员", status: "active", lastLogin: "今天 13:52" },
  { id: "u-3", name: "王同学", username: "auditor", role: "审计员", status: "active", lastLogin: "昨天 18:12" },
  { id: "u-4", name: "赵同学", username: "viewer", role: "访客", status: "inactive", lastLogin: "09-18" },
];

const roles: RoleItem[] = [
  { id: "role-1", name: "管理员", description: "系统与安全管理全权限", users: 1, permissions: ["robots.control", "tasks.manage", "incidents.manage", "users.manage", "settings.manage"] },
  { id: "role-2", name: "操作员", description: "任务执行与机器人操作", users: 2, permissions: ["robots.control", "tasks.manage", "incidents.confirm"] },
  { id: "role-3", name: "审计员", description: "只读审计与历史查看", users: 1, permissions: ["robots.view", "tasks.view", "incidents.view", "audit.view"] },
  { id: "role-4", name: "访客", description: "仅查看运行状态", users: 1, permissions: ["robots.view"] },
];

const activity: ActivityItem[] = [
  { id: "ac-1", kind: "incident", text: "智巡一号在 A 区检测到未佩戴护目镜人员", time: "刚刚", href: "/incidents/i-301" },
  { id: "ac-2", kind: "task", text: "文件运输任务进入“运输中”阶段", time: "2 分钟前", href: "/tasks/t-102" },
  { id: "ac-3", kind: "incident", text: "智巡三号上报机房高温异常并已确认", time: "4 分钟前", href: "/incidents/i-302" },
  { id: "ac-4", kind: "robot", text: "智巡四号完成充电，状态恢复为在线", time: "8 分钟前", href: "/robots/r-004" },
  { id: "ac-5", kind: "task", text: "A 区巡检任务进度更新至 62%", time: "12 分钟前", href: "/tasks/t-101" },
  { id: "ac-6", kind: "system", text: "系统完成每日地图快照备份", time: "今天 09:00", href: "/system" },
];

const assets: AssetItem[] = [
  { id: "as-1", name: "ROSMASTER X3 底盘", category: "device", location: "A 区 · 智巡一号", updatedAt: "今天", status: "active" },
  { id: "as-2", name: "RPLIDAR A2 雷达", category: "device", location: "智巡一号", updatedAt: "今天", status: "active" },
  { id: "as-3", name: "YOLO11 安全检测模型", category: "model", location: "边缘推理 · v1.4", updatedAt: "昨天", status: "active" },
  { id: "as-4", name: "ByteTrack 跟踪器", category: "model", location: "边缘推理 · v0.9", updatedAt: "昨天", status: "active" },
  { id: "as-5", name: "护目镜检测数据集", category: "media", location: "训练集 · 4800 张", updatedAt: "09-18", status: "active" },
  { id: "as-6", name: "巡检现场记录 09-21", category: "media", location: "媒体库", updatedAt: "昨天", status: "active" },
];

const analyticsSeries = {
  patrolCount: [18, 22, 20, 26, 24, 30, 28],
  transportCount: [8, 10, 9, 12, 11, 14, 15],
  incidentCount: [5, 4, 6, 3, 4, 2, 3],
  utilization: [42, 55, 61, 58, 72, 69, 78],
  coverage: [64, 71, 74, 82, 86, 91, 94],
  days: ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
};

export type DemoMap = { width: number; height: number; resolution: number; data: number[] };

function buildDemoMap(): DemoMap {
  const width = 120;
  const height = 90;
  const cells = new Array<number>(width * height).fill(0);
  const set = (x: number, y: number, v: number) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return;
    cells[y * width + x] = v;
  };
  const wallH = (x0: number, x1: number, y: number, gap: number) => {
    for (let x = x0; x <= x1; x += 1) { if (x !== gap) set(x, y, 100); }
  };
  const wallV = (y0: number, y1: number, x: number, gap: number) => {
    for (let y = y0; y <= y1; y += 1) { if (y !== gap) set(x, y, 100); }
  };
  const box = (x0: number, y0: number, x1: number, y1: number) => {
    for (let y = y0; y <= y1; y += 1) for (let x = x0; x <= x1; x += 1) set(x, y, 100);
  };
  // outer border
  for (let x = 0; x < width; x += 1) { set(x, 0, 100); set(x, height - 1, 100); }
  for (let y = 0; y < height; y += 1) { set(0, y, 100); set(width - 1, y, 100); }
  // interior walls with door gaps
  wallV(12, 78, 34, 44);
  wallV(12, 78, 66, 50);
  wallH(12, 34, 60, 20);
  wallH(12, 66, 34, 50);
  wallH(54, 108, 44, 82);
  wallV(12, 44, 88, 30);
  // furniture / equipment blocks
  box(16, 18, 24, 26);
  box(44, 40, 54, 50);
  box(72, 18, 82, 26);
  box(16, 44, 24, 52);
  box(92, 52, 104, 62);
  box(76, 70, 88, 78);
  return { width, height, resolution: 0.05, data: cells };
}

export const adapters = {
  async listRobots(): Promise<Robot[]> { await delay(); return robots.map((r) => ({ ...r })); },
  async getRobot(id: string): Promise<Robot | undefined> { await delay(240); return robots.find((r) => r.id === id); },
  async listTasks(): Promise<Task[]> { await delay(); return tasks.map((t) => ({ ...t })); },
  async getTask(id: string): Promise<Task | undefined> { await delay(240); return tasks.find((t) => t.id === id); },
  async listIncidents(): Promise<Incident[]> { await delay(); return incidents.map((i) => ({ ...i })); },
  async getIncident(id: string): Promise<Incident | undefined> { await delay(240); return incidents.find((i) => i.id === id); },
  async listMaps(): Promise<MapObject[]> { await delay(); return maps.map((m) => ({ ...m })); },
  async getMap(id: string): Promise<MapObject | undefined> { await delay(240); return maps.find((m) => m.id === id); },
  async listRoutes(): Promise<RouteInfo[]> { await delay(); return routes.map((r) => ({ ...r })); },
  async getRoute(id: string): Promise<RouteInfo | undefined> { await delay(240); return routes.find((r) => r.id === id); },
  async listNotifications(): Promise<NotificationItem[]> { await delay(180); return notifications.map((n) => ({ ...n })); },
  async listAuditLogs(): Promise<AuditEntry[]> { await delay(); return auditLogs.map((a) => ({ ...a })); },
  async listUsers(): Promise<UserItem[]> { await delay(); return users.map((u) => ({ ...u })); },
  async listRoles(): Promise<RoleItem[]> { await delay(); return roles.map((r) => ({ ...r })); },
  async listActivity(): Promise<ActivityItem[]> { await delay(180); return activity.map((a) => ({ ...a })); },
  async getAnalytics() { await delay(); return { ...analyticsSeries }; },
  async getDemoMap(): Promise<DemoMap> { await delay(200); return buildDemoMap(); },
  async listAssets(): Promise<AssetItem[]> { await delay(); return assets.map((a) => ({ ...a })); },
};
