const reasons: Record<string, string> = {
  navigation_waiting_command: "正在等待本轮导航的首条速度指令，小车保持停车",
  navigation_start_timeout: "导航启动等待超时，已停车，请检查规划与控制服务",

  stop_mode: "停止模式", operator_stop: "已松手或主动停止", emergency_stop: "急停已锁定",
  manual_command_timeout: "驾驶指令已过期", navigation_command_timeout: "导航指令已过期",
  navigation_invalid_velocity: "导航速度无效", speed_scale_zero: "速度设置为零",
  speed_scale_invalid: "速度设置无效", turn_speed_invalid: "转速设置无效",
  control_lease_required: "尚未取得控制权", control_lease_expired: "控制权已过期，请重新选择模式",
  control_released: "控制权已释放", lease_mode_mismatch: "控制权与当前模式不一致",
  search_gate_held: "当前搜索要求停车", search_gate_timeout: "当前搜索心跳超时",
  follow_target_unavailable: "跟随目标不可用", follow_input_timeout: "跟随数据过期",
  follow_input_invalid: "跟随数据无效", detection_timeout: "当前任务的识别数据过期",
  scan_timeout: "雷达数据过期", scan_unavailable: "尚未收到有效雷达证据",
  scan_stale: "雷达时间戳无效或过期", scan_mount_tf_unavailable: "雷达安装坐标变换不可用",
  scan_odom_tf_unavailable: "完整防护或绕行所需的位姿变换不可用",
  footprint_invalid: "车体标定无效", recovery_confirmation_required: "请先确认故障恢复",
  avoidance_sensor_fault: "防撞数据异常", avoidance_blocked: "运动路径有障碍",
  avoidance_waiting_observation: "运动方向缺少可靠观测", avoidance_braking: "正在安全制动",
  avoidance_timeout: "主动绕行已超时", avoidance_waiting: "等待防护设置确认",
  avoidance_assessing: "主动绕行正在评估", avoidance_recovering: "主动绕行正在恢复方向",
  bounded_forward_components: "短距前进任务不允许横移或转动",
};

export function protectionReason(code: string) {
  return reasons[code] ?? "当前条件不允许运动，请查看车端状态";
}
