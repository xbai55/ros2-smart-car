# 前端现状审查：ros2-smart-car

> 状态：审查完成；Phase 0–9 已落地首版，详见同目录 `phase-*.md`。
> 审查日期：2026-09-18
> 工作区：`C:\Users\xbai55\Desktop\综设\ros2-smart-car`
> Git：`main`，`HEAD=0011fcd`
> 主要依据：`综设三/Codex_AI机器人平台前端重构完整提示词.md`、`综设三/ai_robotics_platform_ui_reference.png`、`综设三/实验室安全巡检与文件运输系统_前后端详细设计.md`、仓库 README/docs/doc/web-console/ros2_ws/tests。

## 0.0 当前实施状态

- 新前端：`flutter_app/`，Flutter + Riverpod + Freezed + go_router，页面 `Login/Overview/Robots/Patrol/Missions/Incidents/Analytics/Settings`。
- 新后端：`backend/`，FastAPI + SQLAlchemy + JWT/Refresh Token + RBAC，SQLite 本地验证、Redis 抽象已保留。
- 边界层：`robot-gateway/` 禁止 `/cmd_vel`，只发布安全话题与任务指令。
- 旧 `web-console/` 保留；未覆盖 `tests/test_bytetrack_integration.py` 与 rollback patch。
- 视觉截图：`docs/refactor/screenshots/`，每页 1440×900 及 1920×1080 / 1280×800 响应式验收。

---

## 0. 审查结论摘要

当前项目不是“传统管理后台”，而是一套以 **ROS2 实车控制台** 为核心的边缘调试 Web。它的机器人安全链路设计比较清晰，`web_app_node.py` 没有直接发布 `/cmd_vel`；但前端只有单页 React 控制台，没有业务后端、没有认证权限、没有任务/巡检/异常/分析等企业业务能力。因此本项目既有可复用的车端资产，也确有需要重构的前端与后端边界。

| 维度 | 现状 | 结论 |
| --- | --- | --- |
| 前端形态 | React + TypeScript + Vite，单页控制台 | 需整体重构为 Flutter |
| 页面范围 | Home + Console 两块伪页面，无路由 | 需补齐完整企业页面 |
| 数据真实度 | 机器人状态真实；业务数据几乎不存在 | 需新建业务 API |
| 权限 | 无登录、无 JWT、无 RBAC | 必须新增 |
| 实时链路 | `/ws/status` 0.5s 快照 + `/ws/control` 手动命令 | 可复用，但需事件化 |
| 地图 | SLAM 占据栅格展示已有，实车验收未闭环 | 复用渲染逻辑，重构体验 |
| 相机 | MJPEG/标注帧可用 | 复用，重构 UI |
| 后端 | FastAPI 嵌在 ROS2 节点内 | 需拆分 FastAPI 与 Robot Gateway |
| 数据库 | 无 | 需 PostgreSQL + Redis |
| 机器人功能 | 底盘、雷达安全、YOLO、颜色跟随、建图资产已实现；Nav2/巡检/运输未实现 | 保持车端，不要破坏 |

---

## 0.1 机器人能力完成度矩阵

| 能力 | 代码完成度 | 实车/闭环状态 | 前端支持 | 重构后动作 |
| --- | --- | --- | --- | --- |
| SLAM 建图 | 已实现：`slam_toolbox.yaml`、`mapping.launch.py`、`map_assets.py`、地图保存/加载/预览 | 本地/自动化测试通过，待 Jetson 实车建图验收 | 当前 React 有地图显示和重启/保存，但视觉仍是调试 HUD | 保留车端与地图算法，重构为 Map Workspace |
| Localization 定位 | 部分：TF、`/odom`、`map_pose` 有采集；未实现 AMCL/Nav2 定位闭环 | 未完成 | 仅显示位姿健康 | 后续接 Nav2 后补定位页面 |
| Nav2 导航 | 未完成：只有 `map_view.launch.py` 加载地图；无目标点、规划、控制 | 未完成 | 无 | 新建任务执行层，不得绕开 `decision_controller` |
| AI Detection | 已实现：YOLO11、ByteTrack 人物跟随、交通灯 HSV 辅助、颜色追踪；微调模型已训练待默认接入 | YOLO/颜色跟随已实车部分验证；三类异常检测尚未实现 | 无 Detection Overlay，只有视频流 | 复用 AI 节点；补 smoke/fire/fallen/blocked 检测与事件上报 |
| Robot Status | 已实现：`system_status_node` 汇总 mode/estop/lidar/map/odom/cmd_vel/tf/detection/color/tracking | 已实车验证 | 有状态卡和 JSON 展示 | 沿用 schema，但改为事件化 WebSocket |
| LiDAR Safety | 已实现：`laser_obstacle_monitor` + `decision_controller` 近障停车、雷达超时停车 | 已实车测试 | 有雷达点云与健康展示 | 保留安全仲裁，前端只做状态/安全面板 |
| WebSocket | 已实现但原始：`/ws/status` 0.5s 全量快照、`/ws/control` 手动命令 | 已使用 | 有自动重连 | 升级为事件化、鉴权、按机器人订阅 |
| Camera | 已实现：MJPEG `/video_feed`、视觉模式标注帧、相机所有权切换 | 已实车使用 | 有 Live Camera，但无 AI Box | 复用视频代理，补 AI Detection Overlay |
| Patrol 巡检 | 未实现：只有 `综设三` 中的业务设计，无 ROS2 任务执行器和 FastAPI 任务状态机 | 未实现 | 无 | 新增任务/路线/执行器/历史 |
| Mission 运输 | 未实现：无取件/运输/交接状态机和执行器 | 未实现 | 无 | 新增业务状态机；UI 不得虚构机械臂 |
| Incident / Notification / Audit | 未实现 | 未实现 | 无 | 新增数据库、事件、通知、审计 |

