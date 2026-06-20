# ROS2 Smart Car Web Console

React + TypeScript + Vite 实现的 ROS2 智能小车大屏控制台前端。当前使用静态 mock 数据，界面结构已经按后续接入 WebSocket、摄像头视频流、雷达点云和控制接口拆分。

## 运行

```bash
cd web-console
npm install
npm run dev
```

默认访问：

```text
http://127.0.0.1:5173/
```

生产构建：

```bash
npm run build
```

## 主要文件

```text
src/App.tsx                         页面状态和整体布局
src/App.css                         深色 HUD、玻璃拟态、雷达和响应式样式
src/data/mockData.ts                模式、状态、检查项、雷达点云 mock 数据
src/components/Sidebar.tsx          左侧模式导航与 WebSocket 状态
src/components/HeaderBar.tsx        顶部标题与急停按钮
src/components/LiveCameraPanel.tsx  现场画面面板
src/components/ManualControlPanel.tsx 手动遥控和速度滑块
src/components/LidarPanel.tsx       SVG 雷达扫描可视化
```

后续接真实 ROS2 数据时，可以先替换 `mockData.ts`，再把 `App.tsx` 中的本地状态换成 WebSocket 消息和控制接口调用。
