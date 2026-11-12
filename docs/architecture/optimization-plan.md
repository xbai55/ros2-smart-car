# 总体架构图优化计划

范围：仅调整架构图与相关说明，不修改运行时代码；以当前 V4 分支源码为事实依据，沿用既有 Mermaid 内容基础，按用户要求统一保留黑白风格，不改变字体、边框和线条的朴素表达。

1. 阅读现有根 README、`docs/patrol-assistant-architecture.mmd`、历史总体架构 PNG 和手绘图；检查实际前端、业务接口、Agent、执行、网关、车端与 ROS 2 控制链。
2. 建立代码依据表，区分部署边界、业务调用、HTTP/WS/SSE、ROS 2 Topic/Action、传感输入与执行反馈。
3. 将图改为横向分区；主机保留 Agent 编排、共享业务执行与状态管理、数据存储，通信适配位于主机内；车端分别表达视觉、建图、定位、导航和安全控制；物理硬件单独成区。
4. 更新现有 Mermaid 源文件，增加可精确编辑的 Draw.io 源文件与 SVG；从同一布局数据导出高清 PNG。保留文字可编辑，不将全图栅格化后嵌入 SVG。
5. 核对模块及连线、中文、文本边界、节点遮挡、长宽比与缩放可读性，必要时调整并重新导出。
6. 输出简短修改说明和代码依据，README 引用最终图及源文件；检查提交范围、拉取远程变更、普通推送 main，并核对远程提交。

实施要点：AssistantWorker 是助手计划执行器，普通任务通过 navigation_tasks 等共享执行入口并由 task_reconciler 对账。图中以“持久任务执行与状态管理”组织这些实际组件，不将全部任务误画成 AssistantWorker 的输入。底盘软件驱动与电机硬件分开，Nav2 速度经 /navigation/cmd_vel 进入 decision_controller，最终才发布 /cmd_vel。
