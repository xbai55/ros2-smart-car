import json
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Float32, String

from .common import min_front_range, normalize_command


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
        self.declare_parameter("lane_offset_topic", "/lane/offset")
        self.declare_parameter("front_angle_deg", 35.0)
        self.declare_parameter("publish_rate_hz", 2.0)

        self.state = {
            "mode": "stop",
            "emergency_stop": False,
            "front_distance": None,
            "detection": "",
            "color_target": None,
            "lane_offset": 0.0,
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
        self.create_subscription(Float32, self.get_parameter("lane_offset_topic").value, self.on_lane_offset, 10)
        self.front_angle_rad = float(self.get_parameter("front_angle_deg").value) * 3.1415926 / 180.0
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
        distance = min_front_range(scan, self.front_angle_rad)
        self.state["front_distance"] = None if distance == float("inf") else round(distance, 3)
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

    def publish_status(self):
        msg = String()
        msg.data = json.dumps(self.state, ensure_ascii=False)
        self.status_pub.publish(msg)

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
