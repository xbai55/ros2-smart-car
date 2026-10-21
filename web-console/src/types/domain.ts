export type RobotHealth = "online" | "offline" | "degraded" | "charging";

export type Robot = {
  id: string;
  name: string;
  model: string;
  zone: string;
  health: RobotHealth;
  mode: string;
  battery: number | null;
  speed: number | null;
  frontDistance: number | null;
  position: { x: number; y: number } | null;
  heading: number | null;
  tasks: number | null;
  incidents: number | null;
  lastSeen: string;
};

export type TaskType = "patrol" | "transport";
export type TaskStatus = "pending" | "running" | "paused" | "completed" | "failed" | "cancelled" | "queued" | "dispatched" | "transporting";
export type TransportStage = "pickup" | "loading" | "transit" | "arrived" | "handover" | "done";

export type Task = {
  id: string;
  title: string;
  type: TaskType;
  status: TaskStatus;
  robotId: string | null;
  robotName: string;
  routeName: string;
  progress: number | null;
  currentStep: string;
  createdAt: string;
  updatedAt: string;
  transportStage?: TransportStage;
};

export type IncidentLevel = "critical" | "warning" | "info";
export type IncidentStatus = "open" | "confirmed" | "resolving" | "resolved" | "dismissed";

export type Incident = {
  id: string;
  title: string;
  type: string;
  level: IncidentLevel;
  status: IncidentStatus;
  confidence: number | null;
  location: string;
  robotName: string;
  detectedAt: string;
  description: string;
};

export type MapObject = {
  id: string;
  name: string;
  area: string;
  floors: number | null;
  version: number | null;
  updatedAt: string;
  status: "active" | "draft";
};

export type RouteInfo = {
  id: string;
  name: string;
  mapId: string;
  mapName: string;
  distance: number | null;
  waypoints: number;
  version: number | null;
  updatedAt: string;
};

export type NotificationItem = {
  id: string;
  type: "incident" | "task" | "system";
  title: string;
  object: string;
  time: string;
  read: boolean;
  href: string;
};

export type AuditEntry = {
  id: string;
  actor: string;
  action: string;
  object: string;
  time: string;
  result: "success" | "failure" | null;
};

export type UserItem = {
  id: string;
  name: string;
  username: string;
  role: string;
  status: "active" | "inactive";
  lastLogin: string;
};

export type RoleItem = {
  id: string;
  name: string;
  description: string;
  users: number | null;
  permissions: string[];
};

export type ActivityItem = {
  id: string;
  kind: "task" | "incident" | "robot" | "system";
  text: string;
  time: string;
  href: string;
};

export type AssetItem = {
  id: string;
  name: string;
  category: "device" | "model" | "media";
  location: string;
  updatedAt: string;
  status: "active" | "archived";
};
