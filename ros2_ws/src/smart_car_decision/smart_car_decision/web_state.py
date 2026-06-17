import copy
import time

from .control_policy import normalize_manual_command, normalize_mode


class RobotStateStore:
    def __init__(self):
        self._state = {
            "mode": "stop",
            "emergency_stop": False,
            "front_distance": None,
            "detection": "",
            "color_target": None,
            "camera": {"ok": False, "message": "not started"},
            "nodes": {},
            "last_command": "stop",
            "speed_scale": 1.0,
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
        if self._state["mode"] != "manual":
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
        scale = max(0.0, min(1.0, float(value)))
        self._state["speed_scale"] = scale
        self._touch()
        return scale

    def _touch(self):
        self._state["updated_at"] = time.time()