---

## 1. 当前前端架构

```text
React 19 + TypeScript 5 + Vite 6
        │
        │ fetch /api/*  + WebSocket /ws/*
        ▼
web_app_node.py 内嵌 FastAPI + Uvicorn
        │
        │ ROS2 topics
        ▼
ROS2 decision_controller / system_status_node / sensor nodes
```

`web-console/` 是前端源码；`ros2_ws/src/smart_car_decision/web/static/` 是旧版 vanilla JS 静态回退资源，FastAPI 在找不到 Vite `dist` 时提供这套旧页面。

- 没有 `react-router`，页面切换是 `App.tsx` 里的 `consoleOpen` 布尔状态。
- 没有全局状态库，主要状态来自 `useRobotState.ts` 的自定义 Hook。
- 没有 API 抽象层之外的业务领域模型，只有 `RobotStatus` 类型。
- 没有设计系统组件库，视觉由约 47KB 的 `App.css` 控制。

---

## 2. 当前页面

当前 React 实际只有两种视图：

| 视图 | 文件 | 内容 |
| --- | --- | --- |
| Home | `src/components/HomePage.tsx` | 品牌、状态摘要、进入控制台按钮、急停按钮 |
| Console | `src/App.tsx` | 模式侧栏、状态卡、相机、系统摘要、模式操作、地图、雷达、发车前检查 |

Sidebar 中展示的不是业务导航，而是 7 种 ROS2 工作模式：`stop/manual/auto/mapping/navigation/color_track/object_follow`。这与目标产品所需的 `Overview/Robots/Patrol/Missions/Incidents/Analytics/Settings` 完全不同。

已存在但未作为独立业务页面的模块：

- 建图控制：`MapPanel.tsx`
- 雷达可视化：`LidarPanel.tsx`
- 手动遥控：`ManualControlPanel.tsx`
- HSV 颜色配置：`ColorConfigPanel.tsx`
- 感知健康：`PerceptionHealthPanel.tsx` / `SystemSummaryPanel.tsx`
- 发车前检查：`PreDriveChecklist.tsx`

目标企业页面 `Login/Robots/Patrol/Missions/Incidents/Analytics/Settings/Users/Roles/Notifications/Audit/Maps/Routes/History` 当前均未实现。

---

## 3. 当前路由

前端：无客户端路由，仅由 React 状态控制 Home/Console 两态。

