# Docker 容器化与分布式部署

## 1. 目标

本方案用于满足任务书中的 **Docker 容器化 ROS2 环境** 和 **分布式部署** 要求。

- **Jetson 端**：运行 `smart-car-runtime` 容器，负责底盘、雷达、摄像头、YOLO、颜色追踪、决策控制、SLAM 依赖、Web 控制台和 TCP command bridge。
- **PC 端**：运行 `smart-car-dev` 容器，用于一致化开发、编译、测试和远程 ROS2 调试。
- **ROS2 版本**：默认使用 `ROS2 Humble`，默认 `ROS_DOMAIN_ID=77`。

## 2. Jetson 一键启动

在 Jetson 项目目录执行：

```bash
cd /home/jetson/ros2-smart-car
bash scripts/deploy_docker_jetson.sh
```

脚本会按顺序执行：

1. 检查 **Docker** 和 **Docker Compose**。
2. 停止旧的 Docker runtime。
3. 停止可能占用 `/dev/video0`、`/dev/ttyUSB0`、`/dev/ttyUSB1`、`/dev/rplidar`、`/dev/myserial` 的旧 ROS2、Yahboom 和摄像头进程。
4. 加载 `cp210x` 和 `uvcvideo` 内核模块。
5. 重新加载并触发 **udev rules**。
6. 检查底盘、雷达和摄像头设备。
7. 构建并启动 `smart-car-runtime` 容器。
8. 检查 `8080`、`9999`、`/api/status`、ROS2 nodes、`/odom`、`/robot/status`、`/scan` 和摄像头能力。

## 3. 直接 Compose 启动

也可以直接启动容器：

```bash
docker compose -f docker-compose.jetson.yml up -d smart-car-runtime
docker compose -f docker-compose.jetson.yml logs -f smart-car-runtime
```

直接 Compose 启动时，容器入口 `docker/launch_runtime.sh` 仍会进行二次设备检查。默认严格模式下，缺少底盘、雷达或摄像头会导致容器退出并输出诊断信息。

## 4. 必需硬件设备

| 设备 | 默认路径 | 生成方式 | 用途 |
|---|---|---|---|
| **底盘串口** | `/dev/myserial` 或 `/dev/ttyUSB0` | `serial.rules` 或 USB serial 自动枚举 | Yahboom chassis driver 和 `/odom` |
| **雷达串口** | `/dev/rplidar` | `rplidar.rules` 将 CP210x 设备映射为 symlink | `sllidar_ros2` 和 `/scan` |
| **摄像头** | `/dev/video0` | `uvcvideo` 或相机厂商驱动枚举 | YOLO、颜色追踪和 Web 视频 |

## 5. 严格模式与容错模式

默认实车部署使用严格模式，避免硬件缺失时仍宣称部署成功。

| 环境变量 | 默认值 | 含义 |
|---|---:|---|
| `SMART_CAR_REQUIRE_LIDAR` | `1` | `1` 表示缺少雷达时部署失败 |
| `SMART_CAR_REQUIRE_CAMERA` | `1` | `1` 表示缺少摄像头时部署失败 |
| `SMART_CAR_LIDAR_PORT` | `/dev/rplidar` | 手动指定雷达串口 |
| `SMART_CAR_CAMERA_SOURCE` | `0` | 手动指定 OpenCV camera source |
| `SMART_CAR_START_YOLO_CAMERA` | `1` | 是否启动 YOLO 摄像头节点 |
| `SMART_CAR_START_COLOR_TRACKER` | `1` | 是否启动颜色追踪节点 |
| `SMART_CAR_START_WEB_CAMERA` | `1` | 是否启用 Web 直连摄像头流 |

容错模式示例：

```bash
SMART_CAR_REQUIRE_LIDAR=0 SMART_CAR_REQUIRE_CAMERA=0 bash scripts/deploy_docker_jetson.sh
```

容错模式只适合调试 Web、TCP bridge、底盘或纯 ROS2 控制链路，不适合宣称完整实车部署成功。

## 6. 雷达设备诊断

`/dev/rplidar` 通常由 udev 规则生成。典型规则如下：

```text
KERNEL=="ttyUSB*", ATTRS{idVendor}=="10c4", ATTRS{idProduct}=="ea60", MODE:="0777", SYMLINK+="rplidar"
```

诊断命令：

```bash
lsusb
ls -l /dev/rplidar /dev/ttyUSB* 2>/dev/null || true
udevadm info -q property -n /dev/ttyUSB0 2>/dev/null || true
dmesg | tail -n 160 | egrep -i 'usb|ttyUSB|cp210|serial|lidar|disconnect|reset|error'
```

如果 `lsusb` 中没有 `10c4:ea60` 或 `cp210x` 相关设备，通常是雷达 USB 线、供电、Hub 或设备枚举问题，不是 Docker 挂载问题。

## 7. 摄像头设备诊断

摄像头依赖 `/dev/video*` 设备节点。诊断命令：

```bash
sudo modprobe uvcvideo || true
sudo udevadm control --reload-rules || true
sudo udevadm trigger || true
lsusb
ls -l /dev/video* 2>/dev/null || true
dmesg | tail -n 160 | egrep -i 'usb|uvc|video|camera|disconnect|reset|error'
```

如果 `uvcvideo` 已加载但没有 `/dev/video*`，说明摄像头没有被宿主机 USB 总线识别。此时容器内也无法通过 `/dev:/dev` 获得摄像头。

## 8. 健康检查

启动后执行：

```bash
bash scripts/healthcheck_docker.sh
```

健康检查覆盖：

| 检查项 | 通过标准 |
|---|---|
| **容器** | `smart-car-runtime` 处于 running |
| **Web 控制台** | `8080` 监听，`/api/status` 返回 JSON |
| **TCP command bridge** | `9999` 监听 |
| **ROS2 nodes** | `/base_node`、`/system_status_node`、`/tcp_command_bridge`、`/web_app_node` 在线 |
| **底盘状态** | `/odom` 和 `/robot/status` 可采样 |
| **雷达状态** | 严格模式下 `/scan` 存在且可采样 |
| **摄像头能力** | 严格模式下 `/dev/video*` 存在，且 `/vision/annotated_frame` 话题存在 |

## 9. PC 开发容器

在开发机仓库根目录执行：

```bash
docker compose -f docker-compose.pc.yml run --rm smart-car-dev
```

进入容器后可执行：

```bash
source /opt/ros/humble/setup.bash
colcon build --base-paths ros2_ws/src --packages-select smart_car_decision
python3 -m pytest -q tests
```

## 10. 关键注意事项

- `9999` 是 **TCP command bridge**，不是 HTTP API。
- `smart-car-runtime` 使用 `network_mode: host`，避免 ROS2 DDS 和 Web 端口映射问题。
- Jetson 默认基础镜像为 `docker.m.daocloud.io/library/ros:humble-ros-base`，可通过 `SMART_CAR_BASE_IMAGE` 覆盖。
- 容器会 source Yahboom workspace，并通过 `PYTHONPATH` 暴露 `Rosmaster_Lib`。
- 不要在硬件缺失时把容错模式结果写成完整部署成功。
