# 转弯速度、建图距离与完整输入记录

网页“运动参数”新增独立转弯速度，范围为 0.05–0.60 rad/s，默认 0.15 rad/s。手动与建图共用，不再乘速度比例；原来的比例仍用于手动、建图的直行和横移。自动识别转向、跟随与导航的既有策略不受此设置影响。应用转弯速度时，网页先停止当前按住行驶操作。

SLAM 页提供 0.5、1、3、6 m 四个建图距离，默认 3 m。点击“保存建图距离”只保存下次启动设置，不重启建图、不清除地图。网页分别显示“下次建图”和“本轮”距离。0.5、1 m 会减少可用于定位的环境结构，界面会给出简短提示。

设置通过 POST `/api/mapping/settings` 保存至车端 `~/.ros/insightrover/motion-mapping.json`，重启服务后读取。新建图会话复制已安装的 SLAM 参数并生成独立 `slam-params.yaml`，只覆盖该会话的 `max_laser_range`，不修改共享 YAML。本轮开始后再保存的距离只影响下一轮。

## 自动记录

每次从网页开始建图时，先启动完整输入记录，确认已订阅雷达、静态 TF 和控制话题，再重新发布当前模式、停止命令及速度设置，随后启动 SLAM。静态 TF 和转弯速度使用持久订阅，保证能记录启动前已存在的值。普通模式切换入口不能绕过录制创建建图会话。记录目录默认是：

```text
~/.ros/insightrover/mapping_logs/<时间>_<session_id>/
  session.json       # 会话设置、开始/结束时间、完整性、各话题条数与缺失话题
  events.jsonl       # 记录开始/结束与参数修改
  status.jsonl       # 每次状态回调，包括地图位姿、里程计速度、控制速度和链路状态
  slam-params.yaml   # 本轮 SLAM 实际使用的参数
  slam.log           # 本轮 SLAM 输出
  recorder.log       # rosbag 记录进程输出
  qos.yaml           # 静态 TF 的持久订阅配置
  inputs/            # 完整 ROS 消息，sqlite3 rosbag 与 metadata.yaml
```

记录话题包括 `/scan`、`/odom_raw`、`/odom`、`/imu/data_raw`、`/imu/data`、`/tf`、`/tf_static`、`/cmd_vel`、`/manual_cmd`、`/robot/mode`、`/robot/speed_scale`、`/robot/turn_speed`、`/robot/status`、`/map`、`/parameter_events`。

原始 `/scan` 包含完整距离数组和每束时间信息；原始/融合里程计包含姿态与协方差；IMU 和 TF 保留原始 ROS 时间戳。网页状态中的简化雷达点不替代这些完整记录。某个可选话题不存在时会列入 `missing_topics`；关键话题没有记录、记录进程异常或元数据缺失时，不会标记为完整。

退出建图模式、切换导航、重新开始建图和关闭 Web 节点时，记录进程通过 SIGINT 收尾并等待元数据落盘。历史目录保留，不自动删除。SLAM 异常退出也会终止本轮记录并标记错误。至少剩余 512 MB 才开始记录；运行中不足 256 MB 时收尾并明确标记中断，避免静默丢失数据。网页不增加日志列表、查看器或下载入口。

## 查看记录

在车端加载现有 ROS 环境后，可以直接查看摘要或导出某段完整输入：

```sh
python3 scripts/inspect_mapping_log.py <本轮日志目录>
ros2 bag info <本轮日志目录>/inputs
python3 scripts/inspect_mapping_log.py <本轮日志目录> --topic /odom --topic /imu/data --start 180 --duration 10 --output /tmp/turn-inputs.jsonl
```

`--start` 是相对本轮记录开始的秒数。导出的每条记录包含话题、消息类型、录制时间及完整消息内容。摘要查看不需要 ROS 库，完整消息导出需要 rosbag2_py、rosidl_runtime_py 与 rclpy。

## 验证边界与更新

本地已验证设置校验、持久化、独立转弯速度与停车条件、当前地图保留、会话参数隔离、记录启动顺序和收尾、关键输入缺失标记。网页在隔离模拟服务上验证了预设、应用、距离下轮生效及 390 px 布局。

部署必须同时更新 decision_controller、system_status_node、web_app_node 及新增模块，并安装 package.xml 中的 rosbag2 依赖。不能只替换网页，否则新增控件会提示需要更新车端。

2026-10-20 已在 `192.168.1.106` 的新目录 `/home/jetson/ros2-smart-car-mapping-settings-20261020` 部署并启动服务 `smart-car-mapping-settings-20261020.service`。本地启动入口已指向该版本，本地网页代理已同步新 IP；旧部署目录保留。

静止验收中，四种距离设置均被车端接受，实际 SLAM 节点读取的 `max_laser_range` 为 3.0；转弯设置及重启后持久值为 0.15 rad/s。约 15 秒的记录正常收尾，15 类话题全部有数据，`complete=true`、`missing_topics=[]`。实际解码验证了 106 帧雷达（每帧完整 1080 槽位）、136 条融合里程计、303 条 TF 和 272 条控制速度；控制速度全部为零。原始里程计和原始 IMU 也各有 136 条记录。

验收日志目录为 `~/.ros/insightrover/mapping_logs/20261020_175054_08996310bbb847df8b3392c86c042f08/`。服务再次重启后仍读取持久设置，小车留在停止模式。尚未做行驶中的转弯速度或地图质量验收，静止验证不能替代该项。
