import copy
import time

from .control_policy import MANUAL_COMMAND_MODES, normalize_manual_command, normalize_mode
from .color_config import DEFAULT_COLOR_CONFIG, normalize_color_config

MIN_SPEED_SCALE = 0.15
DEFAULT_MODE_OBSTACLE_STOP_DISTANCES = {
    "stop": 0.0,
    "manual": 0.0,
    "auto": 0.45,
    "mapping": 0.0,
    "navigation": 0.45,
    "color_track": 0.45,
    "object_follow": 0.45,
}


def normalize_mode_obstacle_stop_distances(payload):
    distances = dict(DEFAULT_MODE_OBSTACLE_STOP_DISTANCES)
    for mode, distance in dict(payload or {}).items():
        normalized = normalize_mode(mode)
        distances[normalized] = max(0.0, min(5.0, float(distance)))
    return distances


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


PATROL_ACTIVE_ACTIONS = {"start", "resume", "progress"}
MISSION_ACTIVE_ACTIONS = {"dispatch", "transporting"}


def _task_progress(payload):
    try:
        return max(0.0, min(1.0, float(payload.get("progress"))))
    except (TypeError, ValueError):
        return None


def normalize_patrol_task_state(payload, now=None):
    """把巡检任务指令归一化为状态快照（active 表示任务正在进行）。"""
    payload = payload or {}
    action = str(payload.get("action") or "").strip().lower()
    return {
        "active": action in PATROL_ACTIVE_ACTIONS,
        "message": action or "idle",
        "action": action or None,
        "progress": _task_progress(payload),
        "updated_at": time.time() if now is None else float(now),
    }


def normalize_mission_task_state(payload, now=None):
    """把运输任务指令归一化为状态快照。"""
    payload = payload or {}
    action = str(payload.get("action") or "").strip().lower()
    return {
        "active": action in MISSION_ACTIVE_ACTIONS,
        "message": action or "idle",
        "action": action or None,
        "status": payload.get("status"),
        "updated_at": time.time() if now is None else float(now),
    }


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
            "mode_obstacle_stop_distances": dict(DEFAULT_MODE_OBSTACLE_STOP_DISTANCES),
            "patrol_task": {"active": False, "message": "idle", "action": None, "progress": None, "updated_at": None},
            "mission_task": {"active": False, "message": "idle", "action": None, "status": None, "updated_at": None},
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
        if self._state["emergency_stop"]:
            next_mode = "stop"
        self._state["mode"] = next_mode
        if next_mode == "stop":
            self._state["last_command"] = "stop"
        self._touch()
        return next_mode

    def set_command(self, command):
        if self._state["emergency_stop"] or self._state["mode"] not in MANUAL_COMMAND_MODES:
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
        maximum = 0.5 if self._state["mode"] == "mapping" else 1.0
        scale = max(MIN_SPEED_SCALE, min(maximum, float(value)))
        self._state["speed_scale"] = scale
        self._touch()
        return scale

    def set_color_config(self, payload):
        config = normalize_color_config(payload)
        self._state["color_config"] = config
        self._touch()
        return config

    def set_mode_obstacle_stop_distance(self, mode, distance):
        normalized = normalize_mode(mode)
        distances = dict(self._state.get("mode_obstacle_stop_distances", DEFAULT_MODE_OBSTACLE_STOP_DISTANCES))
        distances[normalized] = max(0.0, min(5.0, float(distance)))
        self._state["mode_obstacle_stop_distances"] = distances
        self._touch()
        return distances

    def set_patrol_task(self, payload):
        self._state["patrol_task"] = normalize_patrol_task_state(payload)
        self._touch()
        return dict(self._state["patrol_task"])

    def set_mission_task(self, payload):
        self._state["mission_task"] = normalize_mission_task_state(payload)
        self._touch()
        return dict(self._state["mission_task"])

    def _touch(self):
        self._state["updated_at"] = time.time()
