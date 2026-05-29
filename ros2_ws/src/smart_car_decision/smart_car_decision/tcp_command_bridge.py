import socket
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .common import normalize_command


class TcpCommandBridge(Node):
    def __init__(self):
        super().__init__("tcp_command_bridge")
        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 9999)
        self.declare_parameter("manual_cmd_topic", "/manual_cmd")

        self.host = self.get_parameter("host").value
        self.port = int(self.get_parameter("port").value)
        topic = self.get_parameter("manual_cmd_topic").value
        self.publisher = self.create_publisher(String, topic, 10)

        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self.get_logger().info(f"TCP command bridge listening on {self.host}:{self.port}")

    def destroy_node(self):
        self._stop.set()
        return super().destroy_node()

    def _serve(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen(1)
            server.settimeout(0.5)
            while not self._stop.is_set():
                try:
                    client, address = server.accept()
                except socket.timeout:
                    continue
                with client:
                    self.get_logger().info(f"TCP client connected: {address}")
                    client.settimeout(0.5)
                    buffer = ""
                    while not self._stop.is_set():
                        try:
                            data = client.recv(1024)
                        except socket.timeout:
                            continue
                        except OSError:
                            break
                        if not data:
                            break
                        buffer += data.decode("utf-8", errors="ignore")
                        parts = buffer.replace("\r", "\n").split("\n")
                        buffer = parts[-1]
                        for part in parts[:-1]:
                            self.publish_command(part)
                        if "\n" not in buffer and len(buffer) < 32:
                            self.publish_command(buffer)
                            buffer = ""
                    self.publish_command("stop")
                    self.get_logger().info("TCP client disconnected, published stop")

    def publish_command(self, raw):
        command = normalize_command(raw)
        if not command:
            return
        msg = String()
        msg.data = command
        self.publisher.publish(msg)


def main():
    rclpy.init()
    node = TcpCommandBridge()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
