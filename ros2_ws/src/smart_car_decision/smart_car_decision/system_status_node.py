import json
import time

import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Float32, String

from .common import front_range_statistic, normalize_command
from .lidar_health import ScanRateWindow, evaluate_lidar_health, scan_quality
from .map_health import evaluate_map_health
from .scan_visualization import simplify_scan_points


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
        rate = float(self.get_parameter("publish_rate_hz").value)
        self.create_timer(1.0 / rate, self.publish_status)

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

    def publish_status(self):
        now = time.monotonic()
        self._refresh_lidar(now)
        self._refresh_map(now)
        self._touch()
        msg = String()
        msg.data = json.dumps(self.state, ensure_ascii=False)
        self.status_pub.publish(msg)

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
