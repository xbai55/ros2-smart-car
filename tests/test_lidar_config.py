from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "ros2_ws/src/smart_car_decision/config/decision.yaml"


def test_all_front_scan_consumers_share_direction_and_percentile_parameters():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    expected = {
        "front_center_deg": 180.0,
        "front_angle_deg": 35.0,
        "front_distance_percentile": 20.0,
    }

    for node_name in (
        "decision_controller",
        "laser_obstacle_monitor",
        "system_status_node",
    ):
        params = config[node_name]["ros__parameters"]
        assert {key: params[key] for key in expected} == expected


def test_status_node_has_explicit_lidar_health_thresholds():
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    params = config["system_status_node"]["ros__parameters"]

    assert params["scan_timeout_sec"] == 0.6
    assert params["health_window_size"] >= 2
    assert 0.0 < params["min_valid_ratio"] <= 1.0

