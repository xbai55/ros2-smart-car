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
