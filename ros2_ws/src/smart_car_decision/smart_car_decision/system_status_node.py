import json
import math
import time

import rclpy
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Float32, String
from tf2_ros import Buffer, TransformException, TransformListener
from geometry_msgs.msg import Twist

from .common import front_range_statistic, normalize_command
from .lidar_health import ScanRateWindow, evaluate_lidar_health, scan_quality
from .map_health import evaluate_map_health
from .mapping_quality import evaluate_mapping_quality
from .odom_health import evaluate_odom_health
from .scan_visualization import simplify_scan_points
from .tf_health import evaluate_tf_health


class SystemStatusNode(Node):
    def __init__(self):
        super().__init__("system_status_node")
        self.declare_parameter("status_topic", "/robot/status")
        self.declare_parameter("mode_topic", "/robot/mode")
        self.declare_parameter("emergency_stop_topic", "/robot/emergency_stop")
        self.declare_parameter("speed_scale_topic", "/robot/speed_scale")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("detection_topic", "/vision/detection")
        self.declare_parameter("color_target_topic", "/vision/color_target")
        self.declare_parameter("tracking_target_topic", "/vision/tracking_target")
        self.declare_parameter("lane_offset_topic", "/lane/offset")
        self.declare_parameter("map_topic", "/map")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("odom_timeout_sec", 1.0)
        self.declare_parameter("cmd_vel_timeout_sec", 0.7)
        self.declare_parameter("tf_parent_frame", "odom")
        self.declare_parameter("tf_child_frame", "base_link")
        self.declare_parameter("tf_check_period_sec", 0.5)
        self.declare_parameter("front_angle_deg", 35.0)
        self.declare_parameter("front_center_deg", 180.0)
        self.declare_parameter("front_distance_percentile", 20.0)
        self.declare_parameter("scan_timeout_sec", 0.6)
        self.declare_parameter("health_window_size", 20)
        self.declare_parameter("min_valid_ratio", 0.05)
        self.declare_parameter("map_timeout_sec", 5.0)
        self.declare_parameter("publish_rate_hz", 2.0)

        self.state = {
            "mode": "stop",
            "emergency_stop": False,
            "front_distance": None,
            "detection": "",
            "color_target": None,
            "tracking_target": {"selection_mode": "auto", "state": "searching", "locked": False, "track_id": None},
            "lane_offset": 0.0,
            "radar_points": [],
            "lidar": {
                "ok": False,
                "message": "no_data",
                "scan_age_sec": None,
                "scan_rate_hz": 0.0,
                "valid_count": 0,
                "valid_ratio": 0.0,
                "frame_id": "",
            },
            "map": {
                "ok": False,
                "message": "no_map",
                "map_age_sec": None,
                "width": 0,
                "height": 0,
                "resolution": 0.0,
                "frame_id": "",
            },
            "odom": {
                "ok": False,
                "message": "no_odom",
                "odom_age_sec": None,
                "frame_id": "",
                "child_frame_id": "",
                "linear_speed": 0.0,
                "angular_speed": 0.0,
            },
            "cmd_vel": {
                "ok": False,
                "message": "no_cmd_vel",
                "age_sec": None,
                "linear_x": 0.0,
                "linear_y": 0.0,
                "angular_z": 0.0,
                "updated_at": None,
            },
            "tf": {
                "ok": False,
                "message": "unavailable",
                "checked_at": None,
                "parent_frame": "odom",
                "child_frame": "base_link",
            },
            "map_pose": {
                "ok": False,
                "message": "unavailable",
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "frame_id": "map",
                "child_frame_id": "base_link",
                "updated_at": None,
            },
            "mapping_quality": {
                "ok": False,
                "level": "bad",
                "message": "lidar,map,odom,tf",
                "issues": ["lidar", "map", "odom", "tf"],
            },
            "speed_scale": 1.0,
            "camera": {"ok": None, "message": "unknown"},
            "nodes": {"system_status_node": "ok"},
            "updated_at": time.time(),
        }

        self.status_pub = self.create_publisher(String, self.get_parameter("status_topic").value, 10)
        self.create_subscription(String, self.get_parameter("mode_topic").value, self.on_mode, 10)
        self.create_subscription(Bool, self.get_parameter("emergency_stop_topic").value, self.on_estop, 10)
        self.create_subscription(Float32, self.get_parameter("speed_scale_topic").value, self.on_speed_scale, 10)
        self.create_subscription(LaserScan, self.get_parameter("scan_topic").value, self.on_scan, 10)
        self.create_subscription(String, self.get_parameter("detection_topic").value, self.on_detection, 10)
        self.create_subscription(String, self.get_parameter("color_target_topic").value, self.on_color_target, 10)
        self.create_subscription(String, self.get_parameter("tracking_target_topic").value, self.on_tracking_target, 10)
        self.create_subscription(Float32, self.get_parameter("lane_offset_topic").value, self.on_lane_offset, 10)
        self.create_subscription(OccupancyGrid, self.get_parameter("map_topic").value, self.on_map, 10)
        self.create_subscription(Odometry, self.get_parameter("odom_topic").value, self.on_odom, 10)
        self.create_subscription(Twist, self.get_parameter("cmd_vel_topic").value, self.on_cmd_vel, 10)
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.front_angle_rad = float(self.get_parameter("front_angle_deg").value) * 3.1415926 / 180.0
        self.front_center_rad = float(self.get_parameter("front_center_deg").value) * 3.1415926 / 180.0
        self.front_distance_percentile = float(self.get_parameter("front_distance_percentile").value)
        self.scan_timeout_sec = float(self.get_parameter("scan_timeout_sec").value)
        self.min_valid_ratio = float(self.get_parameter("min_valid_ratio").value)
        self.scan_rate = ScanRateWindow(self.get_parameter("health_window_size").value)
        self.last_scan_time = None
        self.scan_valid_count = 0
        self.scan_valid_ratio = 0.0
        self.scan_frame_id = ""
        self.map_timeout_sec = float(self.get_parameter("map_timeout_sec").value)
        self.last_map_time = None
        self.map_width = 0
        self.map_height = 0
        self.map_resolution = 0.0
        self.map_frame_id = ""
        self.odom_timeout_sec = float(self.get_parameter("odom_timeout_sec").value)
        self.cmd_vel_timeout_sec = float(self.get_parameter("cmd_vel_timeout_sec").value)
        self.last_odom_time = None
        self.last_cmd_vel_time = None
        self.odom_frame_id = ""
        self.odom_child_frame_id = ""
        self.odom_linear_speed = 0.0
        self.odom_angular_speed = 0.0
        self.cmd_vel_linear_x = 0.0
        self.cmd_vel_linear_y = 0.0
        self.cmd_vel_angular_z = 0.0
        self.tf_parent_frame = str(self.get_parameter("tf_parent_frame").value)
        self.tf_child_frame = str(self.get_parameter("tf_child_frame").value)
        self.last_tf_status = evaluate_tf_health(
            ok=False,
            message="unavailable",
            checked_at=None,
            parent_frame=self.tf_parent_frame,
            child_frame=self.tf_child_frame,
        )
        rate = float(self.get_parameter("publish_rate_hz").value)
        self.create_timer(1.0 / rate, self.publish_status)
        self.create_timer(float(self.get_parameter("tf_check_period_sec").value), self.refresh_tf_status)

    def on_mode(self, msg):
        self.state["mode"] = normalize_command(msg.data) or "stop"
        self._touch()

    def on_estop(self, msg):
        self.state["emergency_stop"] = bool(msg.data)
        self._touch()

    def on_speed_scale(self, msg):
        self.state["speed_scale"] = round(float(msg.data), 3)
        self._touch()

    def on_scan(self, scan):
        now = time.monotonic()
        quality = scan_quality(scan)
        self.last_scan_time = now
        self.scan_rate.add(now)
        self.scan_valid_count = quality.valid_count
        self.scan_valid_ratio = quality.valid_ratio
        self.scan_frame_id = getattr(getattr(scan, "header", None), "frame_id", "")
        distance = front_range_statistic(
            scan,
            center_angle_rad=self.front_center_rad,
            half_width_rad=self.front_angle_rad,
            percentile=self.front_distance_percentile,
        )
        self.state["front_distance"] = None if distance == float("inf") else round(distance, 3)
        self.state["radar_points"] = simplify_scan_points(
            scan, max_points=96, rotation_rad=self.front_center_rad
        )
        self._refresh_lidar(now)
        self._touch()

    def on_detection(self, msg):
        self.state["detection"] = normalize_command(msg.data)
        self._touch()

    def on_color_target(self, msg):
        try:
            self.state["color_target"] = json.loads(msg.data)
        except json.JSONDecodeError:
            self.state["color_target"] = {"raw": msg.data}
        self._touch()

    def on_lane_offset(self, msg):
        self.state["lane_offset"] = round(float(msg.data), 4)
        self._touch()

    def on_tracking_target(self, msg):
        try:
            self.state["tracking_target"] = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        self._touch()

    def on_map(self, msg):
        self.last_map_time = time.monotonic()
        self.map_width = int(msg.info.width)
        self.map_height = int(msg.info.height)
        self.map_resolution = float(msg.info.resolution)
        self.map_frame_id = str(msg.header.frame_id)
        self._refresh_map(self.last_map_time)
        self._touch()

    def on_odom(self, msg):
        self.last_odom_time = time.monotonic()
        self.odom_frame_id = str(msg.header.frame_id)
        self.odom_child_frame_id = str(msg.child_frame_id)
        self.odom_linear_speed = float(msg.twist.twist.linear.x)
        self.odom_angular_speed = float(msg.twist.twist.angular.z)
        self._refresh_odom(self.last_odom_time)
        self._touch()

    def on_cmd_vel(self, msg):
        self.last_cmd_vel_time = time.monotonic()
        self.cmd_vel_linear_x = float(msg.linear.x)
        self.cmd_vel_linear_y = float(msg.linear.y)
        self.cmd_vel_angular_z = float(msg.angular.z)
        self._refresh_cmd_vel(self.last_cmd_vel_time)
        self._touch()

    def publish_status(self):
        now = time.monotonic()
        self._refresh_lidar(now)
        self._refresh_map(now)
        self._refresh_odom(now)
        self._refresh_cmd_vel(now)
        self.state["tf"] = self.last_tf_status
        self._refresh_mapping_quality()
        self._touch()
        msg = String()
        msg.data = json.dumps(self.state, ensure_ascii=False)
        self.status_pub.publish(msg)

    def refresh_tf_status(self):
        checked_at = time.time()
        try:
            self.tf_buffer.lookup_transform(
                self.tf_parent_frame,
                self.tf_child_frame,
                rclpy.time.Time(),
            )
            self.last_tf_status = evaluate_tf_health(
                ok=True,
                message="ok",
                checked_at=checked_at,
                parent_frame=self.tf_parent_frame,
                child_frame=self.tf_child_frame,
            )
            self._refresh_map_pose(checked_at)
        except TransformException as exc:
            self.last_tf_status = evaluate_tf_health(
                ok=False,
                message=type(exc).__name__,
                checked_at=checked_at,
                parent_frame=self.tf_parent_frame,
                child_frame=self.tf_child_frame,
            )

    def _refresh_map_pose(self, checked_at):
        try:
            transform = self.tf_buffer.lookup_transform(
                "map",
                self.tf_child_frame,
                rclpy.time.Time(),
            )
        except TransformException as exc:
            self.state["map_pose"] = {
                "ok": False,
                "message": type(exc).__name__,
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "frame_id": "map",
                "child_frame_id": self.tf_child_frame,
                "updated_at": checked_at,
            }
            return

        rotation = transform.transform.rotation
        siny_cosp = 2.0 * (rotation.w * rotation.z + rotation.x * rotation.y)
        cosy_cosp = 1.0 - 2.0 * (rotation.y * rotation.y + rotation.z * rotation.z)
        translation = transform.transform.translation
        self.state["map_pose"] = {
            "ok": True,
            "message": "ok",
            "x": round(float(translation.x), 4),
            "y": round(float(translation.y), 4),
            "yaw": round(math.atan2(siny_cosp, cosy_cosp), 4),
            "frame_id": "map",
            "child_frame_id": self.tf_child_frame,
            "updated_at": checked_at,
        }

    def _refresh_lidar(self, now):
        self.state["lidar"] = evaluate_lidar_health(
            last_scan_time=self.last_scan_time,
            now=now,
            timeout_sec=self.scan_timeout_sec,
            rate_hz=self.scan_rate.rate_hz,
            valid_count=self.scan_valid_count,
            valid_ratio=self.scan_valid_ratio,
            min_valid_ratio=self.min_valid_ratio,
            frame_id=self.scan_frame_id,
        )

    def _refresh_map(self, now):
        self.state["map"] = evaluate_map_health(
            last_map_time=self.last_map_time,
            now=now,
            timeout_sec=self.map_timeout_sec,
            width=self.map_width,
            height=self.map_height,
            resolution=self.map_resolution,
            frame_id=self.map_frame_id,
        )

    def _refresh_odom(self, now):
        self.state["odom"] = evaluate_odom_health(
            last_odom_time=self.last_odom_time,
            now=now,
            timeout_sec=self.odom_timeout_sec,
            frame_id=self.odom_frame_id,
            child_frame_id=self.odom_child_frame_id,
            linear_speed=self.odom_linear_speed,
            angular_speed=self.odom_angular_speed,
        )

    def _refresh_cmd_vel(self, now):
        if self.last_cmd_vel_time is None:
            self.state["cmd_vel"] = {
                "ok": False,
                "message": "no_cmd_vel",
                "age_sec": None,
                "linear_x": 0.0,
                "linear_y": 0.0,
                "angular_z": 0.0,
                "updated_at": None,
            }
            return
        age = max(0.0, now - self.last_cmd_vel_time)
        stale = age > self.cmd_vel_timeout_sec
        self.state["cmd_vel"] = {
            "ok": not stale,
            "message": "stale" if stale else "ok",
            "age_sec": round(age, 3),
            "linear_x": round(self.cmd_vel_linear_x, 4),
            "linear_y": round(self.cmd_vel_linear_y, 4),
            "angular_z": round(self.cmd_vel_angular_z, 4),
            "updated_at": time.time(),
        }

    def _refresh_mapping_quality(self):
        self.state["mapping_quality"] = evaluate_mapping_quality(
            lidar=self.state["lidar"],
            map_status=self.state["map"],
            odom=self.state["odom"],
            tf_status=self.state["tf"],
            speed_scale=self.state["speed_scale"],
        )

    def _touch(self):
        self.state["updated_at"] = time.time()


def main():
    rclpy.init()
    node = SystemStatusNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
