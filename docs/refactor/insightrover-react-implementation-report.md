# InsightRover｜智巡 React 前端重构 — 实施报告（V2.0 计划）

## 关键决策
- 本轮重构目标为仓库内 **React 前端 `web-console/`**（原“ROS2 Web Console”：`package.json`、`src/`、左侧 Sidebar + Dashboard + ROS 控制台），与《InsightRover_智巡_前端视觉与交互重构实施计划_新版.docx》的工程栈（package.json、shadcn/TanStack Query/Zustand/ECharts、npm 脚本）一致。
- 仓库另存在上一轮产出的 `flutter_app/`（未纳入本轮；本轮计划书为 React 技术栈）。旧 ROS 控制台以 `src/legacy/RosConsoleApp.tsx` 备份保留，未删除。

## 已完成
- 顶部 Global App Shell：深色 sticky Header（56px）、品牌区、一级导航、Mega Menu、GlobalSearch（Ctrl/Cmd+K，分组结果）、NotificationCenter、UserMenu；**永久左侧 Sidebar 已移除**。
- 工作台首页 `/`：Header → Hero（品牌/系统状态/时间/机器人视觉主体/在线·异常·任务汇总）→ 主工作区（实时地图 2.3fr + 实时视频 + 机器人状态 + 快速控制）→ 底部四区（任务中心/异常告警/最近动态/系统概览）→ 底部 RobotStatusStrip。
- 页面：`/robots`、`/robots/:id`（概览/运行/任务/异常/遥测）、`/robots/:id/run`（深色运行工作区）、`/tasks`、`/tasks/:id`、`/incidents`、`/incidents/:id`、`/maps`、`/maps/:id`、`/routes`、`/routes/:id`、`/analytics`、`/system`、`/assets`、`/settings`（用户/角色/通知/审计/个人中心）。
- 分层地图画布：OccupancyGrid 墙体 + 巡检路线 + 机器人位姿 + LiDAR 扇区 + 异常点，图层开关/缩放/图例。
- 相机画布：`/video_feed` 状态机 + AI 检测框 overlay + 摄像头切换条。
- 状态体系：loading(Skeleton)/empty/offline/error/degraded 均有明确表现。
- 14 条路由 + 404 兜底；1440×900 全页面截图验收。