FastAPI 当前路由：

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/` | 返回静态 `index.html` |
| GET | `/api/status` | 返回 `RobotStateStore.snapshot()` |
| GET | `/api/map` | 返回 `/map` OccupancyGrid 快照 |
| GET | `/api/debug/pose-log` | 返回位姿调试日志 |
| POST | `/api/debug/pose-log/clear` | 清空位姿日志 |
| POST | `/api/mapping/restart` | 重启 slam_toolbox |
| POST | `/api/mapping/save` | 保存地图 YAML/PGM |
| POST | `/api/mode` | 设置 ROS2 模式 |
| POST | `/api/command` | 下发手动移动命令 |
| POST | `/api/emergency-stop` | 设置/解除急停 |
| POST | `/api/speed` | 设置速度比例 |
| POST | `/api/color-target` | 设置 HSV 颜色配置 |
| POST | `/api/mode-obstacle-stop-distance` | 设置指定模式近障停车距离 |
| POST | `/api/tracking-target` | 自动/手动选择跟随人物 |
| GET | `/video_feed` | MJPEG 视频流 |

目标架构要求的 `/api/v1` 版本化接口、认证接口、任务/地图/路线/异常/统计/审计接口均不存在。

---

## 4. 当前 API 调用

`web-console/src/robotApi.ts` 是当前唯一 API Client，采用同源相对路径，无 baseURL、无认证头、无超时策略、无请求取消。方法：

- `getStatus`
- `getMap`
- `restartMapping`
- `saveMapping`
- `setMode`
- `sendCommand`
- `setEmergencyStop`
- `setSpeed`
- `setModeObstacleStopDistance`
- `setColorConfig`

错误处理只在 `readJson` 中把非 2xx 转成 `detail` 错误文本，缺少业务错误码、幂等键、重试和 403 等状态语义。

---

## 5. 当前 WebSocket

| 端点 | 方向 | 行为 |
| --- | --- | --- |
| `/ws/status` | 服务端→客户端 | 每 0.5s 发送一次 `RobotStateStore.snapshot()` |
| `/ws/control` | 客户端→服务端 | 接收 `{command}`，调 `set_command`，回传 `{command}`；断开时发布 `stop` |

`useRobotState.ts` 的 WebSocket 逻辑：

- 连接前先 `GET /api/status` 做快照校准；
- 建立 `/ws/status` 连接；
- `onclose` 后 1.5s 自动重连；
- 没有心跳、没有事件类型、没有房间订阅、没有按机器人订阅、没有鉴权。

目标要求的 `/ws/v1/robots/{robot_id}`、`robot_status/robot_position/patrol_progress/incident_created/notification_created/transport_task_updated` 等事件总线尚未建立。

---

## 6. 当前状态管理

- 核心状态：`useRobotState()` 内的 `status/connection/error`，通过 `useState` 管理。
- 派生状态：`App.tsx` 内 `useMemo` 生成 `statusCards`。
- 局部 UI 状态散落在各组件：`consoleOpen/jsonExpanded/videoRevision/videoState/mappingRestarting/mappingSaving/mappingSavePath`。
- 本地持久化：只有颜色配置通过 `localStorage` 保存，速度默认值旧版前端也曾存 localStorage。
- 没有统一 `RobotState/PatrolState/IncidentState/NotificationState` 领域状态模型。

这导致逻辑集中在 `App.tsx`，组件间通过 props 层层传递，后续加任务/异常/通知等页面时不可扩展。

---

## 7. 当前组件体系

`web-console/src/components/`：

| 类别 | 文件 |
| --- | --- |
| Shell | `Sidebar.tsx`、`HeaderBar.tsx`、`HomePage.tsx` |
| 通用面板 | `HudPanel.tsx`、`StatusCard.tsx`、`QuickResultCard.tsx` |
| 相机 | `LiveCameraPanel.tsx` |
| 雷达 | `LidarPanel.tsx` |
| 地图 | `MapPanel.tsx` |
| 控制 | `ModeOperationPanel.tsx`、`ManualControlPanel.tsx`、`ColorConfigPanel.tsx`、`PreDriveChecklist.tsx` |
| 健康/状态 | `SystemSummaryPanel.tsx`、`PerceptionHealthPanel.tsx`、`ModeFocusPanel.tsx` |

组件粒度尚可，但属于“机器人调试 HUD”，不是企业 SaaS 工作台组件。缺少：AppShell、RobotMarker、Timeline、ActivityFeed、CommandPanel、DataChart、FilterBar、Drawer、Toast、NotificationPanel 等目标 Design System 组件。

---

## 8. 当前视觉体系

`App.css` 约 47KB，核心变量：

- `--bg-0:#020713`、`--bg-1:#041227`、`--bg-2:#062245`
- `--cyan:#19dfff`、`--blue:#0a84ff`、`--green:#40e486`、`--red:#ff4e54`
- 深色、网格背景、径向渐变、发光描边、玻璃拟态、扫描线动画

视觉关键词更接近：深色 HUD、赛博朋克、雷达控制台。与目标参考图要求的“深色专业控制台、克制、去霓虹、去游戏 HUD、Map/Camera/Timeline/Workspace 为布局语言”存在方向差异。新版 Flutter 应保留深色专业感，但去除大量 glow、scanLine、玻璃卡和重复状态卡。

