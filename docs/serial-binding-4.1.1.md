# 4.1.1 串口冲突排查、修复准备与现场验收

## 当前结论与边界

2026-11-17，先完成只读排查，再按用户逐阶段明确授权完成真实协议仅接收采样、唯一底盘绑定安装、独立驱动构建和隔离静态验证，随后获准切换并启动整车服务。故障驱动打开物理2.3，真实底盘协议却来自2.2.3，错误绑定证据已经闭合。**整车现已在新目录运行并保持stop，网页、雷达、原始IMU、Madgwick、原始里程计和EKF静态检查通过**。正常控制器持续发送零速停车报文，非零运动报文计数为0；未执行驾驶/导航请求，未改EKF/Nav2/Madgwick/底盘参数或交接阈值。

最新运行验收：`output/serial-binding-20261117/deployment-20261117-220657/RUNNING_REPORT.md`。后续章节中的“保持停止/等待入口切换”描述的是前一隔离部署阶段，不是当前主服务状态。

最新部署和静态验收报告：`output/serial-binding-20261117/deployment-20261117-220657/DEPLOYMENT_REPORT.md`。原始仅接收采样16384字节、速度245帧/IMU244帧、零checksum错误，静止加速度均值9.916 m/s²；后续静态ROS验证原始加速度均值9.909 m/s²、运动报文发送计数0。

现场报告：`output/serial-binding-20261117/passive-20261117-215447/FIELD_REPORT.md`。下文的假设排序保留了初稿证据边界；当前可将“底盘驱动未连接已确认的底盘协议口”升级为已证实，不能将另一个口直接命名为 MQ-2。新的本地 confirmed 配置仅包含 base，不包含 smoke。

用户补充：**没有语音模块**；烟雾传感器是 MQ-2，可能经 STM32 接入 USB。`myspeech.rules` 是历史注释，不能用来证明目前存在语音设备。早先 `output/cannot-drive-20261117/FINDINGS.md` 中“很可能打开语音接口”的描述由本报告纠正。

### 已确认

- 两个 CH340 均为 `1a86:7523`，没有可用的唯一 USB 序列号。两者都声明 `/dev/myserial`，也争用了同名 by-id 链接；当前链接指向 ttyUSB2。这个配置冲突本身已经成立。
- 当前运行 `/home/jetson/insightrover-v411-task-consistency-37926128f27a/start_v4.sh`，服务主进程 487498；驱动 487912 的 fd19 打开 ttyUSB2，雷达 488011 打开 ttyUSB1（PID 只是采集时快照）。驱动不是本地最新修改的证明。
- 前轮日志有 110 条非零最终速度输出，示例为前进 0.14 m/s，控制权有效，而里程计反馈没有相应变化。当前停车提示不能解释此前这些已放行输出。
- 实际 SDK 3.3.1 默认打开 `/dev/myserial`，115200、pyserial 默认 8N1；驱动没有配置显式端口。源码能证明意图参数，不能替代对运行串口设置的独立观测。本轮没有为了读取设置而打开设备。
- SDK 缓存初值为零；驱动定时器每 0.1 秒读缓存并重新打 ROS 时间戳。没有反馈时也能产生表面新鲜的 `/vel_raw`、`/imu/data_raw`；原始 IMU 加速度和角速度全零，滤波 IMU 无有效输出，符合这一失败机制。
- SDK 在构造函数中自动发送舵机力矩指令。**实例化 SDK 不是只读诊断**，本轮只读源代码，没有实例化它。
- 底盘回包由 `FF FB` 帧头、长度、功能字、数据和校验和组成。速度 `0x0A` 有 7 字节数据；MPU `0x0B`、ICM `0x0E` 各有 18 字节数据。旧接收线程未向 ROS 发布有效帧时间与故障状态，校验错误仅在 debug 时打印，发送函数还会吞掉异常。

### 根因排序

