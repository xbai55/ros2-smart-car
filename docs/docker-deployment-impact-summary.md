# Docker 一键部署改造影响说明

## 1. 总体结论

这次修改不是单纯“把程序放进 Docker”，而是把 **Jetson 实车启动流程** 做成了相对完整的 **Docker 一键部署闭环**。

- **环境一致性**：ROS2、Python 依赖、Web 后端依赖、YOLO 依赖进入镜像。
- **启动自动化**：一条命令完成硬件恢复、旧进程清理、容器启动、健康检查。
- **硬件可诊断**：雷达、摄像头、底盘缺失时不再假成功。
- **后续开发可延续**：大部分功能仍按原 ROS2 包结构开发，不需要每次重做 Docker 部署方案。

## 2. 相比未 Docker 部署做了哪些工作

### 2.1 增加 Docker 运行环境

| 文件 | 作用 |
|---|---|
| **`Dockerfile`** | 构建 ROS2 Humble、项目依赖和 Python 依赖镜像 |
| **`docker-compose.jetson.yml`** | Jetson 实车运行容器配置 |
| **`docker-compose.pc.yml`** | PC 开发容器配置 |
| **`docker/entrypoint.sh`** | 进入容器时自动 source ROS2 和 Yahboom workspace |
| **`docker/launch_runtime.sh`** | 容器内启动前做设备检查和诊断 |

实现效果：

```bash
bash scripts/deploy_docker_jetson.sh
```

即可启动完整 runtime。

### 2.2 增强 Jetson 一键部署脚本

`scripts/deploy_docker_jetson.sh` 现在会自动做：

1. 停止旧 Docker 容器。
2. 停止旧 ROS2、Yahboom、摄像头占用进程。
3. 加载 `cp210x`、`uvcvideo`。
4. reload 和 trigger **udev rules**。
5. 检查底盘、雷达、摄像头。
6. 构建并启动容器。
7. 执行健康检查。

实现效果：

- `/dev/rplidar` 缺失会明确报错。
- `/dev/video0` 缺失会明确报错。
- `/dev/myserial` 或 `/dev/ttyUSB0` 缺失会明确报错。
- 不再出现“容器启动了但功能半死不活还以为成功”的情况。

### 2.3 改造 ROS2 launch

`bringup_all.launch.py` 做了参数化：

| 参数 | 用途 |
|---|---|
| **`lidar_serial_port`** | 不再硬编码 `/dev/rplidar` |
| **`camera_source`** | 摄像头来源可由环境变量传入 |
| **`start_yolo_camera`** | 可控制是否启动 YOLO 节点 |
| **`start_color_tracker`** | 可控制是否启动颜色追踪节点 |
| **`start_web_camera`** | 可控制 Web 是否直接占用摄像头 |

实现效果：

- 雷达端口可以换。
- 摄像头缺失时可以禁用摄像头节点。
- Web、YOLO、颜色追踪不会在不合适时乱抢摄像头。

### 2.4 增强节点容错

修改了：

- **`web_app_node.py`**
- **`yolo11_camera_node.py`**
- **`decision.yaml`**

实现效果：

- `web_app_node` 支持禁用 Web 视频流，但 Web 控制台仍能启动。
- `yolo11_camera_node` 保持 idle，不会在 `stop` 模式提前占用摄像头。
- 摄像头打开失败时会输出清晰日志并重试。
- 修复了 `camera_source=0` 被 ROS2 当成 integer 导致 Web 节点崩溃的问题。

## 3. 实现效果

### 3.1 当前实车效果

Jetson 上已经验证通过：

```text
STRICT_DEPLOY_RC=0
Docker smart-car runtime healthcheck passed.
```

关键能力恢复：

| 功能 | 当前效果 |
|---|---|
| **底盘** | `/odom` 正常 |
| **雷达** | `/scan` 正常 |
| **摄像头设备** | `/dev/video0`、`/dev/video1` 可见 |
| **Web 控制台** | `8080` 正常 |
| **TCP command bridge** | `9999` 正常 |
| **状态节点** | `/robot/status` 正常 |
| **YOLO 节点** | 正常启动，未进入模式前 idle |
| **健康检查** | 可自动判断启动是否成功 |

