import copy
import time

from .control_policy import normalize_manual_command, normalize_mode
from .color_config import DEFAULT_COLOR_CONFIG, normalize_color_config

MIN_SPEED_SCALE = 0.15


def normalize_tracking_target_request(payload):
    action = str(payload.get("action", "")).strip().lower()
    if action == "auto":
        return {"action": "auto"}
    if action != "select":
        raise ValueError("tracking target action must be 'auto' or 'select'")
    x = float(payload.get("x"))
    y = float(payload.get("y"))
    if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
        raise ValueError("tracking target coordinates must be normalized to [0, 1]")
    return {"action": "select", "x": x, "y": y}


class RobotStateStore:
    def __init__(self):
        self._state = {
            "mode": "stop",
            "emergency_stop": False,
            "front_distance": None,
            "lidar": {
                "ok": False,
                "message": "no_data",
                "scan_age_sec": None,
                "scan_rate_hz": 0.0,
                "valid_count": 0,
                "valid_ratio": 0.0,
                "frame_id": "",
            },
            "map": {
                "ok": False,
                "message": "no_map",
                "map_age_sec": None,
                "width": 0,
                "height": 0,
                "resolution": 0.0,
                "frame_id": "",
            },
            "odom": {
                "ok": False,
                "message": "no_odom",
                "odom_age_sec": None,
                "frame_id": "",
                "child_frame_id": "",
                "linear_speed": 0.0,
                "angular_speed": 0.0,
            },
            "tf": {
                "ok": False,
                "message": "unavailable",
                "checked_at": None,
                "parent_frame": "odom",
                "child_frame": "base_link",
            },
            "map_pose": {
                "ok": False,
                "message": "unavailable",
                "x": 0.0,
                "y": 0.0,
                "yaw": 0.0,
                "frame_id": "map",
                "child_frame_id": "base_link",
                "updated_at": None,
            },
            "mapping_quality": {
                "ok": False,
                "level": "bad",
                "message": "lidar,map,odom,tf",
                "issues": ["lidar", "map", "odom", "tf"],
            },
            "detection": "",
            "color_target": None,
            "lane_offset": 0.0,
            "radar_points": [],
            "tracking_target": {"selection_mode": "auto", "state": "searching", "locked": False, "track_id": None},
            "camera": {"ok": False, "message": "not started"},
            "nodes": {},
            "last_command": "stop",
            "speed_scale": 1.0,
            "color_config": DEFAULT_COLOR_CONFIG,
            "updated_at": time.time(),
        }

    def snapshot(self):
        return copy.deepcopy(self._state)

    def update(self, **values):
        self._state.update(values)
        self._touch()
        return self.snapshot()

    def set_mode(self, mode):
        next_mode = normalize_mode(mode)
        self._state["mode"] = next_mode
        if next_mode == "stop":
            self._state["last_command"] = "stop"
        self._touch()
        return next_mode

    def set_command(self, command):
        if self._state["mode"] not in {"manual", "mapping"}:
            self._state["last_command"] = "stop"
            self._touch()
            return "stop"
        normalized = normalize_manual_command(command) or "stop"
        self._state["last_command"] = normalized
        self._touch()
        return normalized

    def set_emergency_stop(self, enabled):
        self._state["emergency_stop"] = bool(enabled)
        if enabled:
            self._state["mode"] = "stop"
            self._state["last_command"] = "stop"
        self._touch()
        return self._state["emergency_stop"]

    def set_speed_scale(self, value):
        scale = max(MIN_SPEED_SCALE, min(1.0, float(value)))
        self._state["speed_scale"] = scale
        self._touch()
        return scale

    def set_color_config(self, payload):
        config = normalize_color_config(payload)
        self._state["color_config"] = config
        self._touch()
        return config

    def _touch(self):
        self._state["updated_at"] = time.time()