1. **串口通用别名冲突和错误选择底盘通信口：已确认。** 原驱动打开2.3，而2.2.3经真实协议采样确认持续输出底盘速度、IMU、编码器和姿态；修正绑定后原始及融合链路恢复。ttyUSB2是否就是STM32/MQ-2仍待确认，不能据此给它分配烟雾业务别名。
2. **SDK 缺少反馈有效性与时效性：已确认的软件缺陷。** 它掩盖收包失败，并可让原始轮速与 IMU 出现相同的数据源异常。不能仅凭 `/odom_raw` 为零就区分“真实静止”和“没有收到速度回包”。
3. **USB 链路、供电、接触或底盘协议配置异常：待验证。** 内核有另一端口 2.4 的 `-71` 枚举错误，不能直接归因给底盘当前端口。若候选底盘口无有效回包，下一步应核对接线、供电与固件，而非放宽控制或定位阈值。

设备 2.3 在 17:01:30 起多次接入、断开，最后在 17:57:42 接入；当前 devnum29，2.2.3 为 devnum9。这支持新增设备改变链接归属的解释，但当前可用内核日志没有完整保留更早的底盘枚举，旧进程原句柄也未保存，因此“旧进程一直持有正确设备，重启才暴露冲突”仍是机制上成立的假设。固定 VID/PID、bcdDevice 差异及枚举先后都不足以单独证明业务角色。

## 设备映射表

| 采集时节点 | 身份属性 | 稳定物理路径 ID_PATH | 当前使用 | 建议业务角色 |
|---|---|---|---|---|
| ttyUSB0 | CH340 `1a86:7523`，无唯一序列号，bcdDevice8134，interface00 | `platform-3610000.usb-usb-0:2.2.3:1.0` | robot_base，已确认；当前由新驱动唯一占用 | 底盘，OWNER=jetson、0600 |
| ttyUSB2 | CH340 `1a86:7523`，无唯一序列号，bcdDevice0264，interface00 | `platform-3610000.usb-usb-0:2.3:1.0` | 故障时被底盘驱动错误打开；现已释放且移除myserial | STM32/MQ-2候选，未命名；原访问权限保留 |
| ttyUSB1 | CP2102 `10c4:ea60`，序列0001，interface00 | `platform-3610000.usb-usb-0:2.2.2:1.0` | 雷达；rplidar/ydlidar原样保留，整车雷达输出已恢复 | 原样保留 |

CH340 的通用 by-id 名称 `usb-1a86_USB_Serial-if00-port0` 也不唯一，不能拿它替换 myserial。对应的 by-path 名称是在上述 ID_PATH 后追加 `-port0`；已保存原始映射，不依赖 ttyUSB 编号。

当前没有证据表明 MQ-2 接口已被独立采集服务读取。项目内烟雾/火焰视觉识别代码不能证明 MQ-2 已接入业务系统；未找到与当前 STM32 固件相对应的硬件烟雾协议实现。工作区 `src/hello`、`src/LED`、`src/Beep` 不是设备角色或 MQ-2 协议的可靠证明。需要接线记录/固件或被动接收证据，不能凭名称假定 Modbus、文本格式或波特率。

## 数据链路与判断位置

```mermaid
flowchart LR
  UI[Web/客户端] --> Lease[控制权与运动仲裁]
  Lease --> Cmd[最终 /cmd_vel]
  Cmd --> Driver[底盘 ROS 驱动]
  Driver --> SDK[串口 SDK / 115200 8N1]
  SDK --> Alias[myserial 当前指向 USB 2.3]
  Alias --> Unknown[物理设备角色待确认]
  Board[真实底盘控制板] --> Frames[速度与 IMU 有效回包]
  Frames --> Driver
  Driver --> Vel[/vel_raw]
  Driver --> Imu[/imu/data_raw]
  Vel --> Base[base_node / odom_raw]
  Imu --> Madgwick[/imu/data]
  Base --> EKF[EKF / odom]
  Madgwick --> EKF
```

最终速度输出日志已存在，控制权并非本轮首要修改点。驱动持有哪个 fd 已确认；源码证明发送到这个 fd，但旧发送函数吞掉异常，**缺少逐次 write 返回长度和硬件 ACK，不能把日志中的非零速度当作底盘实际收到或执行**。

## 本地修复内容

