# ros2-smart-car

本仓库用于保存 Yahboom ROSMASTER X3 智能小车综合设计相关代码和文档。

当前仓库包含三类内容：

- `src/`：STM32CubeIDE 工程，主要是 LED、蜂鸣器、基础外设实验。
- `ros2_command/`：PC 端远程控制界面，例如 PyQt6 TCP 控制程序。
- `ros2_ws/src/smart_car_decision/`：ROS2 决策控制包，用于雷达避障、视觉识别结果融合、巡线控制和 TCP 遥控桥接。

## 总体架构

推荐在小车的 Orin Nano 上运行 ROS2、雷达、摄像头、YOLO 和控制节点；Windows 本机主要用于查看代码、SSH/VNC 远程连接和运行 PC 遥控界面。

```text
摄像头/YOLO/路径识别
        |
        v
/vision/detection, /lane/offset
        |
        v
smart_car_decision
        ^
        |
雷达 /scan ----> 前方障碍检测
        |
        v
/cmd_vel ----> Yahboom 底盘驱动 ----> STM32 ----> 电机
```

## 新增 ROS2 包说明

包路径：

```text
ros2_ws/src/smart_car_decision
```

包含 3 个节点：

### 1. `decision_controller`

核心决策控制节点。

订阅：

- `/scan`：雷达数据，类型 `sensor_msgs/LaserScan`
- `/vision/detection`：视觉识别结果，类型 `std_msgs/String`
- `/lane/offset`：路径偏移，类型 `std_msgs/Float32`
- `/manual_cmd`：手动控制命令，类型 `std_msgs/String`

发布：

- `/cmd_vel`：小车速度控制，类型 `geometry_msgs/Twist`

默认规则：

```text
前方 0.45m 内有障碍 -> 停车
识别到 red_light / shutdown / stop -> 停车
识别到 turn_right -> 右转
识别到 turn_left -> 左转
识别到 go_straight / green_light / no_light -> 前进
识别到 limiting_velocity / school_decelerate / slow -> 慢速前进
没有特殊视觉指令时 -> 根据 /lane/offset 做巡线修正
```

### 2. `laser_obstacle_monitor`

雷达前方障碍检测节点。

订阅：

- `/scan`

发布：

- `/obstacle/front`，类型 `std_msgs/Bool`

作用是把雷达一圈距离数据简化成“前方是否有障碍”。

### 3. `tcp_command_bridge`

TCP 遥控桥接节点。

默认监听：

```text
0.0.0.0:9999
```

收到 PC 端发来的字符串后发布到 `/manual_cmd`。

支持命令：

```text
forward
backward
left
right
turn_l
turn_r
stop
```

这和 `ros2_command/pc.py` 里的按钮命令对应。

## 在小车 Orin Nano 上使用

以下命令建议在小车终端执行，而不是 Windows 本机。

### 1. 进入工作空间

如果你已经把本仓库放到小车上：

```bash
cd ~/ros2-smart-car/ros2_ws
```

如果你只想把 ROS2 包复制到厂家工作空间，也可以复制：

```bash
cp -r ~/ros2-smart-car/ros2_ws/src/smart_car_decision ~/yahboomcar_ws/src/
cd ~/yahboomcar_ws
```

### 2. 编译

```bash
source /opt/ros/humble/setup.bash
colcon build --packages-select smart_car_decision
source install/setup.bash
```

### 3. 先启动厂家底盘驱动

你们之前记录过 X3 底盘驱动命令：

```bash
ros2 run yahboomcar_bringup Mcnamu_driver_X3
```

再开一个终端，确认 `/cmd_vel` 存在：

```bash
ros2 topic list
```

### 4. 启动雷达

先确认雷达设备：

```bash
ls /dev/ttyUSB*
lsusb
```

然后用厂家雷达 launch 启动。具体 launch 名需要在小车的厂家工作空间里查：

```bash
find ~/yahboomcar_ws -iname "*lidar*"
find ~/yahboomcar_ws -iname "*laser*"
find ~/yahboomcar_ws -iname "*rplidar*"
find ~/yahboomcar_ws -iname "*.launch.py"
```

启动雷达后验证：

```bash
ros2 topic list
ros2 topic echo /scan
```

看到 `/scan` 并且 `ranges: [...]` 持续刷新，说明雷达已经接入。

### 5. 启动决策控制

```bash
source /opt/ros/humble/setup.bash
source install/setup.bash
ros2 launch smart_car_decision decision_bringup.launch.py
```

启动后会同时运行：

- `laser_obstacle_monitor`
- `decision_controller`
- `tcp_command_bridge`

## 和厂家 YOLO/路径识别代码对接

厂家已有视觉代码主要在：

```text
C:\Users\xbai55\Desktop\综设\Rosmaster\Rosmaster\auto_drive
```

小车上通常对应：

```bash
~/Rosmaster/auto_drive
```

其中：

- `road_following.py`：路径跟随
- `yolov5_auto.py`：YOLOv5 + TensorRT + 自动驾驶动作
- `yolov5/traffic.yaml`：识别类别

为了和本包对接，视觉程序需要把识别结果发布成 ROS2 话题：

```text
/vision/detection  std_msgs/String
```

例如发布：

```text
red_light
turn_right
go_straight
slow
stop
```

路径识别程序可以发布：

```text
/lane/offset  std_msgs/Float32
```

约定：

```text
0.0  表示路径在画面中间
正数 表示路径偏右
负数 表示路径偏左
```

`decision_controller` 会根据偏移量自动修正角速度。

## 参数配置

配置文件：

```text
ros2_ws/src/smart_car_decision/config/decision.yaml
```

常用参数：

- `obstacle_stop_distance`：前方小于该距离强制停车，默认 `0.45`
- `obstacle_slow_distance`：前方较近时降速，默认 `0.75`
- `cruise_speed`：默认前进速度，默认 `0.18`
- `slow_speed`：慢速前进速度，默认 `0.08`
- `front_angle_deg`：雷达前方检测角度，默认左右各 `35` 度
- `lane_kp`：巡线偏移转向比例

## 最小测试流程

1. 小车架空，防止误动作。
2. 启动底盘驱动。
3. 启动雷达，确认 `/scan` 有数据。
4. 启动本包：

```bash
ros2 launch smart_car_decision decision_bringup.launch.py
```

5. 手动发布测试命令：

```bash
ros2 topic pub --once /manual_cmd std_msgs/String "{data: 'forward'}"
ros2 topic pub --once /manual_cmd std_msgs/String "{data: 'stop'}"
```

6. 测试视觉规则：

```bash
ros2 topic pub --once /vision/detection std_msgs/String "{data: 'red_light'}"
ros2 topic pub --once /vision/detection std_msgs/String "{data: 'turn_right'}"
```

7. 测试巡线偏移：

```bash
ros2 topic pub --once /lane/offset std_msgs/Float32 "{data: 0.3}"
```

## 注意

SLAM 和 Nav2 不需要自己从零写。建议优先使用 Yahboom 厂家 ROS2 镜像和 `yahboomcar_ws` 里的雷达、建图、导航 launch。本仓库新增的 `smart_car_decision` 主要解决“视觉结果 + 雷达安全 + 手动遥控 + /cmd_vel 控制”的融合问题。
