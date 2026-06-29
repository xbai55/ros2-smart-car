from smart_car_decision.color_config import normalize_color_config
from smart_car_decision.web_state import RobotStateStore


def test_normalize_color_config_clamps_hsv_values():
    config = normalize_color_config(
        {
            "name": "custom",
            "hsv_low": [-10, 80, 90],
            "hsv_high": [220, 300, 260],
        }
    )

    assert config == {
        "name": "custom",
        "hsv_low": [0, 80, 90],
        "hsv_high": [179, 255, 255],
    }


def test_state_store_records_color_config_snapshot():
    store = RobotStateStore()

    config = store.set_color_config(
        {
            "name": "red",
            "hsv_low": [0, 80, 80],
            "hsv_high": [12, 255, 255],
        }
    )

    assert config["name"] == "red"
    assert store.snapshot()["color_config"] == config


def test_color_tracker_publishes_bounding_box_and_uses_faster_default_rate():
    tracker_source = __import__("pathlib").Path("ros2_ws/src/smart_car_decision/smart_car_decision/color_tracker_node.py").read_text(encoding="utf-8-sig")
    config_source = __import__("pathlib").Path("ros2_ws/src/smart_car_decision/config/decision.yaml").read_text(encoding="utf-8-sig")

    assert "bounding_box" in tracker_source
    assert "boundingRect" in tracker_source
    assert "process_rate_hz: 20.0" in config_source


def test_partial_status_does_not_reset_applied_color_config_to_green():
    store = RobotStateStore()
    store.set_color_config({"name": "red", "hsv_low": [0, 80, 80], "hsv_high": [12, 255, 255]})

    snapshot = store.update(mode="color_track", color_target={"found": True, "offset": 0.1})

    assert snapshot["color_config"]["name"] == "red"
    assert snapshot["color_config"]["hsv_low"] == [0, 80, 80]