- `smart_car_decision/serial_binding.py`：只读匹配 VID/PID、接口和唯一序列号或物理路径；拒绝多匹配、跨角色重叠、缺失设备、错误别名和端口占用。设备没有唯一序列号时绑定 ID_PATH，换 USB 接口必须重新核对。普通用户无法看完整 `/proc` 时，使用已有权限执行只读 `sudo -n /usr/bin/fuser <device>`；无权限或审计失败就拒绝启动，不把“看不到”当作“空闲”。不使用 `fuser -k`。
- `base_serial_feedback.py`：校验长度与 checksum，恢复帧同步；按当前实际 SDK 的符号和比例解码两类 IMU。只有真实有效速度和非零加速度 IMU 回包才建立健康状态，分别记录接收时间。零轮速是合法静止反馈，未收包的缓存零不是。0.5 秒是本地保守的通信失效检测上限，尚待实测频率验收；不改变原有控制器、雷达或 EKF 超时，也没有放宽它们。
- `base_serial_transport.py`：端口只能是 robot_base，禁止 myserial/ttyUSB 覆盖；profile 未确认时不会调用串口工厂。打开前检查身份、别名和占用；打开时请求 exclusive/TIOCEXCL，打开后再核对字符设备号、USB 身份与既有占用，发现竞争就关闭。检查短写/读错误，形成明确故障。反馈无效拒绝新非零输出；已确认链路在运动中失效时向同一已确认设备尝试一次零速，失败明确报告。此措施不能代替底盘固件失联停车，后者仍须现场验收。
- `scripts/prepare_base_serial_overlay.py`：只在本地从**车端原始字节且指纹匹配**的 SDK/驱动生成独立覆盖层。不覆盖系统安装。保留厂商原有 ROS 话题、单位、车体类型、灯光和蜂鸣器接口；去掉与本车无关的构造时机械臂舵机指令。保留原协议解码以服务辅助报文，但传感器发布改读有效接收快照；无效或过期就停止发布原始轮速/IMU，输出 `/diagnostics` 错误，每个真实样本最多发布一次。原始 IMU 不提供姿态，将 `orientation_covariance[0]` 标为 -1，不能把默认四元数当实测姿态；没有给 gyro/accel 编造噪声协方差或改融合参数。
- `verified_base_driver.py`、`setup.py`、`bringup_all.launch.py`：新增受保护入口，独立驱动已部署并通过静态验收。缺 profile 或缺生成的覆盖层会明确失败，不回落旧 SDK。主服务仍停止且尚未切换到新目录。
- `package.xml`：声明实际需要的 `python3-serial` 和 `diagnostic_msgs`，不新增其他运行框架。
- `config/serial-binding.candidate.json`：底盘与烟雾口均明确 `confirmed:false`，不能直接安装或生成生效规则。没有新增 voice_device。
- `scripts/inspect_base_serial.py`：库存、自检、规则生成、离线解码与有单独授权才可运行的限时仅接收采样。采样最多 30 秒/1 MiB，保存原始 bytes、每块接收单调时间和故障，绝不调用 SDK 构造或 serial.write。打开设备仍可能改变 DTR/RTS，不能把它算作只读现场检查。
- `scripts/prepare_serial_binding_deployment.py`：本地生成规则/身份配置的 before、after 与指纹清单，只删除已核对的 active myserial 单用途规则行；保留其他规则和历史注释。未知混合用途规则、指纹变化、未确认设备角色会阻止生成。此脚本不连接车端、不安装、不 reload udev。

新代码已部署到独立目录，不覆盖旧目录；EKF、Madgwick、Nav2、map_handoff.py 及运动仲裁安全约束均未修改。原有工作区改动保留。当前服务账户不在dialout组，因此新底盘口采用仅OWNER=jetson、0600权限。旧规则中附带的其他CH340权限按已采集物理路径定向保留，不增加烟雾别名，不把账户加入可访问其他串口的组。

## 固定源版本及备份

车端重新按原始 bytes 获取源码，避免 Windows 换行转换造成伪指纹不一致：

- SDK：`bc0f1313f4f2527cca5f631373ab66cf03c66035d1732a3f2fd665f32a27c139`
- 驱动：`2be9784289154b3d2ec972266ccdba5056ffe317b06a4d17c2a9a48e42a8d39a`

