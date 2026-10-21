import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class MissionExecutor(Node):
    """运输任务执行器，位于 decision_controller 上游。

    只发布 /robot/mode/set 与任务状态，禁止直接发布 /cmd_vel。
    """

    def __init__(self):
        super().__init__("mission_executor")
        self.declare_parameter("task_topic", "/mission_task/set")
        self.declare_parameter("mode_set_topic", "/robot/mode/set")
        self.declare_parameter("state_topic", "/mission_task/state")

        self.mode_pub = self.create_publisher(String, self.get_parameter("mode_set_topic").value, 10)
        self.state_pub = self.create_publisher(String, self.get_parameter("state_topic").value, 10)
        self.create_subscription(String, self.get_parameter("task_topic").value, self.on_task, 10)
        self.get_logger().info("Mission executor started")

    def on_task(self, msg):
        try:
            task = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("忽略无效运输任务 JSON")
            return
        action = task.get("action")
        if action in ("dispatch", "transporting"):
            self.publish_mode("transport")
        elif action in ("pickup", "handover", "complete", "cancel"):
            self.publish_mode("stop")
        self.publish_state({"action": action, "status": task.get("status", "queued")})

    def publish_mode(self, mode):
        out = String()
        out.data = mode
        self.mode_pub.publish(out)

    def publish_state(self, state):
        out = String()
        out.data = json.dumps(state)
        self.state_pub.publish(out)


def main():
    rclpy.init()
    node = MissionExecutor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
