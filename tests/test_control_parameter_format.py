"""Nested YAML would flatten these keys instead of setting the declared ROS string."""
import json
from pathlib import Path
import yaml

def test_per_mode_obstacle_thresholds_are_a_ros_string_parameter():
    config = Path(__file__).resolve().parents[1] / "ros2_ws/src/smart_car_decision/config/decision.yaml"
    value = yaml.safe_load(config.read_text(encoding="utf-8"))["decision_controller"]["ros__parameters"]["mode_obstacle_stop_distances"]
    assert isinstance(value, str), "ROS would flatten a nested dictionary into unrelated dotted parameters"
    thresholds = json.loads(value)
    assert thresholds["manual"] == 0.0
    assert thresholds["mapping"] == 0.0
    assert thresholds["auto"] == thresholds["navigation"] == 0.45