生成的覆盖层及文件指纹在 `output/serial-binding-20261117/staged-vendor/manifest.json`，标记 `installed:false`。上游 SDK/驱动继续保留原位，只把生成文件放进新的独立 release 的 `smart_car_decision` 包，构建并切换服务时需要新的现场授权。生成工具不接受未知版本的自动替换。

本地生成命令（输入是本轮无损提取的实际源码，不打开硬件）：

```bash
python3 scripts/prepare_base_serial_overlay.py \
  --sdk output/serial-binding-20261117/vehicle-sdk.py \
  --driver output/serial-binding-20261117/vehicle-driver.py \
  --sdk-sha256 bc0f1313f4f2527cca5f631373ab66cf03c66035d1732a3f2fd665f32a27c139 \
  --output output/serial-binding-20261117/staged-vendor-new
```

生成目录必须不存在。获准部署后，先核对生成 manifest，再把两个 py 文件放入**新 release** 的 `ros2_ws/src/smart_car_decision/smart_car_decision/`，确认该处无其他同名修改再安装；随后在新 release 的 ros2_ws 中按原工程环境构建 `smart_car_decision`。缺少这一步时入口会明确拒绝启动，不会偷用系统旧 SDK。

## 现场阶段 A：确认身份与静态通信（首轮仅接收已完成）

目标：先证明候选口是否有底盘协议，不先改 alias，不试发任何指令。前提是有人确认车辆静止、没有任务运行，不按驾驶按钮。停止现有整车服务将一起中断底盘、雷达、IMU/EKF、Web；下一次启动要重建定位基准。本阶段不自动重启旧的冲突配置。

以下是现场步骤模板。首轮已按用户明确授权执行停止服务及10秒仅接收采样，原始证据见上述现场报告；**不要据此重复打开串口或重启服务**。`$ROOT` 指已审核的新独立目录；仅上传工具及源码，不覆盖当前部署、vendor 安装或任何参数。

```bash
# jetson 用户：只有获得停止服务授权后执行
systemctl --user stop smart-car-v4.service
systemctl --user is-active smart-car-v4.service   # 应为 inactive
sudo -n /usr/bin/fuser /dev/serial/by-path/platform-3610000.usb-usb-0:2.2.3:1.0-port0
# 应无 PID；有任何占用则停止，不抢占、不 kill

# 只针对物理路径候选，默认 115200 8N1；不发送任何数据
cd "$ROOT"
sudo -n python3 scripts/inspect_base_serial.py passive \
  --profile ros2_ws/src/smart_car_decision/config/serial-binding.candidate.json \
  --authorized-passive-candidate --seconds 10 \
  --output /home/jetson/serial-audit-base-20261117
```

此打开可能改变 DTR/RTS，脚本尽量提前置低但不能保证 USB 芯片/STM32 不复位，因此不暗中执行。只对已确认空闲的 2.2.3 候选接收一次。若无字节，不推断设备错误或强行开启自动上报；若有但不是底盘协议，保留原始文件，停止，不扫描波特率、不发握手。必须另行取得明确的固件/设备说明。

验收需重复有效的速度与 IMU 帧（10 秒采样至少 20 组，具体速率原样报告），校验错误率可解释；静止速度接近零、加速度模长合理接近重力、gyro 合理接近零。只有数据和接线能对应设备身份时才把 base 标为 confirmed 并记录原始数据 SHA/接线证据。烟雾口的身份独立核实；不能拿它没有底盘帧当作它就是 MQ-2 的证明。烟雾驱动未知时先不部署烟雾 reader，保留原设备。

## 确认后的规则部署与回退（已按授权完成）

如只确认底盘，确认配置可暂时仅包含 base；烟雾设备的原节点与配置保持不动。只有确认烟雾口后才加入 smoke 别名。不要把候选配置中的 false 一次性全改 true。

```bash
# 本地/准备目录；只生成文件，没有现场变更
python3 scripts/inspect_base_serial.py rules --profile serial-binding.confirmed.json > 99-insightrover-serial.rules
python3 scripts/prepare_serial_binding_deployment.py \
  --inventory inventory.json --profile serial-binding.confirmed.json --output serial-binding-bundle
```

实际规则由 VID/PID/interface/ID_PATH 精确匹配，示例（**只有物理角色确认后才可用**）：