## 4. 对后续开发的影响

### 4.1 正面影响

| 方面 | 影响 |
|---|---|
| **环境一致性** | PC、Jetson 更接近，不容易出现“我这能跑你那不能跑” |
| **部署效率** | 改完代码后可以一键重建启动 |
| **问题定位** | 硬件缺失、端口未监听、ROS topic 无数据会直接报错 |
| **团队协作** | 新成员按文档和脚本部署，不需要手动记一堆命令 |
| **功能测试** | 健康检查能快速确认底盘、雷达、Web、TCP 是否在线 |

### 4.2 需要注意的影响

以后新增功能时，需要考虑 Docker 镜像是否包含依赖：

| 新增内容 | 是否需要改 Docker |
|---|---|
| 只改 ROS2 Python 逻辑 | 通常只需要重建镜像 |
| 新增 Python pip 包 | 需要改 `requirements-*.txt` 或 `Dockerfile` |
| 新增 apt/ROS 系统包 | 需要改 `Dockerfile` |
| 新增硬件设备 | 需要改 compose 的设备检查、udev 说明或环境变量 |
| 新增 Web 前端页面 | 需要重新 `npm run build` 并同步 `web-console/dist` |
| 新增 ROS2 launch 参数 | 需要同步改 launch、compose/env、文档 |

## 5. 修改代码是否方便

### 5.1 推荐开发流程

以前可能是：

```bash
直接在 Jetson 上改代码
source install/setup.bash
ros2 launch ...
```

现在推荐流程是：

```bash
本地改代码
git push
Jetson 同步或拉取
bash scripts/deploy_docker_jetson.sh
```

对于 ROS2 代码，Docker 镜像会重新 build，但现在构建上下文已经优化过，常规 Python 代码改动不会重新下载大依赖。

### 5.2 常用修改路径

| 修改类型 | 推荐操作 |
|---|---|
| 改 ROS2 节点逻辑 | 改 `ros2_ws/src/...`，重新跑部署脚本 |
| 改 Web 前端 | `cd web-console && npm run build`，再部署 |
| 改 Docker 启动流程 | 改 `scripts/`、`docker/`、`docker-compose.jetson.yml` |
| 改硬件参数 | 优先用环境变量，不要硬编码 |
| 现场临时验证 | 可用容错变量，例如 `SMART_CAR_REQUIRE_CAMERA=0` |

## 6. 后续是否需要重新做这次工作

### 6.1 不需要重新做一遍

这次主要是一次性补齐 **Docker 化基础设施**。后续不需要再从零做：

- 不需要重新设计 Dockerfile。
- 不需要重新写 compose。
- 不需要重新写硬件恢复流程。
- 不需要重新写健康检查。
- 不需要重新解决 `camera_source` 类型问题。
- 不需要重新梳理雷达、摄像头、底盘的启动关系。

### 6.2 什么时候需要扩展

| 场景 | 需要做什么 |
|---|---|
| 换雷达型号 | 增加新的 udev 识别规则和端口检测逻辑 |
| 换摄像头型号 | 检查 `/dev/video*`、OpenCV source 和驱动 |
| 新增传感器 | 在 compose、deploy script、healthcheck 中加入检查 |
| 新增 ROS2 依赖 | 更新 Dockerfile |
| 新增运行模式 | 更新 launch 参数和健康检查 |
| 上云或多机部署 | 扩展 compose 或拆分服务 |

## 7. 一句话总结

这次修改把原来依赖手工经验的 **Jetson 原生启动流程**，升级成了可重复、可检查、可失败、可诊断的 **Docker 一键部署流程**。后续开发仍然按原 ROS2 架构写功能，只是在部署时走统一 Docker 脚本；一般不需要重做这次工作，只需要随着新硬件、新依赖、新节点做小幅增量维护。