参考图审查说明：本地图片渲染工具不可用，未能生成可查看缩略图；通过图片尺寸（1536×1024）、主色分布（深蓝黑 `#041A34` 系、蓝灰面板、低饱和辅助色）与提示词约束确认其“深色控制台 + 地图/相机主体 + 非对称 Workspace”的方向。后续进入 UI 实施前应再补充一次真实屏幕截图核验。

---

## 9. 当前可以复用的代码

### 9.1 必须保留的 ROS2 车端能力

- `decision_controller.py`：唯一 `/cmd_vel` 发布者，安全仲裁逻辑不能绕过。
- `control_policy.py`：模式归一化、手动命令归一化、急停/近障/超时/速度比例等纯逻辑，可继续作为后端和网关的行为基准。
- `mode_manager.py`、`laser_obstacle_monitor.py`、`tcp_command_bridge.py`：现有运动意图入口与安全边界。
- `system_status_node.py`：机器人状态采集与 `/robot/status` JSON 发布。
- `web_app_node.py`：可作为边缘适配器原型，但需拆出业务 FastAPI；其状态快照、地图快照、视频流、相机所有权逻辑仍可复用。
- `web_camera.py`、`web_video.py`：相机打开/关闭、标注帧新鲜度管理。
- `map_assets.py`：PGM/YAML 地图保存、预览、质量统计、元数据。
- `yolo11_camera_node.py`、`color_tracker_node.py`、`object_follow_node.py`、`person_target.py`：AI 检测、颜色追踪、人物锁定。
- `config/decision.yaml`、`config/slam_toolbox.yaml`、`config/vendor_launch_profiles.yaml`、各 launch 文件。

### 9.2 可迁移到 Flutter 的纯逻辑

- `mapDisplay.ts`：占据栅格颜色、噪声去除、空洞填补、稳定 viewBox。
- `mapPoseSmoothing.ts`：地图位姿投影、平滑、SLAM 校正。
- `lidarHealth.ts`：健康状态文案映射。
- `videoState.ts`：视频加载/超时状态机。
- `robotApi.ts` 中 `RobotStatus` 字段结构可作为后端契约起点。
- Python 测试与前端测试可作为重构后的回归用例，避免重复造轮子。

### 9.3 可保留为兼容层

- 旧 `web/static/app.js/index.html/styles.css` 在新 Flutter 稳定前保留，作为 ROS2 实车现场调试入口，不提前删除。

---

## 10. 当前应该重构的代码

1. **React 前端**：整体替换为 Flutter Feature-first 架构，单页 HUD 改造成企业 Workspace。
2. **内嵌 FastAPI**：把当前 `web_app_node.py` 的 REST/WebSocket 拆成：
   - `management-api`（业务 FastAPI，PostgreSQL/Redis）；
   - `robot-gateway`（与 ROS2 边缘节点通信）；
   - `edge-adapter`（保留在 Jetson 上，只做机器人接入、任务执行与视频代理）。
3. **API 层**：升级为 `/api/v1`，增加 JWT/Refresh Token/RBAC、分页、错误码、幂等键、审计。
4. **WebSocket 层**：从 0.5s 全量快照改为事件化订阅，增加重连、心跳、按机器人订阅和断线快照校准。
5. **状态管理**：从 `useState` 散点状态改为统一 Riverpod/Bloc 状态模型。
6. **地图与相机 UI**：复用算法，重构为 Map 视觉中心、Camera 主视图、Overlay 检测框、Floating Robot Panel。
7. **配置持久化**：颜色/速度等配置不能继续只存浏览器 `localStorage`，应落到后端/Redis/车端配置。

---

## 11. 当前应该废弃的代码

以下代码在 Flutter 稳定并验收后逐步移除，不要在 Phase 1 立即删除：

- React 视觉层：`App.css` 中 HUD/glow/scanLine/玻璃态、`StatusCard/QuickResultCard/HomePage/HudPanel` 等调试面板样式。
- React 旧页面组织：`App.tsx` 的 `consoleOpen` 条件渲染、7 模式 Sidebar、四格状态卡、多格健康卡。
- 旧 vanilla JS 静态页：`ros2_ws/.../web/static/app.js/index.html/styles.css`，在旧系统退役后删除。
- 浏览器本地存储优先的 `colorPersistence.ts` 思路；后端应提供真实配置存储。
- 未版本化、无权限、无审计的 `/api/*` 直接暴露方式；改为受保护的 `/api/v1` 或网关内部协议。

