from pathlib import Path
import xml.etree.ElementTree as ET

import yaml


ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "ros2_ws/src/smart_car_decision"


def test_mapping_runtime_dependencies_are_declared():
    root = ET.parse(PACKAGE / "package.xml").getroot()
    dependencies = {node.text for node in root.findall("exec_depend")}

    assert {
        "nav_msgs",
        "tf2_ros",
        "slam_toolbox",
        "nav2_map_server",
        "nav2_lifecycle_manager",
    } <= dependencies


def test_slam_toolbox_config_has_required_frames_and_safe_initial_values():
    config = yaml.safe_load(
        (PACKAGE / "config/slam_toolbox.yaml").read_text(encoding="utf-8")
    )["slam_toolbox"]["ros__parameters"]

    assert config["map_frame"] == "map"
    assert config["odom_frame"] == "odom"
    assert config["base_frame"] == "base_link"
    assert config["scan_topic"] == "/scan"
    assert config["mode"] == "mapping"
    assert 0.0 < config["resolution"] <= 0.1
    assert config["max_laser_range"] > 0.0


def test_mapping_launch_reuses_bringup_and_starts_slam_toolbox():
    source = (PACKAGE / "launch/mapping.launch.py").read_text(encoding="utf-8")

    assert "bringup_all.launch.py" in source
    assert "slam_toolbox" in source
    assert "online_async_launch.py" in source
    assert "publish_laser_tf" in source
    assert "static_transform_publisher" in source

