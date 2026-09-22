# InsightRover｜智巡 React 前端重构审计（Phase 1）

> 依据《InsightRover_智巡_前端视觉与交互重构实施计划_新版.docx》与首页视觉预览图，对 `web-console/`（React）做只读审计。
> 本轮结论：当前前端 = `web-console/`（Vite + React 19 + TS + lucide-react），即“左侧 Sidebar + Dashboard + 大量 Card + ROS 控制台”。目标：顶部业务导航 + 工作台 + 对象详情 + 专业机器人工作区。

## 1. 当前架构
- 构建：Vite 6 + React 19 + TypeScript 5.9 + lucide-react，无路由、无 UI 组件库、无 TanStack Query / Zustand。
- 入口：`src/main.tsx` → `src/App.tsx`（单页，`consoleOpen` 状态在 `HomePage` 与“Sidebar+Console”间切换）。
- 样式：单文件 `src/App.css`（约 47KB，深色 HUD 风）。
- 数据：`src/robotApi.ts`（REST client + 类型）、`src/useRobotState.ts`（HTTP 快照 + `/ws/status` + 1.5s 重连）。
- 业务常量：`src/data/consoleData.ts`（7 种模式、颜色预设、手动指令）。

## 2. 当前页面
- `HomePage`：落地页（品牌/模式/前方距离/视频源 4 指标 + 进入控制台 + 急停）。
- `Console`：`Sidebar`（左侧模式导航）+ `HeaderBar` + `status-grid`（4 张 StatusCard）+ `dashboard-grid`（LiveCameraPanel / SystemSummaryPanel / ModeOperationPanel / MapPanel / LidarPanel）+ `PreDriveChecklist`。

## 3. 当前 API（robotApi.ts，继续复用）
- REST：`/api/status`、`/api/map`、`/api/mapping/restart`、`/api/mapping/save`、`/api/mode`、`/api/command`、`/api/emergency-stop`、`/api/speed`、`/api/mode-obstacle-stop-distance`、`/api/color-target`。
- 流：`/video_feed`（MJPEG 图帧）。
- 类型：`RobotStatus`（mode、emergency_stop、front_distance、detection、lidar/map/odom/cmd_vel/tf 健康、map_pose、mapping_quality、color_target、radar_points、speed_scale、nodes）。

## 4. 当前 WebSocket（复用）
- `/ws/status`：推送 `RobotStatus` 全量快照；客户端先 `GET /api/status` 再升 WS，断线 1.5s 重连；`normalizeRobotStatus` 做缺省合并。

## 5. 当前状态管理
- `App.tsx` 多个 `useState` + `useRobotState`（status/connection/error + 控制 actions）。无全局 UI store、无服务端数据缓存层。

## 6. 当前组件体系
- 布局：`Sidebar`、`HeaderBar`、`HudPanel`。
- 展示：`StatusCard`、`QuickResultCard`、`SystemSummaryPanel`。
- 专业：`MapPanel`（SVG 占据栅格 + SLAM 位姿平滑 + 图层/质量）、`LiveCameraPanel`（视频状态机 + HUD）、`LidarPanel`、`ManualControlPanel`（方向盘）、`ModeOperationPanel`、`ModeFocusPanel`、`PerceptionHealthPanel`、`PreDriveChecklist`、`ColorConfigPanel`。
- 工具：`mapDisplay.ts`（栅格上色/降噪/补缝）、`videoState.ts`、`mapPoseSmoothing.ts`、`colorPersistence.ts`。

## 7. 当前视觉体系
- 深色 HUD/控制台风：`#0b2237` 系地图配色、`#19dfff` 高亮、左右分栏、多 Card。首页信息密度低、无对象详情/时间线/工作台结构。

## 8. 可复用
- `robotApi.ts` 全部 REST/类型；`useRobotState.ts` 的 WS 状态机；`/video_feed` 状态机；`mapDisplay.ts` 栅格渲染；`ManualControlPanel` 方向盘；`consoleData.ts` 模式/预设；`HudPanel` 的“kicker+标题+action”结构。

## 9. 必须重构
- 永久左侧 `Sidebar` → 顶部 `GlobalHeader`。
- 落地页 → 工作台首页（Hero → 地图/视频/机器人状态 → 四业务区 → 状态条）。
- 技术指标卡片堆叠 → 业务对象 Panel。
- 无路由 → 多页面对象路由。
- 散落状态 → 分层数据接入（service/adapter/store）。

## 10. 必须废弃
- `Sidebar.tsx`（永久侧边栏）；旧 `App.css` 的 HUD 卡片样式（停止导入，文件保留）；“ROS2 Web Console”标题文案。

## 11. 新架构
- `Router`（hash）+ `GlobalHeader`（Brand/一级导航/Mega Menu/搜索/通知/用户）。
- 数据：`services/adapters`（mock seam）+ `services/api`（复用 robotApi）+ `hooks/useRobotStream`（WS）+ `hooks/useData`（Query 等价）。
- 状态：`stores/uiStore`（useSyncExternalStore，等价 Zustand：选中对象/图层/弹层）。
- 组件：`navigation` / `workspace` / `robot` / `task` / `incident` / `ui` / `shared`。

## 12. React 依赖说明（差异）
- npm CLI 损坏、网络受限，无法新增 `react-router-dom`/`@tanstack/react-query`/`zustand`/`shadcn`/`echarts`。
- 采用 React 内置能力实现等价层：hash Router、`useSyncExternalStore` store、`useData` 查询 Hook、自建 UI 原语与 SVG 图表；组件 API 保持稳定，后续可无缝替换。lucide-react 已存在，继续复用。

## 13. FastAPI 对接关系
- 机器人实时（status/map/video/控制）走现有 ROS2 Web 服务（`/api/*`、`/ws/status`、`/video_feed`），不改变 decision_controller 的 `/cmd_vel` 唯一仲裁边界。
- 业务对象（tasks/incidents/maps/routes/stats/system）当前由 mock adapter 提供，接口形态对齐 FastAPI `/api/v1/*`，就绪后只替换 adapter 实现。

## 14. 风险
- npm 不可用导致无法引入重型依赖（用等价层规避，已记录差异）。
- 后端业务接口未接（mock 集中在 adapter，避免组件散落 mock）。
- 地图/视频依赖 ROS2 服务在线；离线时需 clear 的 offline/empty 态。

## 15. 建议实施顺序
Phase 1 审计（本文）→ Phase 2 基础能力 → Phase 3 App Shell → Phase 4 首页 → Phase 5 地图/机器人 → Phase 6 任务/异常 → Phase 7 地图/路线/数据/系统 → Phase 8 动画/响应式/状态 → Phase 9 build/lint/test 验收。
