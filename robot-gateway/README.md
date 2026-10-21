# Robot Gateway

机器人边缘适配器，位于 FastAPI 与 ROS2 之间，是 ROS2 车端唯一合法的控制入口。

## 安全边界（必须保持）

```
Flutter -> FastAPI -> Robot Gateway -> ROS2 -> Patrol/Navigation -> Decision Controller -> Safety Check -> /cmd_vel
```

- `decision_controller` 是唯一允许发布 `/cmd_vel` 的节点。
- Robot Gateway **禁止**直接发布 `/cmd_vel`。
- Robot Gateway 只发布：
  - `/robot/mode/set`
  - `/manual_cmd`
  - `/robot/emergency_stop/set`
  - `/robot/speed_scale`
  - 任务指令（巡检/运输 executor 命令）

## 数据流

- 订阅 ROS2 `/robot/status`、标注帧，写入 Redis：
  - `robot:status:{robot_id}`
  - `robot:annotated_frame:{robot_id}`
- 从 Redis 读取命令：`robot:command:{robot_id}`，并映射到上述安全话题。

## 目录

- `gateway/contracts.py`：ROS2 事件与命令的 JSON Schema。
- `gateway/gateway.py`：Redis <-> ROS2 适配主循环骨架。
- `simulator/simulate.py`：无真实 Jetson 时的状态/事件模拟器。