from pathlib import Path
import xml.etree.ElementTree as ET
import ast
import math

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
        "yahboomcar_bringup",
        "imu_filter_madgwick",
        "robot_localization",
        "sllidar_ros2",
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
    assert config["map_update_interval"] == 0.5
    assert config["scan_queue_size"] == 1
    assert config["throttle_scans"] == 1
    assert config["minimum_time_interval"] == 0.1
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
    assert "static_transform_publisher" not in source
    assert '"publish_scan_laser_tf": LaunchConfiguration("publish_laser_tf")' in source


def test_bringup_launch_starts_vendor_odom_and_scan_tf_chain():
    source = (PACKAGE / "launch/bringup_all.launch.py").read_text(encoding="utf-8")

    assert "base_node_X3" in source
    assert "ekf_x1_x3.yaml" in source
    assert "robot_state_publisher" in source
    assert "yahboomcar_X3.urdf" in source
    assert "serial_port:=/dev/rplidar" in source
    assert "sllidar_a2m8_launch.py" not in source
    assert "base_to_scan_laser_static_tf" in source
    assert '"--child-frame-id", LaunchConfiguration("laser_frame")' in source


def _launch_nodes():
    tree = ast.parse((PACKAGE / "launch/bringup_all.launch.py").read_text(encoding="utf-8"))
    return {
        ast.literal_eval(next(item.value for item in call.keywords if item.arg == "name")): {
            keyword.arg: keyword.value for keyword in call.keywords
        }
        for call in ast.walk(tree)
        if isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id == "Node"
    }


def test_localization_has_one_odom_output_and_one_tf_owner():
    nodes = _launch_nodes()
    base = nodes["base_node"]
    ekf = nodes["ekf_filter_node"]
    imu = nodes["imu_filter_madgwick"]
    assert ast.literal_eval(base["parameters"])[0]["pub_odom_tf"] is False
    assert "remappings" not in base
    assert ast.literal_eval(ekf["package"]) == "robot_localization"
    assert ast.literal_eval(ekf["executable"]) == "ekf_node"
    assert ast.literal_eval(ekf["remappings"]) == [("odometry/filtered", "odom")]
    assert ast.literal_eval(imu["package"]) == "imu_filter_madgwick"
    assert "imu_filter_param.yaml" in ast.unparse(imu["parameters"])
    # A caller using vendor bringup must be able to disable the complete local chain.
    assert ast.dump(base["condition"]) == ast.dump(imu["condition"]) == ast.dump(ekf["condition"])


def test_ekf_restores_vendor_sensor_selection_and_planar_frames():
    config = yaml.safe_load((PACKAGE / "config/ekf_x1_x3.yaml").read_text(encoding="utf-8"))["ekf_filter_node"]["ros__parameters"]
    assert config["odom0"] == "/odom_raw"
    assert config["imu0"] == "/imu/data"
    assert config["world_frame"] == config["odom_frame"] == "odom"
    assert config["base_link_frame"] == "base_footprint"
    assert config["publish_tf"] is True
    assert config["two_d_mode"] is True
    assert config["frequency"] == 30.0
    assert config["imu0_relative"] is True
    assert config["odom0_config"] == [True, True, False, False, False, True, True, True, False, False, False, True, False, False, False]
    assert config["imu0_config"] == [False, False, False, False, False, True, False, False, False, False, False, True, False, False, False]
    assert len(config["process_noise_covariance"]) == 225
    assert len(config["initial_estimate_covariance"]) == 225


def test_laser_mount_is_explicit_and_only_one_tf_publisher_exists():
    nodes = _launch_nodes()
    laser_nodes = [node for node in nodes.values() if ast.literal_eval(node["package"]) == "tf2_ros"]
    assert len(laser_nodes) == 1
    args = laser_nodes[0]["arguments"]
    assert "laser_yaw" in ast.unparse(args)
    assert "base_frame" in ast.unparse(args)
    assert "laser_frame" in ast.unparse(args)
    tree = ast.parse((PACKAGE / "launch/bringup_all.launch.py").read_text(encoding="utf-8"))
    declaration = next(call for call in ast.walk(tree) if isinstance(call, ast.Call)
                       and isinstance(call.func, ast.Name) and call.func.id == "DeclareLaunchArgument"
                       and call.args and ast.literal_eval(call.args[0]) == "laser_yaw")
    default = next(item.value for item in declaration.keywords if item.arg == "default_value")
    assert math.isclose(float(ast.literal_eval(default)), math.pi)
