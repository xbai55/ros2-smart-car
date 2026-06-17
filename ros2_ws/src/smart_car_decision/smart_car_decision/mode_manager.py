import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String

from .control_policy import normalize_mode


class ModeManager(Node):
    def __init__(self):
        super().__init__("mode_manager")
        self.declare_parameter("initial_mode", "stop")
        self.declare_parameter("mode_topic", "/robot/mode")
        self.declare_parameter("mode_set_topic", "/robot/mode/set")
        self.declare_parameter("emergency_stop_topic", "/robot/emergency_stop")
        self.declare_parameter("emergency_stop_set_topic", "/robot/emergency_stop/set")
        self.declare_parameter("publish_rate_hz", 5.0)

        self.mode = normalize_mode(self.get_parameter("initial_mode").value)
        self.emergency_stop = False

        self.mode_pub = self.create_publisher(String, self.get_parameter("mode_topic").value, 10)
        self.estop_pub = self.create_publisher(Bool, self.get_parameter("emergency_stop_topic").value, 10)
        self.create_subscription(String, self.get_parameter("mode_set_topic").value, self.on_mode_set, 10)
        self.create_subscription(
            Bool,
            self.get_parameter("emergency_stop_set_topic").value,
            self.on_emergency_stop_set,
            10,
        )
        rate = float(self.get_parameter("publish_rate_hz").value)
        self.create_timer(1.0 / rate, self.publish_state)
        self.get_logger().info("Mode manager started in stop mode")

    def on_mode_set(self, msg):
        mode = normalize_mode(msg.data)
        self.mode = mode
        if mode != "stop":
            self.emergency_stop = False
        self.publish_state()

    def on_emergency_stop_set(self, msg):
        self.emergency_stop = bool(msg.data)
        if self.emergency_stop:
            self.mode = "stop"
        self.publish_state()

    def publish_state(self):
        mode_msg = String()
        mode_msg.data = self.mode
        self.mode_pub.publish(mode_msg)

        stop_msg = Bool()
        stop_msg.data = self.emergency_stop
        self.estop_pub.publish(stop_msg)


def main():
    rclpy.init()
    node = ModeManager()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