```udev
ACTION!="add|change", GOTO="insightrover_serial_end"
SUBSYSTEM!="tty", GOTO="insightrover_serial_end"
ENV{ID_VENDOR_ID}=="1a86", ENV{ID_MODEL_ID}=="7523", ENV{ID_USB_INTERFACE_NUM}=="00", ENV{ID_PATH}=="platform-3610000.usb-usb-0:2.2.3:1.0", GROUP="dialout", MODE="0660", SYMLINK+="robot_base"
LABEL="insightrover_serial_end"
```

部署前再采集 inventory，并逐项校验 bundle manifest 的 before 指纹。新目标存在则先准确备份，不能按“预计不存在”覆盖。备份当前 user unit、启动脚本、规则目录中实际受影响文件、当前 profile（若存在），记录权限/所有者/链接目标。确认原有 lidar 规则不变，dialout 组权限存在，`sudo -n /usr/bin/fuser` 可用；没有权限就停在准备阶段，不改成 0777。

新 release 以当轮实际运行目录为底座，**不能直接把整个未提交本地工作区部署过去**。只叠加本轮清单中的新文件；launch/setup/package 三个既有文件只应用本次小补丁并检查上下文，不整文件覆盖。若车端在这些位置已有其他修改，停止并合并后重新验证。当前本地 HEAD 备份只用于本地回退，不冒充车端安装前备份；现场 before 指纹必须在真正部署前重新取得。

安装的具体文件仅限清单中的旧 `serial.rules` 修订、新 `99-insightrover-serial.rules`、`/etc/insightrover/serial-binding.json`，配置由 root 拥有且服务用户可读。服务已停且串口空闲时才 reload，并只对两个 CH340 的 sysfs 节点触发，不对整个 USB 树触发：

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --action=change --subsystem-match=tty --sysname-match=ttyUSB0
sudo udevadm trigger --action=change --subsystem-match=tty --sysname-match=ttyUSB2
sudo udevadm settle --timeout=10
# ttyUSB 编号必须从当轮 inventory 重新取得；这里是采集时示例，不能直接照旧编号执行。
sudo -n python3 scripts/inspect_base_serial.py preflight --profile /etc/insightrover/serial-binding.json
readlink -f /dev/robot_base
```

reload/trigger、安装文件和启动新服务都需要授权，不因准备了命令而自动执行。alias/身份或唯一性不符合预期就停止。新驱动在独立 release 构建，overlay 文件名必须属于包内 `verified_rosmaster.py`、`guarded_vendor_driver.py`；不修改全局 egg、vendor install、不依赖 PYTHONPATH 偶然覆盖系统 SDK。启动入口改成 `smart_car_decision verified_base_driver`。

回退时先保持停车/停止服务，保存失败诊断；对受影响文件核对当前内容仍等于本次 after 指纹，再恢复 before 文件和元数据，仅移除本次新文件，恢复原 unit 指向。若内容已被他人修改，不覆盖，先人工合并。不要删除现有工作区或其他 release。恢复原规则会恢复别名冲突，因此**不能自动重启旧服务**；应保持停机，或先在单独授权下恢复经过身份验证的唯一底盘绑定。回退不等于恢复了可驾驶状态。

## 阶段 B：传感器恢复（隔离静态验收已通过）

需要单独授权启动经过核验的新驱动。先独立启动底盘接收节点并把 cmd_vel 订阅重映射到一个无人发布的输入，灯光/蜂鸣器入口同样不接外部指令；此时不启动导航，不使用原整车服务让 UI 获得驾驶控制。示例命令需与新独立 release 的 overlay 一起执行：

```bash
source /opt/ros/humble/setup.bash
source "$ROOT/ros2_ws/install/setup.bash"
ros2 run smart_car_decision verified_base_driver --ros-args \
  -r cmd_vel:=/serial_validation/no_cmd_vel \
  -r RGBLight:=/serial_validation/no_rgb \
  -r Buzzer:=/serial_validation/no_buzzer
