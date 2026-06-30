import json
import time
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Float32, String

from .control_policy import normalize_mode
from .person_target import PersonTargetSelector
from .yolo_decision import (
    YoloCommandFilter,
    is_frame_obscured,
    normalize_candidate_command,
)


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
        self.offset_publisher = self.create_publisher(Float32, self.object_offset_topic, 10)
        self.tracking_status_publisher = self.create_publisher(
            String, self.tracking_target_topic, 10
        )
        self.annotated_frame_publisher = self.create_publisher(
            CompressedImage, self.annotated_frame_topic, 2
        )
        self.mode = "stop"
        self.create_subscription(String, self.mode_topic, self.on_mode, 10)
        self.create_subscription(
            String,
            self.tracking_target_set_topic,
            self.on_tracking_target_set,
            10,
        )

        self.camera = None
        self.command_filter = YoloCommandFilter(
            default_command=self.default_command,
            safety_hold_sec=self.safety_hold_sec,
        )
        self.person_selector = PersonTargetSelector(
            lost_timeout_sec=self.person_lock_timeout_sec,
            max_center_jump_ratio=self.person_max_center_jump_ratio,
        )

        self.last_publish_time = 0.0
        self.last_reopen_time = 0.0
        self.create_timer(1.0 / self.inference_rate_hz, self.process_frame)
        self.get_logger().info(
            f"YOLO camera node started: model={self.model_path}, source={self.camera_source}, idle until auto/object_follow mode"
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
        self.declare_parameter("tracking_confidence", 0.1)
        self.declare_parameter("tracker_config", "bytetrack.yaml")
        self.declare_parameter("inference_rate_hz", 10.0)
        self.declare_parameter("detection_topic", "/vision/detection")
        self.declare_parameter("object_offset_topic", "/vision/object_offset")
        self.declare_parameter("tracking_target_topic", "/vision/tracking_target")
        self.declare_parameter("tracking_target_set_topic", "/vision/tracking_target/set")
        self.declare_parameter("annotated_frame_topic", "/vision/annotated_frame")
        self.declare_parameter("annotated_jpeg_quality", 72)
        self.declare_parameter("camera_buffer_size", 1)
        self.declare_parameter("camera_reopen_interval_sec", 2.0)
        self.declare_parameter("mode_topic", "/robot/mode")
        self.declare_parameter("active_modes", ["auto", "object_follow"])
        self.declare_parameter("default_command", "no_light")
        self.declare_parameter("safety_hold_sec", 0.8)
        self.declare_parameter("min_frame_brightness", 20.0)
        self.declare_parameter("min_frame_contrast", 6.0)
        self.declare_parameter("publish_every_sec", 0.1)
        self.declare_parameter("person_lock_timeout_sec", 0.8)
        self.declare_parameter("person_max_center_jump_ratio", 0.3)
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
        self.tracking_confidence = float(self.get_parameter("tracking_confidence").value)
        self.tracker_config = self._resolve_config_path(
            str(self.get_parameter("tracker_config").value)
        )
        self.inference_rate_hz = float(self.get_parameter("inference_rate_hz").value)
        self.detection_topic = str(self.get_parameter("detection_topic").value)
        self.object_offset_topic = str(self.get_parameter("object_offset_topic").value)
        self.tracking_target_topic = str(self.get_parameter("tracking_target_topic").value)
        self.tracking_target_set_topic = str(
            self.get_parameter("tracking_target_set_topic").value
        )
        self.annotated_frame_topic = str(self.get_parameter("annotated_frame_topic").value)
        self.annotated_jpeg_quality = max(
            30,
            min(95, int(self.get_parameter("annotated_jpeg_quality").value)),
        )
        self.camera_buffer_size = max(1, int(self.get_parameter("camera_buffer_size").value))
        self.camera_reopen_interval_sec = max(
            0.5,
            float(self.get_parameter("camera_reopen_interval_sec").value),
        )
        self.mode_topic = str(self.get_parameter("mode_topic").value)
        self.active_modes = {
            normalize_mode(mode) for mode in self.get_parameter("active_modes").value
        }
        self.default_command = str(self.get_parameter("default_command").value)
        self.safety_hold_sec = float(self.get_parameter("safety_hold_sec").value)
        self.min_frame_brightness = float(self.get_parameter("min_frame_brightness").value)
        self.min_frame_contrast = float(self.get_parameter("min_frame_contrast").value)
        self.publish_every_sec = float(self.get_parameter("publish_every_sec").value)
        self.person_lock_timeout_sec = float(self.get_parameter("person_lock_timeout_sec").value)
        self.person_max_center_jump_ratio = float(self.get_parameter("person_max_center_jump_ratio").value)
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

    @staticmethod
    def _resolve_config_path(config_path):
        path = Path(config_path).expanduser()
        if path.is_absolute() or path.exists():
            return str(path)
        package_config = (
            Path(get_package_share_directory("smart_car_decision"))
            / "config"
            / config_path
        )
        return str(package_config) if package_config.exists() else config_path

    def on_mode(self, msg):
        next_mode = normalize_mode(msg.data)
        if self.mode == next_mode:
            return
        previous_mode = self.mode
        self.mode = next_mode
        tracking_reset = False
        if previous_mode == "object_follow" and self.mode != "object_follow":
            self.person_selector.reset()
            tracking_reset = True
        if self.mode != "object_follow":
            self._reset_tracker()
        if not self._is_active_mode():
            self._close_camera()
            self.person_selector.reset()
            tracking_reset = True
        if tracking_reset:
            self._publish_tracking_status(time.monotonic())

    def on_tracking_target_set(self, msg):
        try:
            payload = json.loads(msg.data)
            action = str(payload.get("action", "")).strip().lower()
            if action == "auto":
                self.person_selector.select_auto()
            elif action == "select":
                self.person_selector.select_point(payload["x"], payload["y"])
            else:
                raise ValueError("unknown tracking target action")
            self._publish_tracking_status(time.monotonic())
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            self.get_logger().warning(f"Ignored invalid tracking target request: {exc}")

    def _is_active_mode(self):
        return self.mode in self.active_modes

    def process_frame(self):
        if not self._is_active_mode():
            return
        if self.camera is None or not self.camera.isOpened():
            self._try_reopen_camera()
            return

        ok, frame = self.camera.read()
        if not ok:
            self.get_logger().warning(
                "Failed to read camera frame; will retry camera source",
                throttle_duration_sec=2.0,
            )
            self._close_camera()
            self._try_reopen_camera()
            return

        if self.mode == "object_follow":
            results = self.model.track(
                source=frame,
                imgsz=self.imgsz,
                conf=self.tracking_confidence,
                device=self.device,
                tracker=self.tracker_config,
                persist=True,
                verbose=False,
            )
            command, offset = self._choose_person_follow(frame, results[0])
        else:
            results = self.model.predict(
                source=frame,
                imgsz=self.imgsz,
                conf=self.confidence,
                device=self.device,
                verbose=False,
            )
            command, offset = self._choose_command(frame, results[0])
        command = self.command_filter.update(command, now=time.monotonic())
        tracking_status = self.person_selector.status(now=time.monotonic())
        self._publish_annotated_frame(results[0], tracking_status)
        if self.mode == "object_follow":
            self._publish_tracking_status(time.monotonic())
        self._publish_command(command)
        if offset is not None:
            msg = Float32()
            msg.data = float(offset)
            self.offset_publisher.publish(msg)

    def _choose_person_follow(self, frame, result):
        if is_frame_obscured(
            frame,
            min_brightness=self.min_frame_brightness,
            min_contrast=self.min_frame_contrast,
        ):
            return "stop", None

        boxes = getattr(result, "boxes", None)
        candidates = []
        if boxes is not None:
            for box in boxes:
                class_id = int(box.cls[0])
                class_name = result.names.get(class_id, str(class_id))
                candidates.append(
                    {
                        "class_name": class_name,
                        "confidence": float(box.conf[0]),
                        "xyxy": tuple(float(value) for value in box.xyxy[0].tolist()),
                        "track_id": None if box.id is None else int(box.id[0]),
                    }
                )
        selected = self.person_selector.update(
            candidates,
            frame_width=max(1, frame.shape[1]),
            frame_height=max(1, frame.shape[0]),
            now=time.monotonic(),
        )
        if selected is None:
            return self.default_command, None
        center_x = (selected["xyxy"][0] + selected["xyxy"][2]) / 2.0
        frame_width = max(1, frame.shape[1])
        offset = (center_x - frame_width / 2.0) / (frame_width / 2.0)
        return "slow", offset

    def _choose_command(self, frame, result):
        if is_frame_obscured(
            frame,
            min_brightness=self.min_frame_brightness,
            min_contrast=self.min_frame_contrast,
        ):
            return "stop", None

        boxes = getattr(result, "boxes", None)
        if boxes is None or len(boxes) == 0:
            return self.default_command, None

        best_command = self.default_command
        best_priority = -1
        best_offset = None
        names = result.names
        frame_width = max(1, frame.shape[1])
        for box in boxes:
            class_id = int(box.cls[0])
            class_name = names.get(class_id, str(class_id))
            if class_name == "traffic light":
                command = self._classify_traffic_light(frame, box)
            else:
                command = self.class_command_map.get(class_name, self.default_command)
            command = normalize_candidate_command(command, self.default_command)
            priority = self._command_priority(command)
            if priority > best_priority:
                best_command = command
                best_priority = priority
                best_offset = (
                    self._box_center_offset(box, frame_width)
                    if command != self.default_command
                    else None
                )
        return best_command, best_offset

    @staticmethod
    def _box_center_offset(box, frame_width):
        x1, _, x2, _ = [float(v) for v in box.xyxy[0].tolist()]
        center_x = (x1 + x2) / 2.0
        return (center_x - frame_width / 2.0) / (frame_width / 2.0)

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

    def _open_camera(self):
        self.camera = self.cv2.VideoCapture(self._parse_camera_source(self.camera_source))
        if self.camera_width > 0:
            self.camera.set(self.cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
        if self.camera_height > 0:
            self.camera.set(self.cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
        if self.camera_fps > 0:
            self.camera.set(self.cv2.CAP_PROP_FPS, self.camera_fps)
        self.camera.set(self.cv2.CAP_PROP_BUFFERSIZE, self.camera_buffer_size)
        if not self.camera.isOpened():
            self.get_logger().warning(
                f"Could not open YOLO camera source: {self.camera_source}; will retry while mode is active",
                throttle_duration_sec=5.0,
            )
            self._close_camera()
            return False
        self.get_logger().info(f"Opened YOLO camera source: {self.camera_source}")
        return True

    def _try_reopen_camera(self):
        now = time.monotonic()
        if now - self.last_reopen_time < self.camera_reopen_interval_sec:
            return
        self.last_reopen_time = now
        if self._open_camera():
            self.get_logger().info(f"Reopened camera source: {self.camera_source}")

    def _close_camera(self):
        if self.camera is not None:
            self.camera.release()
            self.camera = None

    def _reset_tracker(self):
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", ()):
            tracker.reset()

    def _publish_command(self, command):
        now = time.monotonic()
        if now - self.last_publish_time < self.publish_every_sec:
            return
        msg = String()
        msg.data = command
        self.publisher.publish(msg)
        self.last_publish_time = now

    def _publish_tracking_status(self, now):
        msg = String()
        msg.data = json.dumps(self.person_selector.status(now=now), ensure_ascii=False)
        self.tracking_status_publisher.publish(msg)

    def _publish_annotated_frame(self, result, tracking_status=None):
        annotated = result.plot()
        if tracking_status and tracking_status.get("locked") and self.person_selector.locked_box:
            x1, y1, x2, y2 = (int(value) for value in self.person_selector.locked_box)
            self.cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 255, 255), 4)
            self.cv2.putText(
                annotated,
                f"LOCKED ID {tracking_status.get('track_id')}",
                (x1, max(28, y1 - 10)),
                self.cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 255, 255),
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
        self.annotated_frame_publisher.publish(msg)

    def destroy_node(self):
        self._close_camera()
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
