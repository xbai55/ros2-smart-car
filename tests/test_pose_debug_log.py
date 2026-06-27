import json

from smart_car_decision.pose_debug_log import PoseDebugLog


def test_pose_debug_log_records_status_and_command(tmp_path):
    log = PoseDebugLog(path=tmp_path / "pose_debug.jsonl", max_entries=10)

    entry = log.append_status(
        {
            "mode": "mapping",
            "last_command": "forward",
            "speed_scale": 0.25,
            "map_pose": {"ok": True, "x": 1.2, "y": 0.3, "yaw": 0.1},
            "odom": {"linear_speed": 0.2, "angular_speed": 0.0},
            "tf": {"ok": True},
            "map": {"ok": True, "width": 80, "height": 60},
            "updated_at": 10.0,
        }
    )

    assert entry["last_command"] == "forward"
    assert entry["map_pose"]["x"] == 1.2
    snapshot = log.snapshot()
    assert snapshot["count"] == 1
    line = (tmp_path / "pose_debug.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["odom"]["linear_speed"] == 0.2


def test_pose_debug_log_clear_removes_memory_and_file(tmp_path):
    path = tmp_path / "pose_debug.jsonl"
    log = PoseDebugLog(path=path, max_entries=10)
    log.append_status({"mode": "mapping", "last_command": "stop"})

    log.clear()

    assert log.snapshot()["count"] == 0
    assert path.read_text(encoding="utf-8") == ""
