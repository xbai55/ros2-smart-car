# ros2-smart-car

本仓库用于保存 Yahboom ROSMASTER X3 智能小车综合设计相关代码和文档。当前重点是完成“进阶式挑战性综合项目 II”中除机械臂外的基础功能：ROS2 控制、雷达避障、摄像头感知、YOLO11 识别、HSV 颜色追踪、目标跟随、Web/手机端控制、Docker 化部署和 Jetson 实车运行流程。

## 自研功能边界

厂家 Yahboom 程序提供底层硬件驱动和参考功能，例如底盘驱动、雷达、Astra 相机、SLAM/Nav2、Rosmaster 示例程序。本仓库不把这些现成能力说成完全自研，而是在其基础上实现：

- ROS2 决策控制与安全策略：模式切换、急停、命令超时停车、雷达近障停车。
- 感知融合：YOLO11 识别结果、HSV 颜色追踪、目标偏移和 `/lane/offset` 融合。
- Web/PWA 控制端：手机或电脑浏览器遥控、切模式、看视频流和状态。
- 容器化与部署：Dockerfile、Jetson 原生运行脚本、启动编排。

机械臂抓取、多舵机协同不在当前实现范围内，只保留后续扩展边界。

## 目录结构

```text
ros2_ws/src/smart_car_decision/  ROS2 自研功能包
ros2_command/                    PC 端 PyQt6 TCP 遥控工具
src/                             STM32CubeIDE 基础外设实验
scripts/                         Jetson 和 Docker 运行脚本
Dockerfile                       ROS2 Humble 容器化环境
```

## ROS2 节点

`smart_car_decision` 包包含以下节点：

- `mode_manager`：发布 `/robot/mode` 和 `/robot/emergency_stop`，默认 `stop`。
- `decision_controller`：订阅 `/scan`、`/vision/detection`、`/lane/offset`、`/manual_cmd`、`/robot/mode`，输出 `/cmd_vel`。
- `laser_obstacle_monitor`：把 `/scan` 简化为 `/obstacle/front`。
- `yolo11_camera_node`：摄像头 + YOLO11，发布 `/vision/detection` 和 `/vision/object_offset`。
- `color_tracker_node`：HSV 颜色追踪，发布 `/vision/color_target` 和 `/lane/offset`。
- `object_follow_node`：在 `object_follow` 模式下把 `/vision/object_offset` 转发为 `/lane/offset`。
- `system_status_node`：汇总状态为 `/robot/status` JSON。
- `web_app_node`：FastAPI + 静态 PWA，提供手机/电脑控制台。
- `tcp_command_bridge`：兼容旧 TCP 遥控工具，监听 `9999` 并发布 `/manual_cmd`。

## 公开话题

```text
/robot/mode              std_msgs/String
/robot/mode/set          std_msgs/String
/robot/emergency_stop    std_msgs/Bool
/robot/emergency_stop/set std_msgs/Bool
/robot/speed_scale       std_msgs/Float32
/robot/status            std_msgs/String(JSON)
/vision/detection        std_msgs/String
/vision/object_offset    std_msgs/Float32
/vision/color_target     std_msgs/String(JSON)
/lane/offset             std_msgs/Float32
/manual_cmd              std_msgs/String
/cmd_vel                 geometry_msgs/Twist
```

默认安全策略：急停、`stop` 模式、雷达近障碍、手动命令超时、无有效输入时都停车。`mapping` 和 `navigation` 模式默认不直接发布运动速度，避免与厂家 SLAM/Nav2 控制链路抢 `/cmd_vel`。

## Jetson 原生运行

把仓库放到 Jetson 后执行：

```bash
cd ~/ros2-smart-car
bash scripts/build_jetson.sh
bash scripts/run_jetson.sh
```

启动后，手机或电脑浏览器访问：

```text
http://192.168.1.104:8080
```

Web 控制台支持：

- 急停和解除急停
- `stop/manual/auto/mapping/navigation/color_track/object_follow` 模式切换
- 方向遥控
- 摄像头 MJPEG 视频流
- 雷达距离、YOLO 结果、偏移量、状态 JSON 查看
- 手机浏览器添加到主屏幕作为 PWA 使用

## 厂家底层功能启动参考

本仓库记录了 Yahboom 参考启动命令：

```text
ros2_ws/src/smart_car_decision/config/vendor_launch_profiles.yaml
```

常用示例：

```bash
ros2 run yahboomcar_bringup Mcnamu_driver_X3
ros2 launch yahboomcar_laser laser_Avoidance_a1_X3.launch.py
ros2 launch yahboomcar_astra colorTracker_X3.launch.py
ros2 launch yahboomcar_nav localization_imu_odom.launch.py
```

实际比赛/展示时建议先启动底盘驱动和必要传感器，再启动本仓库的 `bringup_all.launch.py`。

## Docker 运行

用于展示 ROS2 环境容器化：

```bash
cd ~/ros2-smart-car
bash scripts/run_docker.sh
```

容器使用 host 网络和 `/dev` 设备映射，适合 Jetson 上访问摄像头、雷达串口等设备。实车调试仍建议优先使用 Jetson 原生运行，等功能稳定后再迁移进容器。

## PC 遥控工具

旧版 PyQt6 遥控界面仍保留：

```bash
python ros2_command/pc.py --host 192.168.1.104 --port 9999
```

它通过 TCP 发送 `forward/backward/left/right/turn_l/turn_r/stop`，由 `tcp_command_bridge` 转成 ROS2 `/manual_cmd`。

## 最小验证流程

1. 小车架空，避免误动作。
2. 启动 Yahboom 底盘驱动。
3. 启动本仓库：

```bash
cd ~/ros2-smart-car
bash scripts/run_jetson.sh
```

4. 查看 ROS2 话题：

```bash
ros2 topic list
ros2 topic echo /robot/status
ros2 topic echo /cmd_vel
```

5. 打开 Web 控制台，先解除急停并切到 `manual`，测试方向键和停止。
6. 切到 `auto/color_track/object_follow` 前确认场地安全、雷达和摄像头数据正常。