---

## 12. 新 Flutter 架构

建议结构：

```text
flutter_app/
├── lib/
│   ├── core/
│   │   ├── theme/ router/ network/ storage/ websocket/ permissions/ widgets/
│   ├── auth/
│   ├── dashboard/          # Overview
│   ├── robots/             # Robots + Robot Detail
│   ├── patrol/             # Patrol + Patrol History
│   ├── missions/           # Missions + Mission Detail
│   ├── incidents/          # Incidents + Incident History
│   ├── analytics/
│   ├── maps/
│   ├── routes/
│   ├── notifications/
│   ├── users/ roles/ audit/ settings/ profile/
│   └── shared/
└── test/
```

关键约束：

- 统一状态管理，推荐 Riverpod 或 Bloc，二选一。
- 统一网络层：`AuthApi/RobotApi/PatrolApi/MissionApi/IncidentApi/MapApi/RouteApi/AnalyticsApi/SettingsApi/NotificationApi/AuditApi`。
- 统一 WebSocket 层：自动重连、心跳、连接状态、页面生命周期管理。
- UI 以 Map/Camera/Timeline/Workspace/Split View/Overlay/Drawer/Master-Detail 为核心，不采用四宫格/六宫格 KPI Card。
- 权限只在前端做展示和路由控制，真实权限由 FastAPI 返回 401/403 保证。

---

## 13. React → Flutter 迁移关系

| React 现有内容 | Flutter 目标位置 | 迁移策略 |
| --- | --- | --- |
| `App.tsx` 总控 | `AppShell + Router` | 拆为统一 Shell 与受权限路由 |
| `HomePage.tsx` | `Login` / `Overview` 入口 | 丢弃 HUD 形态，重新设计 |
| `Sidebar.tsx` | `core/widgets/Sidebar` | 从 ROS2 模式导航改为业务导航 |
| `HeaderBar.tsx` | `core/widgets/Header` | 改为面包屑/搜索/机器人在线/通知/头像 |
| `MapPanel.tsx` | `maps/MapWorkspace + RobotMarker` | 复用栅格/平滑算法，重做视觉 |
| `LiveCameraPanel.tsx` | `robots/CameraViewer` | 增加 AI Detection Overlay、FPS/REC |
| `LidarPanel.tsx` | 机器人详情局部组件 | 可作为辅助安全视图保留 |
| `ManualControlPanel.tsx` | `robots/CommandPanel` | 保留长按安全逻辑，重构视觉 |
| `ModeOperationPanel.tsx` | 命令面板/模式状态条 | 业务化表达，不暴露裸 ROS2 模式 |
| `ColorConfigPanel.tsx` | `robots` 或 `settings/AI Detection` | 配置接口迁移到后端 |
| `SystemSummaryPanel.tsx` | `Overview` Activity/Health 区 | 去掉卡片堆叠 |
| `robotApi.ts` | `core/network/api/*` | 换 `/api/v1` + token + 错误码 |
| `useRobotState.ts` | `dashboard/robot_state_provider` | 改为全局 Provider + 事件流 |
| `mapDisplay.ts` | `maps/occupancy_grid_renderer` | Dart 重写，保留测试 |
| `mapPoseSmoothing.ts` | `maps/pose_smoothing` | Dart 重写，保留测试 |

---

## 14. FastAPI 对接关系

当前实现 vs 目标实现：

| 层 | 当前 | 目标 |
| --- | --- | --- |
| 业务 API | 无 | 新 FastAPI：JWT、RBAC、用户/机器人/地图/路线/任务/异常/通知/统计/审计 |
| 实时缓存 | 无 | Redis：最新机器人状态、任务进度、通知投递 |
| 持久化 | 无 | PostgreSQL：任务、事件、异常、媒体元数据、审计、配置 |
| 机器人接入 | `web_app_node.py` 内嵌 FastAPI | Robot Gateway：订阅 `/robot/status`，接收任务，代理视频 |
| 命令边界 | `web_app_node → /manual_cmd → decision_controller → /cmd_vel` | 保持同一条安全链，FastAPI 不得直接发布 `/cmd_vel` |

目标实时链路：

```text
ROS2
  ↓
Robot Gateway
  ↓
Redis
  ↓
FastAPI WebSocket
  ↓
Flutter
```

高频 ROS2 原始数据不能直接写 PostgreSQL。任务/异常等低频业务事件才落库；机器人状态和检测帧走 Redis/WebSocket/视频代理。

---

