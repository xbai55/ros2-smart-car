# 车端 Web Node（InsightRover 小车端 Web API）

本文档描述 Jetson 上的车端 Web Node：它是 **Web 与 ROS2 之间的适配层**，不是新的机器人控制器。

```text
服务器主机                       小车（Jetson Orin Nano）
React → FastAPI → Robot Gateway
                        HTTP / WebSocket
                              │
                              ▼
                    ┌───────────────────┐
                    │ web_app_node:8080 │  解析请求 / 读取 ROS2 状态
                    └─────────┬─────────┘
                              │ 只发布「控制意图」
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                 状态话题   地图话题   控制意图话题
                                          │
                                          ▼
                                 decision_controller
                                          │
                                       /cmd_vel
                                          │
                                    ROSMASTER X3
```

安全红线：**Web Node 永远不会发布 `/cmd_vel`**。速度仲裁、避障停车等策略完全由 `decision_controller` 负责，
Web Node 只把 Web 请求翻译成现有的 ROS2 控制意图话题。

## 1. 代码结构

| 文件 | 职责 |
| --- | --- |
| `smart_car_decision/web_app_node.py` | ROS2 节点：参数、发布/订阅、ROS2 执行器与 Web 服务的并发（uvicorn 跑在守护线程） |
| `smart_car_decision/web_api.py` | 纯 Python 的 FastAPI 应用（`create_app(node)`）：路由、请求归一化、状态载荷转换。不导入 `rclpy`，因此可以直接用 `TestClient` 测试 |
| `smart_car_decision/web_state.py` | `RobotStateStore`：内存状态缓存（模式、雷达、里程计、TF、任务状态等） |
| `smart_car_decision/web_camera.py`、`web_video.py` | 视频流与标注帧缓存 |
| `smart_car_decision/web_static.py` | Web 控制台静态资源目录解析 |

并发模型：`rclpy.spin()` 占用主线程，`uvicorn` 在 `threading.Thread(daemon=True)` 中运行；
HTTP/WebSocket 请求只访问内存状态与发布器，不阻塞 ROS2 回调，客户端断开也不会让节点退出。

## 2. API 表

| 方法 | 路径 | 功能 | ROS2 对应接口 |
| --- | --- | --- | --- |
| GET | `/health` | Web Node 存活检查；ROS2 数据状态在 `ros2` 子字段 | `/robot/status`（仅判断新鲜度） |
| GET | `/api/status` | 机器人状态（文档字段 + 旧控制台字段） | `/robot/status`、`/odom`、`/tf`、`/scan` |
| GET | `/api/map` | SLAM 地图快照；无地图返回 404 | `/map`（`nav_msgs/OccupancyGrid`） |
| GET | `/api/video` | 视频服务地址与采集诊断（帧数、最新帧年龄、编码大小） | `/vision/annotated_frame` / USB 摄像头 |
| GET | `/api/video?frame=true` | 单张最新 JPEG；无新鲜帧返回 503，禁止缓存 | `/vision/annotated_frame` / USB 摄像头 |
| GET | `/video_feed` | MJPEG 视频流 | `/vision/annotated_frame` / USB 摄像头 |
| POST | `/api/command` | 统一控制入口：手动命令 / 模式 / 速度比例 / 急停 / 任务 | `/manual_cmd`、`/robot/mode/set`、`/robot/speed_scale`、`/robot/emergency_stop/set`、`/patrol_task/set`、`/mission_task/set` |
| POST | `/api/mode` | 设置工作模式 | `/robot/mode/set`（`String`） |
| POST | `/api/command`（`forward/backward/left/right/turn_left/turn_right/stop`） | 手动控制意图 | `/manual_cmd`（`String`） |
| POST | `/api/emergency-stop` | 设置/解除急停 | `/robot/emergency_stop/set`（`Bool`），使能时同时向 `/manual_cmd` 发 `stop` |
| POST | `/api/speed` | 设置速度比例（0.15–1.0） | `/robot/speed_scale`（`Float32`） |
| POST | `/api/patrol-task` | 下发巡检任务 | `/patrol_task/set`（`String` JSON） |
| POST | `/api/mission-task` | 下发运输任务 | `/mission_task/set`（`String` JSON） |
| POST | `/api/color-target` | 设置 HSV 颜色配置 | `/vision/color_config`（`String` JSON） |
| POST | `/api/mode-obstacle-stop-distance` | 设置分模式障碍停车距离 | `/robot/mode_obstacle_stop_distances`（`String` JSON） |
| POST | `/api/tracking-target` | 选择/取消跟随目标 | `/vision/tracking_target/set`（`String` JSON） |
| GET | `/api/debug/pose-log`、`POST /api/debug/pose-log/clear` | 位姿调试日志 | 本地缓存 |
| POST | `/api/mapping/restart`、`POST /api/mapping/save` | 重启/保存 SLAM | `slam_toolbox`、`/map` |
| WS | `/ws/status` | 实时状态推送（默认 0.5 s 一帧） | `/robot/status` 等状态缓存 |
| WS | `/ws/control` | 低延迟手动命令 | `/manual_cmd` |

