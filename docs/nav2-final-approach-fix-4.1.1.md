# Nav2 末段到点容差修复（4.1.1）

本轮只读查询实车参数、分析既有记录、修改本地代码并运行离线测试；未部署、未修改运行参数、未重启服务、未发送导航目标或速度。基准 be940f6，原有展示稿与发行目录保持原样。

## 已确认的配置缺陷及现场证据

2026-11-17 实车 GetParameters 读取：general_goal_checker.xy_goal_tolerance=0.15、yaw_goal_tolerance=0.20、stateful=true；FollowPath.xy_goal_tolerance=0.25、trans_stopped_velocity=0.03；critics 包含 RotateToGoal。项目 navigation.yaml 只覆盖 Goal Checker 容差，launch 的递归合并从车端 Humble 默认文件继承了 DWB 的 0.25。两者是独立参数。

Humble RotateToGoalCritic.prepare() 将 in_window 和 rotating 状态锁存；进入自身 XY 窗口、实测平移速度下降到停止阈值后，scoreTrajectory() 拒绝所有含非零平移的轨迹。于是 0.15～0.25 米区间存在“Goal Checker 不允许到达，critic 又不允许继续平移”的配置矛盾。源码：https://github.com/ros-navigation/navigation2/blob/humble/nav2_dwb_controller/dwb_critics/src/rotate_to_goal.cpp 。该机制独立于其他轨迹评分，足以导致此类困住；未取得逐轨迹评估记录，不能声称历史每条轨迹均已观测到该拒绝文本。

对 retry-result.json 按实际 map 位姿与 goal 重算（不使用 distance_remaining 替代欧氏距离）：目标 (0.4510505,-0.1826304)，yaw=0.1819；首个仅转动样本 XY 误差约 0.17104 米、yaw 误差 0.0108 弧度；随后样本 XY 误差范围 0.15333～0.16945 米、yaw 误差范围 0.0001～0.054 弧度。yaw 已满足要求，XY 始终在 0.15 外。样本 50：XY=0.156248 米、yaw=0.001 弧度、剩余路径=0.153513 米，三者不能混为一谈。

这构成已确认配置缺陷与高置信现场主因；修复后实车到点仍须另行验收。

## 最小修复

1. config/navigation.yaml 显式设 FollowPath.xy_goal_tolerance=0.12。保持 Goal Checker 0.15 米、0.20 弧度不变；3 厘米窗口余量用于避免在更外层提早锁存旋转，不能视为已验证的定位误差上界。
2. navigation.launch.py 在参数合并后、节点构造前检查终点窗口：要求正有限值、明确 Goal Checker 插件、DWB 窗口不大于任一 Goal Checker XY 窗口。不满足立即拒绝启动，防止继承默认值再次制造冲突。
3. 新增 test_navigation_goal_tolerances.py：继承冲突回归、非法值拒绝、观测样本锁存条件、实际 launch 函数生成的最终 YAML。没有更改租约交接、保护、控制输出或进度检查器。

## 速度链路与次要假设

链路为 DWB /navigation/raw_cmd_vel → velocity_smoother /navigation/cmd_vel → on_navigation_command → decide_motion 限速 → 防撞 → /cmd_vel → /odom。当前记录包含最终 cmd_vel、决策请求/输出和 odom，缺少故障当时 raw_cmd_vel 与 cmd_vel_smoothed 的逐帧同步原始记录，不能完整倒推上游。

137 个末段纯转动样本：最终角速度绝对值中位数 0.0395 rad/s、决策请求中位数 0.0394736842 rad/s，odom 实测角速度中位数约 0.002 rad/s。决策层没有把较大的角速度统一截成该微值；Humble 默认 vtheta_samples=20 与 max_vel_theta=0.75 的离散步长也与 ±0.0394736842 候选值吻合，但尚不能仅凭数值确认微转向由 DWB 而非上游平滑阶段产生。低角速度底盘响应不足/死区仍待验证；即使 yaw 没有死区，本次 yaw 已在 0.20 内，仍不能消除 XY 逻辑冲突。因此不增加最低角速度，不扩大速度或超时。

后续最小采集：同一 ROS 时钟记录 /navigation/raw_cmd_vel、/navigation/cmd_vel、/cmd_vel、/odom、/amcl_pose、/tf、/local_plan_evaluation、目标和 /robot/status，保留消息时间与接收时间；缺少 evaluation 时先在仿真确认该 DWB 发布接口，不能把事后静止采样充当历史证据。

## 代价地图与进度检查

