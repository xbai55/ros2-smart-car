import copy
import time

from .control_policy import normalize_manual_command, normalize_mode
from .color_config import DEFAULT_COLOR_CONFIG, normalize_color_config

MIN_SPEED_SCALE = 0.15


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
            "detection": "",
            "color_target": None,
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
