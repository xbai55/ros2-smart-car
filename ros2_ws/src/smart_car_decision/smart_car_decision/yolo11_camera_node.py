import json
import time
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class Yolo11CameraNode(Node):
    def __init__(self):
        super().__init__("yolo11_camera_node")
        self._declare_parameters()
        self._load_parameters()

        try:
            import cv2
            from ultralytics import YOLO
        except ImportError as exc:
            raise RuntimeError(
                "yolo11_camera_node requires opencv-python and ultralytics. "
                "Install them on the Jetson, for example: "
                "pip install ultralytics opencv-python"
            ) from exc

        self.cv2 = cv2
        self.model_path = self._resolve_model_path(self.model_path)
        self.model = YOLO(self.model_path)
        self.publisher = self.create_publisher(String, self.detection_topic, 10)

        self.camera = cv2.VideoCapture(self._parse_camera_source(self.camera_source))
        if self.camera_width > 0:
            self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
        if self.camera_height > 0:
            self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
        if self.camera_fps > 0:
            self.camera.set(cv2.CAP_PROP_FPS, self.camera_fps)
        if not self.camera.isOpened():
            raise RuntimeError(f"Could not open camera source: {self.camera_source}")

        self.last_publish_time = 0.0
        self.create_timer(1.0 / self.inference_rate_hz, self.process_frame)
        self.get_logger().info(
            f"YOLO camera node started: model={self.model_path}, source={self.camera_source}"
        )

    def _declare_parameters(self):
        self.declare_parameter("camera_source", "0")
        self.declare_parameter("camera_width", 640)
        self.declare_parameter("camera_height", 480)
        self.declare_parameter("camera_fps", 30.0)
        self.declare_parameter("model_path", "yolo11s.pt")
        self.declare_parameter("device", "0")
        self.declare_parameter("imgsz", 640)
        self.declare_parameter("confidence", 0.35)
        self.declare_parameter("inference_rate_hz", 10.0)
        self.declare_parameter("detection_topic", "/vision/detection")
        self.declare_parameter("default_command", "no_light")
        self.declare_parameter("publish_every_sec", 0.1)
        self.declare_parameter("red_ratio_threshold", 0.08)
        self.declare_parameter("green_ratio_threshold", 0.08)
        self.declare_parameter(
            "class_command_map",
            json.dumps(
                {
                    "stop sign": "stop",
                    "person": "slow",
                    "car": "slow",
                    "truck": "slow",
                    "bus": "slow",
                    "motorcycle": "slow",
                    "bicycle": "slow",
                }
            ),
        )

    def _load_parameters(self):
        self.camera_source = str(self.get_parameter("camera_source").value)
        self.camera_width = int(self.get_parameter("camera_width").value)
        self.camera_height = int(self.get_parameter("camera_height").value)
        self.camera_fps = float(self.get_parameter("camera_fps").value)
        self.model_path = str(self.get_parameter("model_path").value)
        self.device = str(self.get_parameter("device").value)
        self.imgsz = int(self.get_parameter("imgsz").value)
        self.confidence = float(self.get_parameter("confidence").value)
        self.inference_rate_hz = float(self.get_parameter("inference_rate_hz").value)
        self.detection_topic = str(self.get_parameter("detection_topic").value)
        self.default_command = str(self.get_parameter("default_command").value)
        self.publish_every_sec = float(self.get_parameter("publish_every_sec").value)
        self.red_ratio_threshold = float(self.get_parameter("red_ratio_threshold").value)
        self.green_ratio_threshold = float(self.get_parameter("green_ratio_threshold").value)
        self.class_command_map = json.loads(
            str(self.get_parameter("class_command_map").value)
        )

    @staticmethod
    def _parse_camera_source(source):
        try:
            return int(source)
        except ValueError:
            return source

    @staticmethod
    def _resolve_model_path(model_path):
        path = Path(model_path).expanduser()
        if path.is_absolute() or path.exists():
            return str(path)

        package_model = (
            Path(get_package_share_directory("smart_car_decision"))
            / "models"
            / model_path
        )
        if package_model.exists():
            return str(package_model)
        return model_path

    def process_frame(self):
        ok, frame = self.camera.read()
        if not ok:
            self.get_logger().warning("Failed to read camera frame")
            return

        results = self.model.predict(
            source=frame,
            imgsz=self.imgsz,
            conf=self.confidence,
            device=self.device,
            verbose=False,
        )
        command = self._choose_command(frame, results[0])
        self._publish_command(command)

    def _choose_command(self, frame, result):
        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return self.default_command

        best_command = self.default_command
        best_priority = -1
        names = result.names
        for box in boxes:
            class_id = int(box.cls[0])
            class_name = names.get(class_id, str(class_id))
            if class_name == "traffic light":
                command = self._classify_traffic_light(frame, box)
            else:
                command = self.class_command_map.get(class_name, self.default_command)
            priority = self._command_priority(command)
            if priority > best_priority:
                best_command = command
                best_priority = priority
        return best_command

    def _classify_traffic_light(self, frame, box):
        x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
        h, w = frame.shape[:2]
        x1, x2 = max(0, x1), min(w, x2)
        y1, y2 = max(0, y1), min(h, y2)
        if x2 <= x1 or y2 <= y1:
            return self.default_command

        crop = frame[y1:y2, x1:x2]
        hsv = self.cv2.cvtColor(crop, self.cv2.COLOR_BGR2HSV)
        red_a = self.cv2.inRange(hsv, (0, 80, 80), (10, 255, 255))
        red_b = self.cv2.inRange(hsv, (170, 80, 80), (180, 255, 255))
        green = self.cv2.inRange(hsv, (35, 60, 60), (90, 255, 255))
        pixels = max(1, crop.shape[0] * crop.shape[1])
        red_ratio = (
            self.cv2.countNonZero(red_a) + self.cv2.countNonZero(red_b)
        ) / pixels
        green_ratio = self.cv2.countNonZero(green) / pixels

        if red_ratio >= self.red_ratio_threshold and red_ratio >= green_ratio:
            return "red_light"
        if green_ratio >= self.green_ratio_threshold:
            return "green_light"
        return "no_light"

    @staticmethod
    def _command_priority(command):
        priorities = {
            "stop": 100,
            "red_light": 90,
            "slow": 50,
            "green_light": 20,
            "no_light": 10,
        }
        return priorities.get(command, 0)

    def _publish_command(self, command):
        now = time.monotonic()
        if now - self.last_publish_time < self.publish_every_sec:
            return
        msg = String()
        msg.data = command
        self.publisher.publish(msg)
        self.last_publish_time = now

    def destroy_node(self):
        if hasattr(self, "camera"):
            self.camera.release()
        return super().destroy_node()


def main():
    rclpy.init()
    node = Yolo11CameraNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
