# 总体架构图代码核查

核查基线：V4 开发线提交 `ba46693`。本次修改限于图稿、图稿生成与检查工具、README 和相关说明，不改变运行时架构。

## 核心关系及依据

| 图中关系 | 实际实现 |
| --- | --- |
| Windows 桌面入口 → React / 本机服务 | `desktop/insightrover_desktop/launcher.py`、`server.py`：启动管理、创建业务应用并挂载前端静态资源 |
| React ↔ FastAPI | `web-console/src/services/businessApi.ts`、`robotApi.ts`、`hooks/useRobotStream.ts`：业务 HTTP、状态 WebSocket；助手消息与执行事件通过 SSE 接收 |
| FastAPI → 身份认证与 RBAC | `backend/app/api/deps.py`、`api/routes/assistant.py`、`api/routes/navigation_tasks.py`：当前用户、权限及车辆绑定校验 |
| Agent 编排 ↔ 外部大模型 API | `backend/app/services/assistant_provider.py`、`assistant_tools.py`、`assistant_operations.py`：提供器、工具定义、调用及请求约束；图中外部模型 API 通过主机提供器调用 |
| 计划确认 → AssistantWorker | `backend/app/services/assistant_execution.py::confirm` 保存执行记录；`assistant_worker.py::tick`、`_dispatch` 推进已确认计划 |
| 普通任务与 Agent 复用业务执行 | `backend/app/api/routes/navigation_tasks.py::create_execution`、`apply_execution_action` 既是业务接口，也由 `AssistantWorker._dispatch` 调用；搜索与短距动作分别复用 `search_execution.py`、`relative_motion.py` |
| 任务进度与结果持久化 | `backend/app/services/navigation_execution.py::store_execution`、`task_reconciler.py::reconcile_once`：保存车端确认的任务记录并对账；`models/assistant.py` 保存会话、计划、执行与事件 |
| 主机内 RobotGateway → 车端 HTTP | `backend/app/gateway/robot_gateway.py`：进程内 Python 类，使用 `httpx.AsyncClient`；任务、地图、目标、租约、停止及状态接口均经 HTTP 访问 |
| 状态 WebSocket 的独立代理路径 | `backend/app/api/routes/vehicle_control.py::vehicle_status_socket`：校验用户及车辆绑定后，连接车端 `/ws/status` 并转发。该代码位于 FastAPI 进程，图中与 RobotGateway 并列在主机通信适配框内 |
| 机器鉴权与租约 | `robot_gateway.py::_client`、`services/control_leases.py`、车端 `service_auth.py`、`control_lease.py`、`lease_bridge.py`：机器请求头、租约签发续期及控制器回执 |
| 车端 Web 服务 → 任务、模式和共享视觉 | `ros2_ws/src/smart_car_decision/smart_car_decision/web_app_node.py`：实例化 `NavigationBridge`、`NavigationTaskRunner`、`CameraStream`、`VisionService`、`SafetyVisionWorker`，并发布模式及控制意图 |
| 相机 → 通用与专项视觉模型 | `web_app_node.py::_run_server` 创建共享 `CameraStream`；`vision_service.py`、`yoloe_worker.py` 处理 YOLOE；`safety_vision.py` 处理人员倒地与烟火专项模型 |
| 视觉候选 → 事件与证据 → 主机 | `safety_events.py::EventGate`、`SafetyOutbox` 与 `safety_vision.py`：持续确认和本地证据；`backend/app/services/safety_ingest.py::_pull_events` 通过 HTTP 拉取、存储、入库并确认事件 |
| SLAM → 地图资产 | `launch/mapping.launch.py`、`smart_car_decision/mapping_session.py`、`map_assets.py`：启动 SLAM Toolbox、接收栅格并保存 |
| 地图资产 → AMCL / Nav2 | `smart_car_decision/navigation_runtime.py::load` 保存并加载地图、停止建图，启动 `launch/navigation.launch.py`；该启动文件分别加载 AMCL 定位与 Nav2 规划控制节点 |
| 导航任务 → Nav2 Action | `smart_car_decision/navigation_tasks.py` 调用 `NavigationBridge.plan/start`；`navigation_bridge.py` 使用 `/compute_path_to_pose` 和 `/navigate_to_pose` Action |
| Nav2 → 导航速度 → 统一控制器 | `launch/navigation.launch.py` 将控制与行为速度重映射至 `/navigation/raw_cmd_vel`，经速度平滑器输出 `/navigation/cmd_vel`；`decision_controller.py` 订阅该话题 |
| 手动 / 搜索意图 → 统一控制器 | `decision_controller.py` 订阅 `/manual_cmd`、模式、急停和 `/robot/search/control`；`vision_service.py` 通过 Web 节点发布搜索门控 |
| 统一控制器 → /cmd_vel → 底盘驱动 | `decision_controller.py` 创建最终 Twist 发布器；`launch/bringup_all.launch.py` 启动 Yahboom `Mcnamu_driver_X3`。图中只有此安全控制链连接底盘执行 |
| 雷达 / 底盘传感 → 软件信息层 | `launch/bringup_all.launch.py` 启动雷达、底盘里程计、IMU 滤波、EKF 与机器人 TF；`config/ekf_x1_x3.yaml`、`navigation.yaml`、`slam_toolbox.yaml` 给出输入配置 |
| 位姿 / 状态 / 诊断 → 主机与界面 | 车端 `system_status_node.py`、`web_app_node.py`、`diagnostic_log.py`；主机 `robot_context.py`、`task_reconciler.py`、`services/diagnostics/vehicle.py`、`safety_ingest.py` 分别同步遥测、任务、诊断和证据 |

## 表达口径

“持久任务执行与状态管理”是逻辑分区，包含助手计划推进器、共享业务执行服务及任务对账。普通业务任务不经过 AssistantWorker，但与助手任务共用业务执行入口、车辆控制租约和状态持久化能力。

“主机通信适配”也是同一进程内的逻辑分区，图内分别写明 RobotGateway 的 HTTP 调用和 `vehicle_control` 的状态 WS 代理。两者均不代表独立中间服务器。

“ROS 2 传感与坐标信息”是信息与处理层，不是硬件。其箭头连接自主导航逻辑分区，表示该分区内 SLAM、AMCL、Nav2 对雷达、里程计及 TF 的订阅与使用；不同节点读取各自配置的输入。地图资产分别供定位与导航使用，SLAM 不被表示为 AMCL 的上级服务。

物理硬件按任务要求列出 Jetson Orin Nano、相机、激光雷达、底盘反馈传感与 X3 四轮电机；硬件型号不由软件类推断。图中 Jetson 的具体型号沿用项目 `docs/vehicle-web-api.md` 的设备说明和本次任务指定名称。

图中连线仅概括已存在的协作关系，不展示每个 HTTP 路径或内部函数。没有新增微服务、消息队列、多 Agent、RAG、长期记忆、云端调度或动作生成模型。
