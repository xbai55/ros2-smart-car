# 实验室导航

实车工作区 `/robots/r-001/run` 默认显示重绘的实验室平面图。T 形为讲台，中间长条为实验台，底部缺口为门。老师处是讲台旁的停车点，目的朝向讲台；门口点位于门内。

用户可以点击空地或选择预设地点，点击“预览路线”，确认后点击“开始导航”。预览请求只计算路径，不切换运动模式。未连接小车或未完成对齐时，图中的蓝线只是从门口出发的结构示例，不能执行。保存地点需要完成地图对齐，地点名称和位置存储在小车 `~/.ros/insightrover/lab-navigation.json` 中，重启后保留。

全局规划统一使用 A*：前端结构示例为四方向网格 A*；车端在 `config/navigation.yaml` 明确设置 NavFn 的 `use_astar: true`，局部控制明确使用 DWB。在线预览和执行都调用车端 Nav2，前端示例与实车的地图、代价和路径形状可以不同。更新车端工作区并重新启动导航后配置生效，可用 `ros2 param get /planner_server GridBased.use_astar` 核对，应返回 `True`。

独立“地图”页面现已接入业务数据库，支持上传 PNG/JPG/WebP 图片、删除未关联路线或任务的地图、修改名称/区域/备注/启用状态，以及点击图片新增、编辑、移动和删除地点。地图记录保存在 `maps`，地点保存在 `map_places`，图片由对象存储保存；默认使用项目 `backend/smart_patrol.db` 与 `backend/storage/maps/`。普通图片的标注采用左上角为原点的图片像素坐标。这里的地图库尚未自动切换实车 Nav2 地图，也未把图片坐标自动转换成车端的米制目标；实车导航仍使用上述已对齐的实验室地图。上传图片不代表已完成实车定位对齐。

## 车端部署

此实现面向项目的 ROS2 Humble，Windows 端可以构建前端和测试接口，但无法证明实车行驶效果。需要在 Jetson 更新源码、构建 ROS2 工作区并部署 `web-console/dist`。现有 `decision.yaml` 的 `web_app_node.static_dir` 指向 `/home/jetson/ros2-smart-car/web-console/dist`；更换项目路径时需一起修改。

1. 安装 `ros-humble-navigation2`、`ros-humble-nav2-bringup`，执行项目原有的 `colcon build` 并加载环境。
2. 完成 SLAM 建图，保存包含实验台和讲台的地图。停止 SLAM 的定位发布进程，避免与 AMCL 同时发布 `map → odom`；保持底盘、雷达、里程计、决策控制和 Web 服务运行。
3. 启动 `ros2 launch smart_car_decision navigation.launch.py map:=/绝对路径/lab.yaml`。此启动文件包含地图服务、AMCL 和 Nav2，不重复启动底盘。
4. 在 RViz 使用“2D Pose Estimate”指定小车当前实际位置与朝向，确认雷达与地图重合、地图定位有效。
5. 点击前端“地图对齐”，在概图与实际地图上依次选择四组对应点。选择分散的墙角、实验台端点；不能全部在一条直线上。四点拟合误差超过 10 cm 会拒绝保存，需重新选点或修正示意图比例。地图宽高、原点、分辨率或坐标系变化后必须重新对齐。
6. 测量小车外形，把 `config/navigation.yaml` 的两个 `robot_radius` 和 Web 节点的 `navigation_robot_radius` 设为相同的实际包络半径；默认 0.25 m 是部署起始值。初次试车选择附近空地、低速验证停车位置与朝向。

示意图没有米制尺寸，采用四点仿射对齐，包括比例、旋转和上下方向变换。任意点击换算成真实 `map` 坐标后交给 Nav2；实车地图是判断能否通行的依据。若概图无法准确表达实物比例，四点对齐也不能保证任意位置准确，应先修正平面图。

使用内置实验室平面图时，讲台、实验台和墙体轮廓作为固定障碍叠加在真实地图上，发布 `/navigation/map`，供 Nav2 的全局和局部静态障碍层使用。这样即使雷达只扫到桌腿，路径也不能从实验台下方穿过。AMCL 和对齐画布仍使用原始 `/map`。未对齐时导航地图全为不可通行；对齐变化后旧路线预览失效。由于原图是概图，轮廓宽度同样需要现场核对。

2026-10-13 的更新支持选择用户上传的平面图，以实际图片尺寸完成四点标定，并在统一的 SLAM 画布中叠加图片、地点和路线。上传图片只作视觉参考，导航地图保留实测占据数据，不注入上述实验室轮廓。操作、坐标边界与验证记录见 [上传平面图与 SLAM 的标定和可视化](map-registration-and-visualization.md)。这项更新已配套部署并完成静止链路验证，实际对应点标定和实车导航仍待验收。

参数与速度话题依据 [Nav2 Humble 官方配置](https://github.com/ros-navigation/navigation2/blob/humble/nav2_bringup/params/nav2_params.yaml) 和 [导航启动文件](https://github.com/ros-navigation/navigation2/blob/humble/nav2_bringup/launch/navigation_launch.py) 核对。静态地图使用持久订阅，以便 Web 服务重启后收到已发布的地图。

## 控制与状态

`ComputePathToPose` 提供预览；`NavigateToPose` 执行目标并动态重新规划。因此行驶路线可能随现场障碍变化。预览 60 秒后失效，开始前会重新检查目标、定位、雷达、急停和地图。

Nav2 控制器和恢复动作输出 `/navigation/raw_cmd_vel`，速度平滑器输出 `/navigation/cmd_vel`，`decision_controller` 是 `/cmd_vel` 的唯一发布者。只有导航模式才放行新鲜导航指令；指令超时、雷达过期、急停或前方防撞距离不足会输出零速度。导航服务、定位失效或地图坐标变化会取消任务并切换停止模式。

目前配置沿用 DWB 的前进加转向导航，X3 的横移仍可用于手动控制。狭窄实验台旁的可通行性取决于实测车体尺寸、地图和防撞阈值，需要现场验证。

新增接口：GET `/api/navigation/config`、GET `/api/navigation/status`、POST `/api/navigation/calibration`、POST `/api/navigation/places`、DELETE `/api/navigation/places/{id}`、POST `/api/navigation/plan`、POST `/api/navigation/start`、POST `/api/navigation/cancel`。`/api/status` 和 `/ws/status` 带导航状态、路径和剩余距离。地图对齐与预设地点修改沿用现有车端控制台访问方式，尚未接入业务后台的用户权限管理。
