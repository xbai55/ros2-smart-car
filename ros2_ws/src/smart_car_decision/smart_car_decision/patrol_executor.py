import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class PatrolExecutor(Node):
    """巡检任务执行器，位于 decision_controller 上游。

    只发布 /robot/mode/set 与任务进度，禁止直接发布 /cmd_vel。
    """

    def __init__(self):
        super().__init__("patrol_executor")
        self.declare_parameter("task_topic", "/patrol_task/set")
        self.declare_parameter("mode_set_topic", "/robot/mode/set")
        self.declare_parameter("progress_topic", "/patrol_task/progress")

        self.mode_pub = self.create_publisher(String, self.get_parameter("mode_set_topic").value, 10)
        self.progress_pub = self.create_publisher(String, self.get_parameter("progress_topic").value, 10)
        self.create_subscription(String, self.get_parameter("task_topic").value, self.on_task, 10)
        self.get_logger().info("Patrol executor started")

    def on_task(self, msg):
        try:
            task = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("忽略无效巡检任务 JSON")
            return
        if task.get("action") in ("start", "resume"):
            self.publish_mode("patrol")
        elif task.get("action") == "pause":
            self.publish_mode("stop")
        elif task.get("action") == "cancel":
            self.publish_mode("stop")
        self.publish_progress(task.get("progress", 0.0))

    def publish_mode(self, mode):
        out = String()
        out.data = mode
        self.mode_pub.publish(out)

    def publish_progress(self, progress):
        out = String()
        out.data = json.dumps({"progress": progress})
        self.progress_pub.publish(out)


def main():
    rclpy.init()
    node = PatrolExecutor()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
