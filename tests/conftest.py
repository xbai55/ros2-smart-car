import sys
from pathlib import Path

import pytest


PACKAGE_ROOT = (
    Path(__file__).resolve().parents[1]
    / "ros2_ws"
    / "src"
    / "smart_car_decision"
)
sys.path.insert(0, str(PACKAGE_ROOT))


class FakeLogger:
    """记录日志调用，避免测试依赖 ROS2 logger。"""

    def __init__(self):
        self.messages = []

    def info(self, message):
        self.messages.append(("info", str(message)))

    def warning(self, message):
        self.messages.append(("warning", str(message)))

    def error(self, message):
        self.messages.append(("error", str(message)))


class FakePoseLog:
    def __init__(self):
        self.entries = []

    def snapshot(self, limit=None):
        entries = self.entries if limit is None else self.entries[-int(limit):]
        return {"ok": True, "count": len(self.entries), "path": "memory", "entries": list(entries)}

    def clear(self):
        self.entries.clear()


class FakeMapSnapshotStore:
    def __init__(self):
        self._snapshot = None

    def update(self, snapshot):
        self._snapshot = snapshot

    def snapshot(self):
        return None if self._snapshot is None else dict(self._snapshot)

    def save(self, directory=None):
        if self._snapshot is None:
            raise RuntimeError("map is not available")
        return {
            "ok": True,
            "message": "map saved",
            "yaml_path": "memory.yaml",
            "pgm_path": "memory.pgm",
        }


class FakeMappingRestart:
    def __init__(self):
        self.calls = 0

    def restart(self):
        self.calls += 1
        return {"ok": True, "pid": 4242, "message": "slam_toolbox restarted"}


class FakeWebNode:
    """WebAppNode 的鸭子类型替身：无需 ROS2 即可测试车端 Web API。"""

    def __init__(self, ros_status_age_sec=None):
        from smart_car_decision.web_state import RobotStateStore, normalize_tracking_target_request

        self._normalize_tracking_target = normalize_tracking_target_request
        self.store = RobotStateStore()
        self.map_snapshot = FakeMapSnapshotStore()
        self.mapping_restart = FakeMappingRestart()
        self.pose_debug_log = FakePoseLog()
        self.logger = FakeLogger()
        self.ros2_available = True
        self._ros_status_age_sec = ros_status_age_sec
        self.mode_commands = []
        self.manual_commands = []
        self.emergency_stop_commands = []
        self.speed_scale_commands = []
        self.color_configs = []
        self.obstacle_distances = []
        self.tracking_targets = []
        self.patrol_tasks = []
        self.mission_tasks = []

    def get_logger(self):
        return self.logger

    def get_name(self):
        return "web_app_node"

    def ros_status_age_sec(self):
        return self._ros_status_age_sec

    def set_mode(self, mode):
        result = self.store.set_mode(mode)
        self.mode_commands.append(result)
        return result

    def set_command(self, command):
        result = self.store.set_command(command)
        self.manual_commands.append(result)
        return result

    def set_emergency_stop(self, enabled):
        result = self.store.set_emergency_stop(enabled)
        self.emergency_stop_commands.append(result)
        if result:
            # 与 WebAppNode 一致：急停时同时下发 stop 到 /manual_cmd
            self.set_command("stop")
        return result

    def set_speed_scale(self, value):
        result = self.store.set_speed_scale(value)
        self.speed_scale_commands.append(result)
        return result

    def set_color_config(self, payload):
        result = self.store.set_color_config(payload)
        self.color_configs.append(result)
        return result

    def set_mode_obstacle_stop_distance(self, mode, distance):
        result = self.store.set_mode_obstacle_stop_distance(mode, distance)
        self.obstacle_distances.append((mode, distance))
        return result

    def set_tracking_target(self, payload):
        request = self._normalize_tracking_target(payload)
        self.tracking_targets.append(request)
        return request

    def set_patrol_task(self, payload):
        task = self.store.set_patrol_task(payload)
        self.patrol_tasks.append(payload)
        return task

    def set_mission_task(self, payload):
        task = self.store.set_mission_task(payload)
        self.mission_tasks.append(payload)
        return task


@pytest.fixture
def fake_node():
    return FakeWebNode()


@pytest.fixture
def make_fake_node():
    def _make(**kwargs):
        return FakeWebNode(**kwargs)

    return _make


@pytest.fixture
def web_client(fake_node):
    from fastapi.testclient import TestClient

    from smart_car_decision.web_api import create_app

    return TestClient(create_app(fake_node))
