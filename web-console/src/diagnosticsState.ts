export type DiagnosticEvent = {
  event_id: string; occurred_at: string; observed_at: string;
  level: string; source: string; service: string; module: string;
  event_type: string; reason_code: string; message: string;
  trace_id?: string; robot_id?: string; task_id?: string; episode_id?: string;
  context: Record<string, unknown>; exception?: unknown;
};
export type DiagnosticPage = {
  items: DiagnosticEvent[]; after?: string; next_cursor?: string; reset?: boolean;
  business_events?: { id: number; kind: string; occurred_at: string }[];
};

export function mergeDiagnostics(previous: DiagnosticEvent[], incoming: DiagnosticEvent[], limit = 500) {
  const events = new Map(previous.map(event => [event.event_id, event]));
  incoming.forEach(event => events.set(event.event_id, event));
  return Array.from(events.values()).sort((a, b) =>
    b.occurred_at.localeCompare(a.occurred_at) || b.event_id.localeCompare(a.event_id)).slice(0, limit);
}

export const stopReasons: Record<string, string> = {
  emergency_stop: "急停已触发", operator_stop: "人工停止", stop_mode: "进入停止模式",
  manual_command_timeout: "手动指令超时", navigation_command_timeout: "导航速度输入超时",
  scan_timeout: "雷达数据超时", control_lease_required: "当前无控制租约",
  control_lease_expired: "控制租约到期", control_released: "控制租约已释放",
  lease_mode_mismatch: "租约与当前模式不匹配", search_gate_blocked: "搜索停车锁生效",
  search_gate_held: '搜索停车锁保持', search_gate_timeout: '搜索心跳超时',
  avoidance_blocked: "避障判定通路受阻", avoidance_sensor_fault: "避障观测失效",
  avoidance_waiting_observation: "等待足够的避障观测", avoidance_timeout: "避障超时",
  avoidance_braking: "避障制动", bounded_forward_components: "受限前进拒绝侧移、倒车或转向",
  follow_target_unavailable: "跟随目标丢失", speed_scale_zero: "速度比例为零",
  stationary_evidence_unavailable: "等待期内未获得有效里程计", motion_resumed: "车辆恢复运动",
  fresh_odometry: "停车后收到新鲜里程计", stationary_confirmed: "独立停车已确认静止",
  relative_distance_reached: '达到目标距离', relative_time_limit: '达到前进时限',
  relative_interrupted: '短距前进被中断',
  stationary_unconfirmed: "独立停车未确认静止", independent_stop: "收到独立停车请求",
};
