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
        "robot_state_publisher",
        "slam_toolbox",
        "nav2_map_server",
        "nav2_lifecycle_manager",
        "yahboomcar_base_node",
        "yahboomcar_description",
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
    assert config["max_laser_range"] == 6.0
    assert config["map_update_interval"] == 1.0
    assert config["minimum_travel_distance"] == 0.08
    assert config["minimum_travel_heading"] == 0.08
    assert config["loop_match_minimum_response_coarse"] >= 0.45
    assert config["loop_match_minimum_response_fine"] >= 0.55


def test_mapping_launch_reuses_bringup_and_starts_slam_toolbox():
    source = (PACKAGE / "launch/mapping.launch.py").read_text(encoding="utf-8")

    assert "bringup_all.launch.py" in source
    assert "slam_toolbox" in source
    assert "online_async_launch.py" in source
    assert "publish_laser_tf" in source
    assert "static_transform_publisher" in source


def test_bringup_launch_starts_vendor_odom_and_scan_tf_chain():
    source = (PACKAGE / "launch/bringup_all.launch.py").read_text(encoding="utf-8")

    assert "base_node_X3" in source
    assert "odom_raw" in source
    assert "robot_state_publisher" in source
    assert "yahboomcar_X3.urdf" in source
    assert "lidar_serial_port" in source
    assert "SMART_CAR_LIDAR_PORT" in source
    assert "serial_port:=" in source
    assert "sllidar_a2m8_launch.py" not in source
    assert "base_to_scan_laser_static_tf" in source
    assert "--child-frame-id\", \"laser" in source


def test_bringup_launch_can_disable_camera_nodes_and_override_camera_source():
    source = (PACKAGE / "launch/bringup_all.launch.py").read_text(encoding="utf-8")

    assert "start_yolo_camera" in source
    assert "start_color_tracker" in source
    assert "start_web_camera" in source
    assert "SMART_CAR_CAMERA_SOURCE" in source
    assert "enable_camera_stream" in source
    assert "condition=IfCondition(LaunchConfiguration(\"start_yolo_camera\"))" in source
    assert "condition=IfCondition(LaunchConfiguration(\"start_color_tracker\"))" in source
