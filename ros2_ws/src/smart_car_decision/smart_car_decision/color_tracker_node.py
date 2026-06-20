import json
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Float32, String

from .color_config import normalize_color_config
from .control_policy import normalize_mode


class ColorTrackerNode(Node):
    def __init__(self):
        super().__init__("color_tracker_node")
        self._declare_parameters()
        self._load_parameters()

        try:
            import cv2
        except ImportError as exc:
            raise RuntimeError("color_tracker_node requires opencv-python on the Jetson") from exc

        self.cv2 = cv2
        self.mode = "stop"
        self.camera = None
        self.target_pub = self.create_publisher(String, self.color_target_topic, 10)
        self.offset_pub = self.create_publisher(Float32, self.lane_offset_topic, 10)
        self.annotated_pub = self.create_publisher(CompressedImage, self.annotated_frame_topic, 2)
        self.create_subscription(String, self.mode_topic, self.on_mode, 10)
        self.create_subscription(String, self.color_config_topic, self.on_color_config, 10)
        self.create_timer(1.0 / self.process_rate_hz, self.process_frame)

    def _declare_parameters(self):
        self.declare_parameter("camera_source", "0")
        self.declare_parameter("mode_topic", "/robot/mode")
        self.declare_parameter("color_target_topic", "/vision/color_target")
        self.declare_parameter("color_config_topic", "/vision/color_config")
        self.declare_parameter("lane_offset_topic", "/lane/offset")
        self.declare_parameter("annotated_frame_topic", "/vision/annotated_frame")
        self.declare_parameter("annotated_jpeg_quality", 72)
        self.declare_parameter("camera_buffer_size", 1)
        self.declare_parameter("process_rate_hz", 10.0)
        self.declare_parameter("min_area", 500.0)
        self.declare_parameter("hsv_low", [35, 60, 60])
        self.declare_parameter("hsv_high", [90, 255, 255])

    def _load_parameters(self):
        self.camera_source = str(self.get_parameter("camera_source").value)
        self.mode_topic = str(self.get_parameter("mode_topic").value)
        self.color_target_topic = str(self.get_parameter("color_target_topic").value)
        self.color_config_topic = str(self.get_parameter("color_config_topic").value)
        self.lane_offset_topic = str(self.get_parameter("lane_offset_topic").value)
        self.annotated_frame_topic = str(self.get_parameter("annotated_frame_topic").value)
        self.annotated_jpeg_quality = max(
            30,
            min(95, int(self.get_parameter("annotated_jpeg_quality").value)),
        )
        self.camera_buffer_size = max(1, int(self.get_parameter("camera_buffer_size").value))
        self.process_rate_hz = float(self.get_parameter("process_rate_hz").value)
        self.min_area = float(self.get_parameter("min_area").value)
        self.hsv_low = tuple(int(v) for v in self.get_parameter("hsv_low").value)
        self.hsv_high = tuple(int(v) for v in self.get_parameter("hsv_high").value)

    @staticmethod
    def _parse_camera_source(source):
        try:
            return int(source)
        except ValueError:
            return source

    def on_mode(self, msg):
        next_mode = normalize_mode(msg.data)
        if self.mode == next_mode:
            return
        self.mode = next_mode
        if self.mode != "color_track":
            self._close_camera()

    def on_color_config(self, msg):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning("Ignored invalid color config payload")
            return
        config = normalize_color_config(payload)
        self.hsv_low = tuple(config["hsv_low"])
        self.hsv_high = tuple(config["hsv_high"])
        self.get_logger().info(
            f"Color tracking target updated: {config['name']} low={self.hsv_low} high={self.hsv_high}"
        )

    def process_frame(self):
        if self.mode != "color_track":
            return
        if not self._open_camera():
            self.publish_target(False, 0.0, 0.0)
            return
        ok, frame = self.camera.read()
        if not ok:
            self._close_camera()
            self.publish_target(False, 0.0, 0.0)
            return

        hsv = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2HSV)
        mask = self.cv2.inRange(hsv, self.hsv_low, self.hsv_high)
        moments = self.cv2.moments(mask)
        area = float(moments["m00"])
        if area < self.min_area:
            self.publish_annotated_frame(frame, None, area)
            self.publish_target(False, 0.0, area)
            return

        cx = moments["m10"] / area
        cy = moments["m01"] / area
        width = max(1, frame.shape[1])
        offset = (cx - width / 2.0) / (width / 2.0)
        self.publish_annotated_frame(frame, (cx, cy), area)
        self.publish_target(True, offset, area)
        offset_msg = Float32()
        offset_msg.data = float(offset)
        self.offset_pub.publish(offset_msg)

    def publish_target(self, found, offset, area):
        msg = String()
        msg.data = json.dumps(
            {
                "found": bool(found),
                "offset": round(float(offset), 4),
                "area": round(float(area), 2),
                "hsv_low": list(self.hsv_low),
                "hsv_high": list(self.hsv_high),
                "timestamp": time.time(),
            },
            ensure_ascii=False,
        )
        self.target_pub.publish(msg)

    def publish_annotated_frame(self, frame, center, area):
        annotated = frame.copy()
        if center is not None:
            cx, cy = (int(center[0]), int(center[1]))
            self.cv2.circle(annotated, (cx, cy), 18, (0, 255, 255), 3)
            self.cv2.line(annotated, (frame.shape[1] // 2, 0), (frame.shape[1] // 2, frame.shape[0]), (255, 180, 0), 2)
            self.cv2.putText(
                annotated,
                f"color target area={int(area)}",
                (16, 34),
                self.cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
                2,
            )
        else:
            self.cv2.putText(
                annotated,
                "color target lost",
                (16, 34),
                self.cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 180, 255),
                2,
            )
        ok, encoded = self.cv2.imencode(
            ".jpg",
            annotated,
            [int(self.cv2.IMWRITE_JPEG_QUALITY), self.annotated_jpeg_quality],
        )
        if not ok:
            return
        msg = CompressedImage()
        msg.format = "jpeg"
        msg.data = encoded.tobytes()
        self.annotated_pub.publish(msg)

    def _open_camera(self):
        if self.camera is not None and self.camera.isOpened():
            return True
        self.camera = self.cv2.VideoCapture(self._parse_camera_source(self.camera_source))
        self.camera.set(self.cv2.CAP_PROP_BUFFERSIZE, self.camera_buffer_size)
        if not self.camera.isOpened():
            self.get_logger().warning(
                f"Could not open color tracking camera source: {self.camera_source}",
                throttle_duration_sec=2.0,
            )
            self._close_camera()
            return False
        self.get_logger().info(f"Color tracking camera opened: {self.camera_source}")
        return True

    def _close_camera(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    def destroy_node(self):
        self._close_camera()
        return super().destroy_node()


def main():
    rclpy.init()
    node = ColorTrackerNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