## 复用
- API：`robotApi.ts` 全部 REST（/api/status、/api/map、/api/mode、/api/command、/api/emergency-stop、/api/speed、/api/mode-obstacle-stop-distance、/api/color-target、/api/mapping/*）。
- WebSocket：`/ws/status` 状态机（HTTP 快照 + WS + 1.5s 重连）重构为 `hooks/useRobotStream.ts`。
- 组件/常量：`consoleData.ts`（modes）、`mapDisplay.ts`、`videoState.ts`；旧 `MapPanel/LiveCameraPanel/ManualControlPanel` 保留为 legacy 备份。
- 数据：业务对象由 `services/adapters.ts` mock 集中提供（mock 仅在 adapter 层）。

## 新增
- 页面：`pages/*.tsx`（14 路由 + 详情）。
- 组件：`navigation/GlobalHeader.tsx`、`workspace/HomeSections.tsx`、`robot/{RobotMapCanvas,RobotCamera,RobotStatusPanel,RobotControl,RobotRunWorkspace}.tsx`、`task/MissionStepper.tsx`、`ui.tsx`、`shared.tsx`。
- 数据层：`lib/{router,store,cn}.ts`、`stores/uiStore.ts`、`hooks/{useData,useRobotStream}.ts`、`services/adapters.ts`、`types/domain.ts`。
- 设计系统：`styles/insight.css`（深色导航 + 浅色业务空间 + 深色运行工作区）。

## 验证
- TypeScript：`node node_modules/typescript/bin/tsc --noEmit` → 0 错误。
- 构建：`node node_modules/vite/bin/vite.js build --configLoader native` → 成功（1608 模块，CSS 42KB / JS 317KB）。
- 视觉：Edge 无头 1440×900 截取 15 页，PIL 校验无空白/404；首页结构（深色 Header/浅色 Hero/地图墙体/深色相机/状态面板）符合预览图信息层级。
- 运行时：无应用级 JS 报错（仅 Edge 自身噪声）。

## 未完成 / 差异（原因）
- 未引入 `react-router-dom`/`@tanstack/react-query`/`zustand`/`shadcn`/`echarts`：本机 npm CLI 损坏（`npm-cli.js` 缺失）且网络受限，改用 React 内置能力实现等价 hash Router、`useSyncExternalStore` store、`useData` 查询 Hook、自建 UI 原语与 SVG 图表；组件 API 稳定，可后续无缝替换。
- `npm run lint`/`npm test` 无法执行：`package.json` 无 lint/test 脚本、vitest 未安装。已用 `tsc --noEmit` + `vite build` 替代；`tests/*.test.ts` 保留未运行。
- 后端业务接口（tasks/incidents/maps/routes/stats/system）仍由 mock adapter 提供，真实 FastAPI 就绪后只需替换 adapter 实现。
- 视觉图无法在模型侧直读（view_image 返回 unsupported），已用 PIL 色彩/密度校验 + Codex 面板人工复核替代。
- 首页截图 `home-1440x900.png` 与 `home.png` 为同一页面（后者为循环统一命名）。

## 截图
`docs/refactor/screenshots-react/`：home、robots、robots_r-001、robots_r-001_run、tasks、tasks_t-101、incidents、incidents_i-301、maps、maps_m-001、routes_rt-001、analytics、system、assets、settings（1440×900）。

## 第三轮：去卡片化 · 登录页 · Split View（Master/Detail）

### 目标
严格按《完整前端预览图》把对象页从“详情页卡片墙”重构为“左对象列表 + 右连续工作区”，并补齐登录页入口。

### 改动
- 新增 `/login` 路由：`App.tsx` 在渲染 `GlobalHeader` 前拦截 `/login`，全屏渲染 `LoginPage`（左品牌/机器人视觉 + 右克制登录区）；`GlobalHeader` 用户菜单“退出登录”指向 `#/login`。
- 新增可复用主从组件：`components/shared.tsx` 的 `SplitView`（左 `.split-list` + 右 `.split-detail`）与 `ObjectItem`（左列表项：图标/主副文案/状态徽标/选中态）。
- 机器人详情 `/robots/:id`：左机器人列表 + 右工作区；“概览”由四卡片 `overview-grid` 改为连续工作区——`workspace-stats` 内联状态条 + `ws-split`（左大尺寸实时地图 + 右实时相机）+ 当前任务列表。
- 任务详情 `/tasks/:id`：左任务列表 + 右工作区；“概览/执行/时间线”去掉 Panel 卡片，改为 `workspace-stats` + `ws-section`（进度 / Stepper / 时间线）。
- 异常详情 `/incidents/:id`：左异常列表 + 右工作区；现场证据（AI 检测框大图）作为主视觉，与异常信息/处理时间线并置，不再四卡片。
- 地图/路线详情保持“地图画布 + 右侧属性面板”工作区（符合预览图第 07 节“浮动工具栏 + 属性面板”），未改动。
- 样式：`styles/insight.css` 新增 `.obj-item` 按钮复位与 `.obj-item-icon`、`.ws-split-map`、`.ws-media`/`.ws-media-cell`；`.panel` 阴影清零、边框弱化。

### 验证
- `node node_modules/typescript/bin/tsc --noEmit` → 0 错误。
- `node node_modules/vite/bin/vite.js build --configLoader native` → 成功（1609 模块）。
- Edge 无头截图：`docs/refactor/screenshots-react/round3/` 含 01-login / 02-home / 03-robot-detail / 04-task-detail / 05-incident-detail（1440×900），以及 06-home-1920 / 07-home-1280 / 08-robot-1280。
- PIL 校验：各页顶部为深色 Header（亮度 ~57）、地图/相机/证据区为深色媒体、无空白页或 404。

### 安全链
- 未新增 `/cmd_vel` 直连；急停、雷达避障、速度限制仍走原 `robotApi.ts` 后端接口，由车端 `decision_controller` 仲裁。

