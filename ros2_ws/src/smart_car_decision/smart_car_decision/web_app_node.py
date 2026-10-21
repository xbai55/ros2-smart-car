import json
import copy
import threading
import time
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import rclpy
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage, LaserScan
from std_msgs.msg import Bool, Float32, String

from .web_camera import CameraStream
from .mapping_session import MapSnapshotStore, MappingRestartManager
from .pose_debug_log import PoseDebugLog
from .mapping_settings import MappingSettings
from .mapping_recording import MappingInputRecorder
from .web_api import STATUS_STALE_SEC, create_app, resolve_bind_address
from .web_static import resolve_static_dir
from .web_video import AnnotatedFrameStore, should_release_camera_for_mode
from .web_state import RobotStateStore, normalize_tracking_target_request
from .navigation_config import NavigationConfigStore
from .navigation_map import NavigationMapStore


class WebAppNode(Node):
    def __init__(self):
        super().__init__("web_app_node")
        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 8080)
        self.declare_parameter("status_topic", "/robot/status")
        self.declare_parameter("mode_set_topic", "/robot/mode/set")
        self.declare_parameter("manual_cmd_topic", "/manual_cmd")
        self.declare_parameter("emergency_stop_set_topic", "/robot/emergency_stop/set")
        self.declare_parameter("speed_scale_topic", "/robot/speed_scale")
        self.declare_parameter("mode_obstacle_stop_distance_topic", "/robot/mode_obstacle_stop_distances")
        self.declare_parameter("color_config_topic", "/vision/color_config")
        self.declare_parameter("tracking_target_set_topic", "/vision/tracking_target/set")
        self.declare_parameter("annotated_frame_topic", "/vision/annotated_frame")
        self.declare_parameter("patrol_task_topic", "/patrol_task/set")
        self.declare_parameter("mission_task_topic", "/mission_task/set")
        self.declare_parameter("patrol_progress_topic", "/patrol_task/progress")
        self.declare_parameter("mission_state_topic", "/mission_task/state")
        self.declare_parameter("camera_source", "0")
        self.declare_parameter("video_fourcc", "MJPG")
        self.declare_parameter("video_width", 1280)
        self.declare_parameter("video_height", 720)
        self.declare_parameter("video_fps", 30.0)
        self.declare_parameter("video_target_fps", 12.0)
        self.declare_parameter("video_jpeg_quality", 75)
        self.declare_parameter("video_stream_width", 960)
        self.declare_parameter("annotated_stream_fps", 20.0)
        self.declare_parameter("static_dir", "")
        self.declare_parameter("navigation_config_path", "~/.ros/insightrover/lab-navigation.json")
        self.declare_parameter("navigation_robot_radius", 0.25)
        self.declare_parameter('safety_config_path', '~/.ros/insightrover/safety-vision.json')
        self.declare_parameter('safety_outbox_path', '~/.ros/insightrover/safety-events.sqlite3')
        self.declare_parameter('motion_mapping_settings_path', '~/.ros/insightrover/motion-mapping.json')
        self.declare_parameter('mapping_logs_directory', '~/.ros/insightrover/mapping_logs')
        self.safety_vision = None

        self.store = RobotStateStore()
        self.annotated_frames = AnnotatedFrameStore(max_age_sec=1.5)
        self.map_snapshot = MapSnapshotStore()
        self.navigation_map = NavigationMapStore()
        self._navigation_map_message = None
        self._navigation_map_lock = threading.RLock()
        self.navigation_map_pub = self.create_publisher(OccupancyGrid, "/navigation/map", QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE))
        self.pose_debug_log = PoseDebugLog()
        self.motion_settings = MappingSettings(self.get_parameter('motion_mapping_settings_path').value)
        self.mapping_recorder = MappingInputRecorder(self.get_parameter('mapping_logs_directory').value)
        self.mapping_restart = MappingRestartManager(self.get_logger(), self.map_snapshot,
                                                     ros_now_ns=lambda: self.get_clock().now().nanoseconds,
                                                     settings=self.motion_settings, recorder=self.mapping_recorder,
                                                     capture_initial_inputs=self.capture_mapping_inputs)
        self.camera_stream = None
        self._last_status_at = None
        self._ros2_data_warned = False
        self.mode_pub = self.create_publisher(String, self.get_parameter("mode_set_topic").value, 10)
        self.cmd_pub = self.create_publisher(String, self.get_parameter("manual_cmd_topic").value, 10)
        self.estop_pub = self.create_publisher(Bool, self.get_parameter("emergency_stop_set_topic").value, 10)
        self.speed_pub = self.create_publisher(Float32, self.get_parameter("speed_scale_topic").value, 10)
        self.turn_speed_pub = self.create_publisher(Float32, '/robot/turn_speed',
                                                    QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        turn = Float32()
        turn.data = self.motion_settings.snapshot()['turn_speed']
        self.turn_speed_pub.publish(turn)
        self.mode_obstacle_stop_distance_pub = self.create_publisher(String, self.get_parameter("mode_obstacle_stop_distance_topic").value, 10)
        self.color_config_pub = self.create_publisher(String, self.get_parameter("color_config_topic").value, 10)
        self.tracking_target_pub = self.create_publisher(String, self.get_parameter("tracking_target_set_topic").value, 10)
        self.patrol_task_pub = self.create_publisher(String, self.get_parameter("patrol_task_topic").value, 10)
        self.mission_task_pub = self.create_publisher(String, self.get_parameter("mission_task_topic").value, 10)
        self._startup_stop_pending = True
        self.create_timer(.2, self._confirm_startup_stop)
        self.create_subscription(String, self.get_parameter("status_topic").value, self.on_status, 10)
        self.create_subscription(OccupancyGrid, "/map", self.on_map, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE))
        self.create_subscription(
            CompressedImage,
            self.get_parameter("annotated_frame_topic").value,
            self.on_annotated_frame,
            2,
        )
        self.create_subscription(String, self.get_parameter("patrol_progress_topic").value, self.on_patrol_progress, 10)
        self.create_subscription(String, self.get_parameter("mission_state_topic").value, self.on_mission_state, 10)
        self.create_timer(5.0, self._check_ros2_health)
        self.create_timer(0.2, self.mapping_restart.snapshot)

        self.navigation_config = None
        try:
            self.navigation_config = NavigationConfigStore(self.get_parameter("navigation_config_path").value)
        except (ValueError, OSError) as exc:
            self.get_logger().error(f"导航配置读取失败，保留原文件：{exc}")
        self.navigation_radius = float(self.get_parameter("navigation_robot_radius").value)
        from .navigation_runtime import NavigationRuntime
        from geometry_msgs.msg import PoseWithCovarianceStamped
        self.navigation_runtime = NavigationRuntime(self)
        try:
            from nav2_msgs.msg import CostmapFilterInfo
            self.create_subscription(CostmapFilterInfo, '/navigation/keepout_filter_info', self.navigation_runtime.observe_keepout_info,
                                     QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE))
        except ImportError:
            self.get_logger().warning('Nav2 消息未安装，禁行地图不可用于导航')
        self.create_subscription(OccupancyGrid, '/navigation/keepout_mask', self.navigation_runtime.observe_keepout,
                                 QoSProfile(depth=1,durability=DurabilityPolicy.TRANSIENT_LOCAL,reliability=ReliabilityPolicy.RELIABLE))
        self.initial_pose_pub = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        from std_srvs.srv import Empty
        self.localization_update_client = self.create_client(Empty, "/request_nomotion_update")
        self.create_timer(1.0, self.navigation_runtime.request_update)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self.navigation_runtime.observe_pose, 10)
        self.navigation = None
        try:
            from .navigation_bridge import NavigationBridge
            self.navigation = NavigationBridge(self, self.navigation_radius)
        except ImportError as exc:
            self.get_logger().warning(f"Nav2 依赖未安装，导航暂不可用：{exc}")

        self.navigation_tasks = None
        if self.navigation:
            from .navigation_tasks import NavigationTaskRunner
            try:
                self.navigation_tasks = NavigationTaskRunner(self)
            except (ValueError, OSError) as exc:
                self.get_logger().error(f"导航任务记录读取失败，保留原文件：{exc}")

        from tf2_ros import Buffer, TransformListener
        self.safety_tf_buffer = Buffer()
        self.safety_tf_listener = TransformListener(self.safety_tf_buffer, self)
        self.create_subscription(LaserScan, '/scan', self.on_safety_scan, 2)
        self.create_subscription(Odometry, '/odom', self.on_task_odom, 10)

        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
        self.get_logger().info(
            f"Web/PWA control server starting on {self.get_parameter('host').value}:{self.get_parameter('port').value}"
        )

    def on_status(self, msg):
        self._last_status_at = time.monotonic()
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("忽略无效的 /robot/status JSON")
            return
        if data.get("mode") == "stop":
            self._startup_stop_pending = False
        snapshot = self.store.update(**data)
        self.pose_debug_log.append_status(snapshot)
        self.mapping_restart.observe_status(snapshot)

    def on_task_odom(self, msg):
        if self.navigation_tasks:
            p = msg.pose.pose.position
            stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
            self.navigation_tasks.observe_odometry(p.x, p.y, stamp)

    def on_safety_scan(self, msg):
        if not self.safety_vision:
            return
        import math
        from rclpy.time import Time
        try:
            stamp = Time.from_msg(msg.header.stamp)
            if abs((self.get_clock().now() - stamp).nanoseconds / 1e9) > .6:
                return
            tf = self.safety_tf_buffer.lookup_transform('map', msg.header.frame_id, stamp).transform
            q = tf.rotation
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            points = []
            for i, distance in enumerate(msg.ranges):
                if math.isfinite(distance) and msg.range_min < distance < min(msg.range_max, 5.):
                    angle = msg.angle_min + i * msg.angle_increment + yaw
                    points.append((tf.translation.x + distance * math.cos(angle), tf.translation.y + distance * math.sin(angle)))
            self.safety_vision.update_scan(points)
        except Exception:
            # A missing transform is unavailable evidence, never a synthetic obstacle.
            return

    def _confirm_startup_stop(self):
        if self._startup_stop_pending:
            self.set_command("stop")
            self.set_mode("stop")

    def on_patrol_progress(self, msg):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("忽略无效的巡检进度 JSON")
            return
        self.store.set_patrol_task({"action": "progress", "progress": data.get("progress")})

    def on_mission_state(self, msg):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("忽略无效的运输任务状态 JSON")
            return
        self.store.set_mission_task(data)

    def ros_status_age_sec(self):
        """距上一次收到 /robot/status 的秒数；从未收到时返回 None。"""
        if self._last_status_at is None:
            return None
        return max(0.0, time.monotonic() - self._last_status_at)

    def _check_ros2_health(self):
        age = self.ros_status_age_sec()
        stalled = age is None or age > STATUS_STALE_SEC
        if stalled and not self._ros2_data_warned:
            self._ros2_data_warned = True
            detail = "尚未收到任何状态" if age is None else f"已 {age:.1f}s 未收到状态"
            self.get_logger().warning(f"ROS2 状态数据异常：{detail}，请检查 system_status_node 与 /robot/status")
        elif not stalled and self._ros2_data_warned:
            self._ros2_data_warned = False
            self.get_logger().info("ROS2 状态数据已恢复")

    def on_annotated_frame(self, msg):
        self.annotated_frames.update(bytes(msg.data))

    def on_map(self, msg):
        with self._navigation_map_lock:
            if not self.mapping_restart.on_map(msg):
                return
            self._navigation_map_message = msg
            self.refresh_navigation_map()

    def refresh_navigation_map(self):
        with self._navigation_map_lock:
            source = self.map_snapshot.snapshot()
            config = self.navigation_config.snapshot() if self.navigation_config else {}
            if self.navigation_map.update(source, config.get("calibration")) and self._navigation_map_message is not None:
                message = copy.deepcopy(self._navigation_map_message)
                snapshot = self.navigation_map.snapshot()
                if snapshot is not None and len(message.data) == len(snapshot["data"]):
                    message.data = snapshot["data"]
                    self.navigation_map_pub.publish(message)

    def set_mode(self, mode):
        previous = self.store.snapshot().get("mode")
        mode = self.store.set_mode(mode)
        if should_release_camera_for_mode(mode) and self.camera_stream is not None:
            self.camera_stream.close()
        msg = String()
        msg.data = mode
        self.mode_pub.publish(msg)
        if previous == "mapping" and mode != "mapping":
            self.mapping_restart.stop_mapping()
        return mode

    def set_command(self, command):
        command = self.store.set_command(command)
        msg = String()
        msg.data = command
        self.cmd_pub.publish(msg)
        return command

    def set_emergency_stop(self, enabled):
        state = self.store.set_emergency_stop(enabled)
        msg = Bool()
        msg.data = state
        self.estop_pub.publish(msg)
        if state:
            stop = String()
            stop.data = "stop"
            self.cmd_pub.publish(stop)
        return state

    def set_speed_scale(self, value):
        scale = self.store.set_speed_scale(value)
        msg = Float32()
        msg.data = float(scale)
        self.speed_pub.publish(msg)
        return scale

    def set_motion_settings(self, changes):
        settings = self.motion_settings.update(**changes)
        if "turn_speed" in changes:
            msg = Float32()
            msg.data = settings["turn_speed"]
            self.turn_speed_pub.publish(msg)
        if self.mapping_recorder.snapshot()["state"] == "recording":
            self.mapping_recorder.event("settings_changed", settings=settings)
        return settings

    def capture_mapping_inputs(self):
        """Publish unchanged initial controls after recorder subscription discovery."""
        snapshot = self.store.snapshot()
        self.set_command("stop")
        self.set_speed_scale(snapshot["speed_scale"])
        self.set_mode("mapping")
        turn = Float32()
        turn.data = self.motion_settings.snapshot()["turn_speed"]
        self.turn_speed_pub.publish(turn)
        self.mapping_recorder.event("initial_control_state", mode="mapping", command="stop",
                                    speed_scale=snapshot["speed_scale"], turn_speed=turn.data)

    def set_color_config(self, payload):
        config = self.store.set_color_config(payload)
        msg = String()
        msg.data = json.dumps(config, ensure_ascii=False)
        self.color_config_pub.publish(msg)
        return config

    def set_mode_obstacle_stop_distance(self, mode, distance):
        distances = self.store.set_mode_obstacle_stop_distance(mode, distance)
        msg = String()
        msg.data = json.dumps(distances, ensure_ascii=False)
        self.mode_obstacle_stop_distance_pub.publish(msg)
        return distances

    def set_tracking_target(self, payload):
        request = normalize_tracking_target_request(payload)
        msg = String()
        msg.data = json.dumps(request, ensure_ascii=False)
        self.tracking_target_pub.publish(msg)
        return request

    def set_patrol_task(self, payload):
        task = self.store.set_patrol_task(payload)
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.patrol_task_pub.publish(msg)
        self.get_logger().info(f"下发巡检任务：{msg.data}")
        return task

    def set_mission_task(self, payload):
        task = self.store.set_mission_task(payload)
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self.mission_task_pub.publish(msg)
        self.get_logger().info(f"下发运输任务：{msg.data}")
        return task

    def _run_server(self):
        try:
            import cv2
            import uvicorn
        except ImportError as exc:
            self.get_logger().error(f"Web 服务依赖缺失，无法启动 HTTP 服务：{exc}")
            return

        node = self
        camera = CameraStream(
            str(self.get_parameter("camera_source").value),
            cv2,
            lambda: node.store.snapshot().get("mode", "stop"),
            capture_fps=float(self.get_parameter("video_fps").value),
            target_fps=float(self.get_parameter("video_target_fps").value),
            camera_fourcc=str(self.get_parameter("video_fourcc").value),
            camera_width=int(self.get_parameter("video_width").value),
            camera_height=int(self.get_parameter("video_height").value),
            jpeg_quality=int(self.get_parameter("video_jpeg_quality").value),
            stream_width=int(self.get_parameter("video_stream_width").value),
        )
        node.camera_stream = camera
        from .safety_vision import SafetyVisionWorker
        try:
            node.safety_vision = SafetyVisionWorker(node, camera, self.get_parameter('safety_config_path').value,
                                                   self.get_parameter('safety_outbox_path').value)
            node.safety_vision.start()
        except (ValueError, OSError) as exc:
            self.get_logger().error(f'巡检证据存储不可用：{exc}')
        annotated_stream = AnnotatedFrameStream(
            node.annotated_frames,
            target_fps=float(self.get_parameter("annotated_stream_fps").value),
        )

        static_dir = self._resolve_web_static_dir()
        app = create_app(node, camera=camera, annotated_stream=annotated_stream, static_dir=static_dir)

        host, port = resolve_bind_address(
            self.get_parameter("host").value,
            self.get_parameter("port").value,
        )
        self.get_logger().info(f"车端 Web Node 监听 http://{host}:{port}（静态资源：{static_dir}）")
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        uvicorn.Server(config).run()

    def _resolve_web_static_dir(self):
        """定位 Web 控制台静态资源目录，兼容「已安装」与「源码直接运行」两种方式。"""
        fallback = Path(__file__).resolve().parents[1] / "web" / "static"
        try:
            package_static_dir = Path(get_package_share_directory("smart_car_decision")) / "web" / "static"
        except Exception as exc:
            self.get_logger().warning(f"无法定位安装后的静态资源目录：{exc}")
            package_static_dir = fallback
        configured = str(self.get_parameter("static_dir").value or "")
        resolved = resolve_static_dir(configured, package_static_dir)
        return resolved if resolved.is_dir() else resolve_static_dir(configured, fallback)


class AnnotatedFrameStream:
    def __init__(self, store, target_fps=20.0):
        self.store = store
        self.target_fps = max(1.0, float(target_fps))

    def latest_frame(self):
        return self.store.latest()

    def frame_snapshot(self):
        return self.store.snapshot()

    def frames(self):
        last_version = 0
        timeout = 1.0 / self.target_fps
        while True:
            frame, last_version = self.store.wait_for_frame(
                last_version=last_version,
                timeout=timeout,
            )
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )


def main():
    rclpy.init()
    node = WebAppNode()
    logger = node.get_logger()
    logger.info(f"ROS2 初始化完成，车端 Web Node 已启动（节点 {node.get_name()}）")
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在关闭车端 Web Node")
    finally:
        logger.info("车端 Web Node 退出")
        try:
            if node.safety_vision:
                node.safety_vision.close()
            if node.camera_stream is not None:
                node.camera_stream.close()
            node.mapping_restart.close()
            node.navigation_runtime.stop()
        finally:
            node.destroy_node()
            rclpy.shutdown()


if __name__ == "__main__":
    main()
