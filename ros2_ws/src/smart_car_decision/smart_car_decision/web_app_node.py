import asyncio
import json
import threading
import time
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
import rclpy
from nav_msgs.msg import OccupancyGrid
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import Bool, Float32, String

from .web_camera import CameraStream
from .web_static import resolve_static_dir
from .web_video import AnnotatedFrameStore, should_release_camera_for_mode
from .web_state import RobotStateStore, normalize_tracking_target_request


class WebAppNode(Node):
    def __init__(self):
        super().__init__("web_app_node")
        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 8080)
        self.declare_parameter("status_topic", "/robot/status")
        self.declare_parameter("mode_set_topic", "/robot/mode/set")
        self.declare_parameter("manual_cmd_topic", "/manual_cmd")
        self.declare_parameter("emergency_stop_set_topic", "/robot/emergency_stop/set")
        self.declare_parameter("speed_scale_topic", "/robot/speed_scale")
        self.declare_parameter("color_config_topic", "/vision/color_config")
        self.declare_parameter("tracking_target_set_topic", "/vision/tracking_target/set")
        self.declare_parameter("annotated_frame_topic", "/vision/annotated_frame")
        self.declare_parameter("camera_source", "0")
        self.declare_parameter("video_fps", 30.0)
        self.declare_parameter("video_target_fps", 20.0)
        self.declare_parameter("annotated_stream_fps", 20.0)
        self.declare_parameter("static_dir", "")

        self.store = RobotStateStore()
        self.annotated_frames = AnnotatedFrameStore(max_age_sec=1.5)
        self.map_snapshot = MapSnapshotStore()
        self.camera_stream = None
        self.mode_pub = self.create_publisher(String, self.get_parameter("mode_set_topic").value, 10)
        self.cmd_pub = self.create_publisher(String, self.get_parameter("manual_cmd_topic").value, 10)
        self.estop_pub = self.create_publisher(Bool, self.get_parameter("emergency_stop_set_topic").value, 10)
        self.speed_pub = self.create_publisher(Float32, self.get_parameter("speed_scale_topic").value, 10)
        self.color_config_pub = self.create_publisher(String, self.get_parameter("color_config_topic").value, 10)
        self.tracking_target_pub = self.create_publisher(String, self.get_parameter("tracking_target_set_topic").value, 10)
        self.create_subscription(String, self.get_parameter("status_topic").value, self.on_status, 10)
        self.create_subscription(OccupancyGrid, "/map", self.on_map, 1)
        self.create_subscription(
            CompressedImage,
            self.get_parameter("annotated_frame_topic").value,
            self.on_annotated_frame,
            2,
        )

        self._server_thread = threading.Thread(target=self._run_server, daemon=True)
        self._server_thread.start()
        self.get_logger().info(
            f"Web/PWA control server starting on {self.get_parameter('host').value}:{self.get_parameter('port').value}"
        )

    def on_status(self, msg):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        self.store.update(**data)

    def on_annotated_frame(self, msg):
        self.annotated_frames.update(bytes(msg.data))

    def on_map(self, msg):
        self.map_snapshot.update(msg)

    def set_mode(self, mode):
        mode = self.store.set_mode(mode)
        if should_release_camera_for_mode(mode) and self.camera_stream is not None:
            self.camera_stream.close()
        msg = String()
        msg.data = mode
        self.mode_pub.publish(msg)
        return mode

    def set_command(self, command):
        command = self.store.set_command(command)
        msg = String()
        msg.data = command
        self.cmd_pub.publish(msg)
        return command

    def set_emergency_stop(self, enabled):
        state = self.store.set_emergency_stop(enabled)
        msg = Bool()
        msg.data = state
        self.estop_pub.publish(msg)
        if state:
            stop = String()
            stop.data = "stop"
            self.cmd_pub.publish(stop)
        return state

    def set_speed_scale(self, value):
        scale = self.store.set_speed_scale(value)
        msg = Float32()
        msg.data = float(scale)
        self.speed_pub.publish(msg)
        return scale

    def set_color_config(self, payload):
        config = self.store.set_color_config(payload)
        msg = String()
        msg.data = json.dumps(config, ensure_ascii=False)
        self.color_config_pub.publish(msg)
        return config

    def set_tracking_target(self, payload):
        request = normalize_tracking_target_request(payload)
        msg = String()
        msg.data = json.dumps(request, ensure_ascii=False)
        self.tracking_target_pub.publish(msg)
        return request

    def _run_server(self):
        try:
            import cv2
            import uvicorn
            from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
            from fastapi.responses import FileResponse, StreamingResponse
            from fastapi.staticfiles import StaticFiles
            from pydantic import BaseModel
        except ImportError as exc:
            self.get_logger().error(f"Web server dependencies missing: {exc}")
            return

        node = self
        camera = CameraStream(
            str(self.get_parameter("camera_source").value),
            cv2,
            lambda: node.store.snapshot().get("mode", "stop"),
            capture_fps=float(self.get_parameter("video_fps").value),
            target_fps=float(self.get_parameter("video_target_fps").value),
        )
        node.camera_stream = camera
        annotated_stream = AnnotatedFrameStream(
            node.annotated_frames,
            target_fps=float(self.get_parameter("annotated_stream_fps").value),
        )

        class ModePayload(BaseModel):
            mode: str

        class CommandPayload(BaseModel):
            command: str

        class EmergencyPayload(BaseModel):
            enabled: bool

        class SpeedPayload(BaseModel):
            scale: float

        class ColorConfigPayload(BaseModel):
            name: str = "custom"
            hsv_low: list[int]
            hsv_high: list[int]

        class TrackingTargetPayload(BaseModel):
            action: str
            x: float | None = None
            y: float | None = None

        app = FastAPI(title="ROS2 Smart Car Control")
        package_static_dir = Path(get_package_share_directory("smart_car_decision")) / "web" / "static"
        static_dir = resolve_static_dir(self.get_parameter("static_dir").value, package_static_dir)
        app.mount("/app", StaticFiles(directory=str(static_dir), html=True), name="app")
        assets_dir = static_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

        @app.get("/")
        def root():
            return FileResponse(static_dir / "index.html")

        @app.get("/api/status")
        def status():
            return node.store.snapshot()

        @app.get("/api/map")
        def map_snapshot():
            snapshot = node.map_snapshot.snapshot()
            if snapshot is None:
                raise HTTPException(status_code=404, detail="map is not available")
            return snapshot

        @app.post("/api/mode")
        def mode(payload: ModePayload):
            return {"mode": node.set_mode(payload.mode)}

        @app.post("/api/command")
        def command(payload: CommandPayload):
            result = node.set_command(payload.command)
            if result == "stop" and node.store.snapshot()["mode"] not in {"manual", "mapping"}:
                raise HTTPException(status_code=409, detail="manual commands require manual or mapping mode")
            return {"command": result}

        @app.post("/api/emergency-stop")
        def emergency_stop(payload: EmergencyPayload):
            return {"emergency_stop": node.set_emergency_stop(payload.enabled)}

        @app.post("/api/speed")
        def speed(payload: SpeedPayload):
            return {"speed_scale": node.set_speed_scale(payload.scale)}

        @app.post("/api/color-target")
        def color_target(payload: ColorConfigPayload):
            return {"color_config": node.set_color_config(payload.dict())}

        @app.post("/api/tracking-target")
        def tracking_target(payload: TrackingTargetPayload):
            try:
                request = node.set_tracking_target(payload.dict(exclude_none=True))
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            return {"tracking_target": request}

        @app.get("/video_feed")
        def video_feed():
            if camera.is_blocked_by_mode():
                camera.close()
                return StreamingResponse(
                    annotated_stream.frames(),
                    media_type="multipart/x-mixed-replace; boundary=frame",
                )
            if not camera.open():
                raise HTTPException(status_code=503, detail="camera is not available")
            return StreamingResponse(
                camera.frames(),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )

        @app.websocket("/ws/status")
        async def websocket_status(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    await websocket.send_json(node.store.snapshot())
                    await asyncio.sleep(0.5)
            except WebSocketDisconnect:
                return

        @app.websocket("/ws/control")
        async def websocket_control(websocket: WebSocket):
            await websocket.accept()
            try:
                while True:
                    payload = await websocket.receive_json()
                    command = str(payload.get("command", "stop"))
                    result = node.set_command(command)
                    await websocket.send_json({"command": result})
            except WebSocketDisconnect:
                node.set_command("stop")

        config = uvicorn.Config(
            app,
            host=str(self.get_parameter("host").value),
            port=int(self.get_parameter("port").value),
            log_level="info",
        )
        uvicorn.Server(config).run()


class AnnotatedFrameStream:
    def __init__(self, store, target_fps=20.0):
        self.store = store
        self.target_fps = max(1.0, float(target_fps))

    def latest_frame(self):
        return self.store.latest()

    def frames(self):
        last_version = 0
        timeout = 1.0 / self.target_fps
        while True:
            frame, last_version = self.store.wait_for_frame(
                last_version=last_version,
                timeout=timeout,
            )
            if frame is not None:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n"
                    + frame
                    + b"\r\n"
                )