## 15. 风险

1. **业务后端缺失**：没有用户/权限/数据库，Flutter 企业页面无法直接对接真实 API。
2. **巡检/运输未实现**：ROS2 端只有感知与控制，没有 Nav2/任务执行器，Patrol/Missions 页面容易做成假数据。
3. **权限容易被做成纯前端**：必须同时落地后端 RBAC、JWT、Refresh Token 和审计。
4. **参考图不可机械复制**：若按旧 React 的 HUD 方向延伸，会出现“改了个壳但仍像学生项目”。
5. **车端回归风险**：重构 API 时若改动 `decision_controller` 或新增 `/cmd_vel` 发布者，会破坏现有安全仲裁。
6. **Windows 与 Jetson 差异**：本地可编译 Flutter/FastAPI，但相机、ROS2、GPU、串口、地图保存需实车验收。
7. **未提交改动**：`tests/test_bytetrack_integration.py` 有未提交修改，`rollback-before-github-restore-20260630-010448.patch` 未跟踪；实施时不得覆盖。
8. **临时 pytest 目录权限异常**：多个 `.tmp_pytest*` 目录导致 Git 扫描报警，应只做读取，后续统一处理。

---

## 16. 建议实施顺序

先做契约与后端骨架，再逐步进入 Flutter 页面，避免 Flutter 页面依赖 Mock 长期存在。

```text
Phase 0：契约与后端骨架（建议先做，但不在前端 Phase 中占位）
  - FastAPI /api/v1
  - PostgreSQL + Redis + Alembic
  - JWT + RBAC
  - Robot Gateway 接口定义
  - ROS2 status schema 映射
  - /health/live、/health/ready

Phase 1：Flutter 基础框架
  - Theme / Router / AppShell / Sidebar / Header
  - Auth / API Client / WebSocket Client
  - Login + Overview Shell

Phase 2：Overview
  - Live Map / Robot Marker / Robot Status / Activity Timeline / Carousel

Phase 3：Robots
  - Robot List / Camera / AI Detection / Realtime Status / Activity

Phase 4：Patrol
  - Mission Timeline / Map Route / Progress / AI Inspection Stream

Phase 5：Missions
  - Mission Queue / Transport Map / Mission Detail / Transport Timeline

Phase 6：Incidents
  - Incident Timeline / Camera Frame / AI Analysis / Status Handling

Phase 7：Analytics
  - Patrol Activity / Utilization / Incident Trend / Coverage / Completion

Phase 8：Settings + Enterprise
  - Settings / Users / Roles / Permissions / Notifications / Audit / Maps / Routes / History
```

每个 Phase 必须完成：实现 → 编译 → 测试 → 运行 → 截图 → UI 检查 → 修复 → 更新文档 → 输出阶段报告，再进入下一阶段。

---

## 17. 视觉验收基线

每个核心页面至少检查 `1440×900`，并根据需要检查 `1920×1080`、`1280×800`。

重点：

- 不出现四宫格/六宫格 KPI Card；
- Overview 第一视觉为地图+机器人；
- Robots 第一视觉为 Live Camera；
- Patrol 第一视觉为地图+路线；
- Incidents 第一视觉为 Camera Frame；
- Analytics 是连续分析工作台，不是图表卡片堆；
- Settings 是左侧导航 + 右侧留白 Workspace；
- 所有页面共享同一 AppShell，避免每页风格漂移；
- 不使用紫蓝渐变、赛博朋克、游戏 HUD、大量发光和同质化圆角卡。

---

## 18. 后续必须补充的关键契约

- `/api/v1/auth/login`、`/api/v1/auth/refresh`
- `/api/v1/robots`、`/api/v1/robots/{id}`
- `/api/v1/maps`、`/api/v1/maps/{id}`
- `/api/v1/routes`、`/api/v1/routes/{id}`
- `/api/v1/patrols`、`/api/v1/patrols/{id}/actions/{action}`
- `/api/v1/missions`、`/api/v1/missions/{id}`
- `/api/v1/incidents`、`/api/v1/incidents/{id}/actions/{action}`
- `/api/v1/analytics/*`
- `/api/v1/notifications`、`/api/v1/users`、`/api/v1/roles`、`/api/v1/audit-logs`、`/api/v1/settings`
- WebSocket：`/ws/v1/robots/{robot_id}`、`/ws/v1/notifications`

这些接口应在 Phase 2 前至少形成 OpenAPI 契约与 mock-free 后端实现，不能在每个页面里长期使用静态假数据。