main 无 local static_layer，当前 local costmap 加入了 /navigation/map 静态层；两者 inflation_radius=0.55、cost_scaling_factor=3.0，实测矩形尺寸仍不改变。静态层可能改变终点附近轨迹成本，但历史没有同步成本图/评分，无法据此排除其贡献；本轮保持配置不变。RotateToGoal 在旋转锁存后直接拒绝平移，不依赖 BaseObstacle 的得分，因此优先修复已证实矛盾。

SimpleProgressChecker 只按 XY 位移是否超过 required_movement_radius=0.10 更新基线，原地旋转不重置其 20 秒计时。在前进停止后，Failed to make progress 是无有效平移的结果，不是本轮优先根因。源码：https://github.com/ros-navigation/navigation2/blob/humble/nav2_controller/plugins/simple_progress_checker.cpp 。本轮未删除、放宽或延长此检查。

## 验证结果和边界

实际从车端获取的 /opt/ros/humble/share/nav2_bringup/params/nav2_params.yaml，与部署覆盖文件合并，复现 0.25/0.15 冲突；与修改后的覆盖文件合并，得到 0.12/0.15，并通过启动检查。Goal Checker、进度检查、两套代价地图与 velocity_smoother 与部署配置逐字段相同。原始及合并证据位于本地 output/nav-final-approach-fix/。

专项 9 项通过；车端全套 574 项及 5 个子测试通过，排除两项已有基线失败 test_failed_slam_restart_cannot_restore_old_registration、test_temporary_disk_error_retries_the_same_event_and_picture；后端全套 273 项通过。没有运行真实 Nav2 仿真或实车到点验收；锁存测试为基于官方实现的边界模型，不能替代加载实际 C++ 插件。

部署与实测需另行授权。到时先重新加载导航栈并读取实际参数为 0.12/0.15（critic 初始化缓存参数，不能以源码修改代替生效确认）；低速短距测试需同步采集完整速度链路，检查 XY 不在 0.15 外因 RotateToGoal 提早停止平移。分别验收 yaw 已对齐和未对齐目标，仍保留急停/失联/防撞停车，记录最终 XY、yaw、action succeeded 和停车。若仍失败，分析当帧 trajectory evaluation 与静态/膨胀成本，不预先放宽容差、超时或几何尺寸。


## 随后授权部署与一次实测

用户另行授权部署及现场低速测试。车端新版本目录 insightrover-v411-goal-tolerance-1405c4545e8e，程序版本仍为 4.1.1；原版本和设置已备份。实际运行 GetParameters 确认 DWB=0.12、Goal Checker=0.15/0.20、进度检查=0.10/20.0，未放宽其他参数。只更新车端，未重装客户端。

前方约 0.30 米的低速目标启动成功，Nav2 日志在 1794892024.633597 报 Reached the goal!，随后 1794892024.664206 报 Goal succeeded。本轮没有新的 Failed to make progress，里程计位移约 0.1552 米；现场确认确实前进并停住，没有持续原地微转。由于原生到点容差为 0.15 米，不能把约 15.5 厘米行驶解读为必须移动到目标中心才成功。

完整外部验收仍未通过：脚本在原生成功后读取的地图位姿误差为 0.1557585 米，较 0.15 米外部阈值大约 5.76 毫米，记录保留为 passed=false，没有调整阈值或覆盖原始结果。两个时刻/不同数据源的边界误差与 Goal Checker 的 stateful 行为需后续对齐，不能把该值当作原生判定瞬间的内部误差。脚本清理时停车 API 曾未确认；独立重发停车后返回 controller_confirmed=true、stationary_confirmed=true，实测速度为零、无人持有控制权。此回执时序问题未在本轮修改。

本次同步记录四级链路：raw_cmd_vel 与平滑后速度最高线速度约 0.1611 m/s、角速度 0.1974 rad/s；最终输出最高线速度约 0.0420 m/s、角速度 0.04688 rad/s，符合本次输出监测界限；里程计单样本峰值不同，不应等同于指令上限。监测没有报超速、超时或异常位移。原设置已恢复，最终 stop、零速度、控制权释放。

本轮证明原生 Nav2 的提前只旋转卡住问题在该短距目标中未复现，已得到一次原生成功与现场确认；不等于多目标、不同朝向、动态绕障和稳态位置误差全项验收。原始记录在 output/nav-goal-tolerance-deploy/，包括 navigation-result.json、speed-chain.jsonl、原生导航日志、实际参数及独立停车结果。
