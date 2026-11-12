# 2026-11-12 主分支源码更新记录

## 更新范围

以 `feature/insightrover-v4-agent` 的 V4 开发线为基础更新 `main`，包含此前的 Agent 助手、控制租约、跨端诊断、YOLO11 倒地专项模型接入，以及 4.0.2 中文目标映射与搜索拒绝处理修复。Windows 桌面组件版本保持 4.0.2，本次不生成新的安装包或 Git 标签。

本次新增提交包含：

- 重写根目录 README，统一当前系统定位、架构、目录、环境、启动方式、配置、部署、模型、验证边界和文档索引。
- 纳入已有的建图会话锁竞争修复：SLAM 启动期间，状态、地图回调和状态查询避免阻塞等待同一把锁。
- 保留慢速 SLAM 启动的并发回归测试，验证回调能够及时返回，启动结束后恢复接收地图与状态。

本地未跟踪的演示稿和 `releases/v4.0.1`、`releases/v4.0.2` 交付目录未纳入本次提交。

## 本次验证

| 检查 | 结果 |
| --- | --- |
| 车端离线回归 `python -m pytest tests -q -x` | 477 passed，5 subtests passed |
| 后端与桌面回归 `python -m pytest tests ../desktop/tests -q -x` | 236 passed，1 skipped |
| 前端 `npm test` | 122 passed |
| 前端 `npm run build` | TypeScript 与 Vite 生产构建通过 |
| README 本地链接及代码围栏 | 通过 |
| `git diff --check` | 通过 |

Python 检查使用仓库 `output/` 下的独立临时目录，在正常本机环境完成。最初受限环境运行出现文件访问错误和停滞，已中断，以上结果为后续完整运行的结果。日志保留在本机 `output/publish-main-vehicle-check.txt` 和 `output/publish-main-backend-check.txt`，不提交原始运行日志。

保留依赖弃用警告、1 项平台相关跳过和 Vite 大分包提示。本次没有连接真实车辆、调用外部模型、部署车端或执行运动测试；建图修复通过离线回归，不表示完整移动建图问题已经解决。
