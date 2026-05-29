import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool

from .common import min_front_range


class LaserObstacleMonitor(Node):
    def __init__(self):
        super().__init__("laser_obstacle_monitor")
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("obstacle_topic", "/obstacle/front")
        self.declare_parameter("front_angle_deg", 35.0)
        self.declare_parameter("obstacle_distance", 0.45)
        self.declare_parameter("publish_rate_hz", 10.0)

        self.front_angle = math.radians(self.get_parameter("front_angle_deg").value)
        self.obstacle_distance = float(self.get_parameter("obstacle_distance").value)
        self.front_distance = float("inf")

        scan_topic = self.get_parameter("scan_topic").value
        obstacle_topic = self.get_parameter("obstacle_topic").value
        rate = float(self.get_parameter("publish_rate_hz").value)

        self.publisher = self.create_publisher(Bool, obstacle_topic, 10)
        self.create_subscription(LaserScan, scan_topic, self.on_scan, 10)
        self.create_timer(1.0 / rate, self.publish_state)

    def on_scan(self, scan):
        self.front_distance = min_front_range(scan, self.front_angle)

    def publish_state(self):
        msg = Bool()
        msg.data = self.front_distance <= self.obstacle_distance
        self.publisher.publish(msg)


def main():
    rclpy.init()
    node = LaserObstacleMonitor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
