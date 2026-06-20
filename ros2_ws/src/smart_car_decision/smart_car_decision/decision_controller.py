import math
import time

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Float32, String

from .common import front_range_statistic, normalize_command
from .control_policy import decide_motion, normalize_mode


class DecisionController(Node):
    def __init__(self):
        super().__init__("decision_controller")
        self._declare_parameters()
        self._load_parameters()

        self.front_distance = float("inf")
        self.last_scan_time = 0.0
        self.detection = ""
        self.last_detection_time = 0.0
        self.lane_offset = 0.0
        self.last_lane_time = 0.0
        self.manual_command = "stop"
        self.last_manual_time = 0.0
        self.mode = "stop"
        self.emergency_stop = False
        self.speed_scale = 1.0

        self.publisher = self.create_publisher(Twist, self.cmd_vel_topic, 10)
        self.create_subscription(LaserScan, self.scan_topic, self.on_scan, 10)
        self.create_subscription(String, self.detection_topic, self.on_detection, 10)
        self.create_subscription(Float32, self.lane_offset_topic, self.on_lane_offset, 10)
        self.create_subscription(String, self.manual_cmd_topic, self.on_manual_command, 10)
        self.create_subscription(String, self.mode_topic, self.on_mode, 10)
        self.create_subscription(Bool, self.emergency_stop_topic, self.on_emergency_stop, 10)
        self.create_subscription(Float32, self.speed_scale_topic, self.on_speed_scale, 10)
        self.create_timer(1.0 / self.publish_rate_hz, self.control_loop)

        self.get_logger().info("Decision controller started")

    def _declare_parameters(self):
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("detection_topic", "/vision/detection")
        self.declare_parameter("lane_offset_topic", "/lane/offset")
        self.declare_parameter("manual_cmd_topic", "/manual_cmd")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("mode_topic", "/robot/mode")
        self.declare_parameter("emergency_stop_topic", "/robot/emergency_stop")
        self.declare_parameter("speed_scale_topic", "/robot/speed_scale")
        self.declare_parameter("front_angle_deg", 35.0)
        self.declare_parameter("front_center_deg", 180.0)
        self.declare_parameter("front_distance_percentile", 20.0)
        self.declare_parameter("obstacle_stop_distance", 0.45)
        self.declare_parameter("obstacle_slow_distance", 0.75)
        self.declare_parameter("cruise_speed", 0.18)
        self.declare_parameter("slow_speed", 0.08)
        self.declare_parameter("turn_speed", 0.75)
        self.declare_parameter("lane_kp", 0.9)
        self.declare_parameter("max_angular_speed", 1.2)
        self.declare_parameter("command_timeout_sec", 0.7)
        self.declare_parameter("detection_timeout_sec", 1.5)
        self.declare_parameter("lane_timeout_sec", 0.5)
        self.declare_parameter("scan_timeout_sec", 0.6)
        self.declare_parameter("publish_rate_hz", 20.0)

    def _load_parameters(self):
        self.scan_topic = self.get_parameter("scan_topic").value
        self.detection_topic = self.get_parameter("detection_topic").value
        self.lane_offset_topic = self.get_parameter("lane_offset_topic").value
        self.manual_cmd_topic = self.get_parameter("manual_cmd_topic").value
        self.cmd_vel_topic = self.get_parameter("cmd_vel_topic").value
        self.mode_topic = self.get_parameter("mode_topic").value
        self.emergency_stop_topic = self.get_parameter("emergency_stop_topic").value
        self.speed_scale_topic = self.get_parameter("speed_scale_topic").value
        self.front_angle = math.radians(float(self.get_parameter("front_angle_deg").value))
        self.front_center = math.radians(float(self.get_parameter("front_center_deg").value))
        self.front_distance_percentile = float(self.get_parameter("front_distance_percentile").value)
        self.obstacle_stop_distance = float(self.get_parameter("obstacle_stop_distance").value)
        self.obstacle_slow_distance = float(self.get_parameter("obstacle_slow_distance").value)
        self.cruise_speed = float(self.get_parameter("cruise_speed").value)
        self.slow_speed = float(self.get_parameter("slow_speed").value)
        self.turn_speed = float(self.get_parameter("turn_speed").value)
        self.lane_kp = float(self.get_parameter("lane_kp").value)
        self.max_angular_speed = float(self.get_parameter("max_angular_speed").value)
        self.command_timeout_sec = float(self.get_parameter("command_timeout_sec").value)
        self.detection_timeout_sec = float(self.get_parameter("detection_timeout_sec").value)
        self.lane_timeout_sec = float(self.get_parameter("lane_timeout_sec").value)
        self.scan_timeout_sec = float(self.get_parameter("scan_timeout_sec").value)
        self.publish_rate_hz = float(self.get_parameter("publish_rate_hz").value)

    def on_scan(self, scan):
        self.front_distance = front_range_statistic(
            scan,
            center_angle_rad=self.front_center,
            half_width_rad=self.front_angle,
            percentile=self.front_distance_percentile,
        )
        self.last_scan_time = time.monotonic()

    def on_detection(self, msg):
        self.detection = normalize_command(msg.data)
        self.last_detection_time = time.monotonic()

    def on_lane_offset(self, msg):
        self.lane_offset = float(msg.data)
        self.last_lane_time = time.monotonic()

    def on_manual_command(self, msg):
        self.manual_command = normalize_command(msg.data)
        self.last_manual_time = time.monotonic()

    def on_mode(self, msg):
        self.mode = normalize_mode(msg.data)

    def on_emergency_stop(self, msg):
        self.emergency_stop = bool(msg.data)

    def on_speed_scale(self, msg):
        self.speed_scale = max(0.0, min(1.0, float(msg.data)))

    def control_loop(self):
        now = time.monotonic()
        twist = Twist()
        motion = decide_motion(
            mode=self.mode,
            emergency_stop=self.emergency_stop,
            front_distance=self.front_distance,
            detection=self.detection,
            manual_command=self.manual_command,
            lane_offset=self.lane_offset,
            has_recent_detection=now - self.last_detection_time <= self.detection_timeout_sec,
            has_recent_manual=now - self.last_manual_time <= self.command_timeout_sec,
            has_recent_lane=now - self.last_lane_time <= self.lane_timeout_sec,
            has_recent_scan=now - self.last_scan_time <= self.scan_timeout_sec,
            obstacle_stop_distance=self.obstacle_stop_distance,
            obstacle_slow_distance=self.obstacle_slow_distance,
            cruise_speed=self.cruise_speed,
            slow_speed=self.slow_speed,
            turn_speed=self.turn_speed,
            lane_kp=self.lane_kp,
            max_angular_speed=self.max_angular_speed,
            speed_scale=self.speed_scale,
        )
        twist.linear.x = motion["linear_x"]
        twist.linear.y = motion["linear_y"]
        twist.angular.z = motion["angular_z"]
        self.publisher.publish(twist)

    def apply_detection_rule(self, twist):
        if self.detection in {"red_light", "shutdown", "stop"}:
            return True
        if self.detection in {"turn_right", "right"}:
            twist.angular.z = -self.turn_speed
            return True
        if self.detection in {"turn_left", "left"}:
            twist.angular.z = self.turn_speed
            return True
        if self.detection in {"go_straight", "green_light", "no_light"}:
            twist.linear.x = self.cruise_speed
            return True
        if self.detection in {"limiting_velocity", "school_decelerate", "slow"}:
            twist.linear.x = self.slow_speed
            return True
        return False

    def apply_manual_command(self, twist):
        command = self.manual_command
        speed = self.slow_speed if self.front_distance <= self.obstacle_slow_distance else self.cruise_speed

        if command == "stop":
            return True
        if command == "forward":
            twist.linear.x = speed
            return True
        if command == "backward":
            twist.linear.x = -speed
            return True
        if command == "left":
            twist.linear.y = speed
            return True
        if command == "right":
            twist.linear.y = -speed
            return True
        if command in {"turn_l", "turn_left"}:
            twist.angular.z = self.turn_speed
            return True
        if command in {"turn_r", "turn_right"}:
            twist.angular.z = -self.turn_speed
            return True
        return False


def main():
    rclpy.init()
    node = DecisionController()
    try:
        rclpy.spin(node)
    finally:
        node.publisher.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