## 3. 请求格式（兼容旧控制台与主机端 Gateway）

`/api/command` 同时支持三种写法，内部会归一化到同一套控制意图：

```jsonc
// 1) 旧控制台：只给 command
{"command": "forward"}

// 2) 主机端 Robot Gateway：信封格式（topic + command + payload）
{"robot_id": "r-001", "type": "manual_cmd", "topic": "/manual_cmd",
 "command": "rotate_left", "payload": {"speed": 0.3}}

// 3) 文档简化格式：command + 参数字段
{"command": "mode", "mode": "manual"}
```

归一化规则：

* 命令名 `set_mode` / `mode` → `/robot/mode/set`；`speed_scale` / `speed` → `/robot/speed_scale`；
  `emergency_stop` → `/robot/emergency_stop/set`；`patrol_task` / `mission_task` → 对应任务话题；
  其余名称按手动命令处理，发布到 `/manual_cmd`。
* 主机端的 `rotate_left` / `rotate_right` 会映射到车端已有的 `turn_left` / `turn_right`。
* `payload.speed` 不参与手动命令：速度比例由 `/robot/speed_scale` 单独控制，
  线速度最终由 `decision_controller` 依据 `cruise_speed/slow_speed/turn_speed × speed_scale` 计算。

状态码约定：

| 状态码 | 含义 |
| --- | --- |
| 200 | 已下发到对应 ROS2 控制意图话题 |
| 400 | 未知控制指令 |
| 403 | 请求指定了 `/cmd_vel`（安全红线，直接拒绝） |
| 409 | 当前模式不接受手动命令（仅 `manual` / `mapping` 接受）；或建图重启前置条件不满足 |
| 422 | 字段缺失或取值非法（模式名、速度、急停布尔值、任务 action） |

## 4. `/api/status` 与 `/ws/status` 字段

`/api/status` 在原有快照字段（`mode`、`emergency_stop`、`lidar`、`map`、`odom`、`tf`、`map_pose`、
`detection`、`color_target`、`radar_points`、`speed_scale`、`last_command`、`nodes` 等）之上，
补充了主机端文档要求的字段：

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `status` | `mode` + `emergency_stop` | `emergency_stop` / `idle` / `running` |
| `mode` | `/robot/mode` | 现有模式名 |
| `battery` | **无来源** | 固定 `null`，车端 ROS2 项目没有电池/电压话题 |
| `temperature` | **无来源** | 固定 `null`，车端 ROS2 项目没有温度话题 |
| `speed` | `odom.linear_speed` | `odom` 不可用时为 `null` |
| `position` | `map_pose`（TF `map → base_link`） | `{x, y, yaw}`；不可用时为 `null` |
| `network` | `/robot/status` 新鲜度 | `connected`（≤3 s）/ `stale`（≤10 s）/ `disconnected` / `unknown` |
| `current_task` | `/patrol_task/progress`、`/mission_task/state` | 无进行中任务时为 `null` |
| `capabilities` | 静态说明 | 明确哪些字段「不支持」，避免把「无数据」误读成 0 |

`/ws/status` 每帧是「旧字段 + 文档信封」：