class MapSnapshotStore:
    def __init__(self):
        self._lock = threading.Lock()
        self._snapshot = None

    def update(self, msg):
        data = list(msg.data)
        with self._lock:
            self._snapshot = {
                "header": {
                    "frame_id": str(msg.header.frame_id),
                    "stamp": {
                        "sec": int(msg.header.stamp.sec),
                        "nanosec": int(msg.header.stamp.nanosec),
                    },
                },
                "info": {
                    "width": int(msg.info.width),
                    "height": int(msg.info.height),
                    "resolution": float(msg.info.resolution),
                    "origin": {
                        "x": float(msg.info.origin.position.x),
                        "y": float(msg.info.origin.position.y),
                        "yaw": _yaw_from_quaternion(msg.info.origin.orientation),
                    },
                },
                "data": data,
                "updated_at": time.time(),
            }

    def snapshot(self):
        with self._lock:
            return None if self._snapshot is None else dict(self._snapshot)


def _yaw_from_quaternion(quaternion):
    siny_cosp = 2.0 * (quaternion.w * quaternion.z + quaternion.x * quaternion.y)
    cosy_cosp = 1.0 - 2.0 * (quaternion.y * quaternion.y + quaternion.z * quaternion.z)
    import math

    return math.atan2(siny_cosp, cosy_cosp)


def main():
    rclpy.init()
    node = WebAppNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
