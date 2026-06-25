export type LidarHealthLike = { ok?: boolean; message?: string };

export function lidarIsReady(health: LidarHealthLike | undefined): boolean {
  return health?.ok === true;
}

export function lidarHealthLabel(health: LidarHealthLike | undefined): string {
  if (!health) return "等待雷达数据";
  if (health.ok) return "雷达正常";
  if (health.message === "no_data") return "未收到雷达数据";
  if (health.message === "stale") return "雷达数据已过期";
  if (health.message === "insufficient_valid_points") return "雷达有效点不足";
  return "雷达异常";
}