```json
{
  "type": "robot_status",
  "timestamp": 1234567890.5,
  "data": {"status": "running", "mode": "auto", "battery": null, "speed": 0.25,
           "position": {"x": 1.2, "y": 2.4, "yaw": 1.57},
           "network": "connected", "temperature": null, "current_task": null},
  "mode": "auto", "emergency_stop": false, "lidar": {"ok": true}
}
```

## 5. 配置

| 配置项 | 默认值 | 说明 |
| --- | --- | --- |
| `WEB_HOST`（环境变量） | — | 覆盖 ROS2 参数 `host` |
| `WEB_PORT`（环境变量） | — | 覆盖 ROS2 参数 `port` |
| `host` / `port`（ROS2 参数） | `0.0.0.0` / `8080` | `config/decision.yaml` |
| `static_dir` | 包内 `web/static` | Web 控制台目录（例如 `web-console/dist`） |
| `status_topic` | `/robot/status` | 状态输入 |
| `mode_set_topic` / `manual_cmd_topic` / `emergency_stop_set_topic` / `speed_scale_topic` | `/robot/mode/set`、`/manual_cmd`、`/robot/emergency_stop/set`、`/robot/speed_scale` | 控制意图输出 |
| `patrol_task_topic` / `mission_task_topic` | `/patrol_task/set`、`/mission_task/set` | 任务输出 |
| `patrol_progress_topic` / `mission_state_topic` | `/patrol_task/progress`、`/mission_task/state` | 任务状态输入 |
| `camera_source`、`video_fps`、`video_target_fps`、`annotated_stream_fps` | `0`、30、12、20 | 相机持续采集，编码和传输分别限速 |
| `video_jpeg_quality`、`video_stream_width` | 75、960 | 网页 JPEG 质量和最大宽度，保持宽高比 |
| `ROS_DOMAIN_ID` | `77`（`scripts/run_jetson.sh`） | 与主机端保持一致 |

`WEB_HOST` / `WEB_PORT` 的优先级高于 ROS2 参数，便于在不改 yaml 的情况下调整监听地址。

网页共享画面使用 `/api/video?frame=true`：每次画面下载并解码后才读取下一张，目标每秒 10 张，单次请求与解码最多 1.5 秒。后台标签页暂停请求，恢复时请求最新帧；不会在断网恢复后追播积压视频。响应携带 `X-Frame-Sequence`、`X-Frame-Age-Ms` 和 `X-Frame-Source`。帧年龄只表示车端采集读取完成到响应之间的时间，不能当成传感器到屏幕的总延迟。旧 `/video_feed` MJPEG 接口保留兼容。

## 6. 启动方式

```bash
# 首次或依赖变化后
bash scripts/build_jetson.sh          # pip3 install requirements-web.txt + colcon build

# 随整机启动（含底盘驱动、SLAM、web_app_node）
bash scripts/run_jetson.sh            # ros2 launch smart_car_decision bringup_all.launch.py
```

也可以单独启动 Web Node（需要先 source ROS2 与本工作空间）：

```bash
export ROS_DOMAIN_ID=77
ros2 run smart_car_decision web_app_node --ros-args -p port:=8080
```

验证：

```bash
curl http://<jetson-ip>:8080/health
curl http://<jetson-ip>:8080/api/status
ros2 topic echo /manual_cmd        # 在网页上按前进，应看到 forward
ros2 topic echo /cmd_vel           # 只应由 decision_controller 发布
```

## 7. 测试范围

* `tests/test_web_api.py`：用 `fastapi.testclient.TestClient` + 假 ROS2 节点覆盖
  `/health`、`/api/status`、`/api/map`、`/api/command`、`/api/mode`、`/api/emergency-stop`、
  `/api/speed`、`/api/patrol-task`、`/api/mission-task`、`/api/video`、`/`、`/ws/status`、`/ws/control`。
* `tests/test_web_api_contract.py`：请求归一化、`Web API → ROS2 话题` 映射、`/health` 信封、
  以及「Web Node 只发布控制意图话题、永不发布 `/cmd_vel`」的结构化断言
  （解析 `create_publisher` 参数白名单 + 断言 `decision_controller.py` 是唯一的 `/cmd_vel` 发布者）。

这些测试**只证明 Web API 层正确**；音频/视频、真实雷达、底盘运动等仍需在真车上验证。