```

先确认这些输入没有发布者，然后核对驱动实际 fd、`/diagnostics` 有效帧计数、失效原因，以及原始 IMU 的重力响应与 gyro。没有新帧时原始 IMU/vel 不应继续重复发布新时间戳。通信故障的底盘固件停车能力不能仅凭零速 write 成功证明。验证链路前不运行故障注入或拔线。

原始反馈合格后，另行授权恢复原 Madgwick/base_node/EKF 链路，参数原样保持，再观察 `/imu/data`、`/odom_raw`、`/odom` 和 TF；不得只凭 SDK 有帧就宣称融合正常。若新入口或诊断不符预期，停止新节点并保持停止状态，按上述指纹规则回退文件。

还需静态核实 base_node/EKF 在原始输入停止后的行为；融合节点可能仍预测输出，所以 `/odom` 持续带新时间戳本身不代表底盘源健康，验收必须同时看原始有效帧及 `/diagnostics`。

## 阶段 C、D：运动及地图交接（本轮未执行）

A/B 均通过且再次获得明确现场运动授权，才安排低速短距离测试和失联停车验收。确认底盘实际位移、里程计与最终停车，再进入地图交接。不能因原始反馈恢复就跳过运动验收直接导航；本轮没有发送导航或速度指令。

航向跳变诊断只在真实底盘/IMU 数据恢复后继续，本轮不更改 3° 交接阈值、不改 EKF 融合项或 Madgwick 参数。

## 测试和证据清单

自动化测试以 `output/serial-binding-20261117/new-tests.xml`、`regression.xml` 为准。新增测试覆盖同型号 CH340、枚举改变、缺失/重复角色、路径与序列号交叉匹配、待确认 profile、旧端口覆盖、帧校验/分段/重同步、两类 IMU 符号与量纲、零缓存拒绝、超时、短写/读错、占用竞争、恢复不重放旧命令、生成驱动的无效反馈抑制与不重复时间戳、部署清单备份和指纹漂移。

结果：部署前最终串口相关 **42/42 通过**（0.70秒，`deploy-unit-tests.xml`）；此前扩展回归 **187通过、1失败**（188项，10.85秒，含当时的串口子集，不能与42相加）。唯一失败是工作区既有 `tests/test_navigation_config.py:266` 的 `fail_restart()` 替身不接受 `web_api.py:1237` 已有调用传入的 `validate_start` 参数。两处不属于本次串口改动，未改动它们，也未把失败记为通过。此前额外单独复核因自动审批额度限制未执行；完整回归保留原始异常栈。首次受限环境回归在FastAPI TestClient处挂起，结束该本机测试进程后在正常权限下完成上述完整回归。

生成驱动的集成测试使用本轮实际提取的 vendor 原文件；没有这些现场源文件的环境会明确 skip 这部分，通用绑定/协议/传输测试仍可运行。合成协议帧只用于离线单元测试，不是实车采样。

- 本地协议/绑定与生成覆盖层：已执行，见 JUnit。
- 本地控制、避障、导航参数回归：已执行，见 JUnit。
- Python 编译检查、`git diff --check`：已执行。
- 首轮阶段 A 仅接收采样：已执行，真实底盘协议数据有效，原始文件已校验下载；这不代表双向发送和运动控制验收。
- Jetson ROS2新入口构建、规则安装/定向重载、阶段B隔离静态ROS/Madgwick/里程计恢复：已执行通过。首次汇总脚本兼容性失败已按预案回退并保留原始数据，修正汇总后第二轮通过。
- 多设备重新插拔、枚举变化的实机验收、固件失联停车、车辆运动、导航、地图交接：未执行。

原始证据：`output/serial-binding-20261117/inventory.json`、`usb-history.json`、`final-readonly-check.json`、`vehicle-source-hashes.json`、`vehicle-sdk.py`、`vehicle-driver.py`；原故障输出与 raw IMU 证据在 `output/cannot-drive-20261117/`。记录不存在、无错误日志或正常样本都不能替代关键协议证据。

关键现行源码位置（均为本轮无损提取的副本）：`vehicle-sdk.py:20` 打开串口、`:73` 默认零缓存、`:130` 隐式舵机发送、`:256` 接收校验、`:1095` / `:1128` 缓存 getter；`vehicle-driver.py:32` 默认构造、`:68` 定时器、`:85` 下发速度、`:104` 取缓存发布、`:156` / `:162` 发布原始轮速与 IMU。
