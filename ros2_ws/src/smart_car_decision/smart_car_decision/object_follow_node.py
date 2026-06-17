import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32, String

from .control_policy import normalize_mode


class ObjectFollowNode(Node):
    def __init__(self):
        super().__init__("object_follow_node")
        self.declare_parameter("mode_topic", "/robot/mode")
        self.declare_parameter("object_offset_topic", "/vision/object_offset")
        self.declare_parameter("lane_offset_topic", "/lane/offset")
        self.declare_parameter("offset_timeout_sec", 0.7)
        self.declare_parameter("publish_rate_hz", 10.0)

        self.mode = "stop"
        self.object_offset = 0.0
        self.last_offset_time = 0.0
        self.publisher = self.create_publisher(Float32, self.get_parameter("lane_offset_topic").value, 10)
        self.create_subscription(String, self.get_parameter("mode_topic").value, self.on_mode, 10)
        self.create_subscription(Float32, self.get_parameter("object_offset_topic").value, self.on_offset, 10)
        self.create_timer(1.0 / float(self.get_parameter("publish_rate_hz").value), self.publish_offset)

    def on_mode(self, msg):
        self.mode = normalize_mode(msg.data)

    def on_offset(self, msg):
        self.object_offset = float(msg.data)
        self.last_offset_time = time.monotonic()

    def publish_offset(self):
        if self.mode != "object_follow":
            return
        if time.monotonic() - self.last_offset_time > float(self.get_parameter("offset_timeout_sec").value):
            return
        msg = Float32()
        msg.data = self.object_offset
        self.publisher.publish(msg)


def main():
    rclpy.init()
    node = ObjectFollowNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
