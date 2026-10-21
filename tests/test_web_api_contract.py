"""车端 Web API 契约与安全红线测试（纯 Python，不需要 ROS2）。

重点验证三件事：

1. Web API 能同时吃下旧控制台的载荷与主机端 Robot Gateway 的载荷；
2. Web API → ROS2 控制意图话题的映射固定不变；
3. Web Node 永远不会成为 /cmd_vel 的发布者。
"""

import ast
from pathlib import Path

import pytest

from smart_car_decision.control_policy import VALID_MODES
from smart_car_decision.web_api import (
    FORBIDDEN_TOPICS,
    TOPIC_TARGETS,
    WebRequestError,
    build_status_payload,
    build_ws_status_frame,
    derive_current_task,
    derive_network,
    normalize_command_request,
    normalize_emergency_request,
    normalize_mode_request,
    normalize_speed_request,
    normalize_task_request,
    resolve_bind_address,
)

PACKAGE_DIR = (
    Path(__file__).resolve().parents[1]
    / "ros2_ws"
    / "src"
    / "smart_car_decision"
    / "smart_car_decision"
)
WEB_NODE = PACKAGE_DIR / "web_app_node.py"

# Web Node 允许发布的话题参数；这份白名单里没有 /cmd_vel。
ALLOWED_PUBLISHER_PARAMETERS = {
    "mode_set_topic",
    "manual_cmd_topic",
    "emergency_stop_set_topic",
    "speed_scale_topic",
    "mode_obstacle_stop_distance_topic",
    "color_config_topic",
    "tracking_target_set_topic",
    "patrol_task_topic",
    "mission_task_topic",
}

EXPECTED_TOPIC_PARAMETERS = {
    "status_topic": "/robot/status",
    "mode_set_topic": "/robot/mode/set",
    "manual_cmd_topic": "/manual_cmd",
    "emergency_stop_set_topic": "/robot/emergency_stop/set",
    "speed_scale_topic": "/robot/speed_scale",
    "mode_obstacle_stop_distance_topic": "/robot/mode_obstacle_stop_distances",
    "color_config_topic": "/vision/color_config",
    "tracking_target_set_topic": "/vision/tracking_target/set",
    "annotated_frame_topic": "/vision/annotated_frame",
    "patrol_task_topic": "/patrol_task/set",
    "mission_task_topic": "/mission_task/set",
    "patrol_progress_topic": "/patrol_task/progress",
    "mission_state_topic": "/mission_task/state",
}


def _published_parameter_names(tree):
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "create_publisher"):
            continue
        for argument in node.args:
            for inner in ast.walk(argument):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and inner.func.attr == "get_parameter"
                    and inner.args
                    and isinstance(inner.args[0], ast.Constant)
                ):
                    names.append(inner.args[0].value)
    return names


def test_command_normalizer_accepts_legacy_and_gateway_payloads():
    assert normalize_command_request({"command": "forward"}) == {
        "target": "manual_cmd",
        "value": "forward",
    }
    assert normalize_command_request({"topic": "/manual_cmd", "command": "rotate_left"}) == {
        "target": "manual_cmd",
        "value": "turn_left",
    }
    assert normalize_command_request(
        {"topic": "/robot/mode/set", "command": "set_mode", "payload": {"mode": "auto"}}
    ) == {"target": "mode", "value": "auto"}
    assert normalize_command_request({"command": "mode", "mode": "mapping"}) == {
        "target": "mode",
        "value": "mapping",
    }
    assert normalize_command_request(
        {"topic": "/robot/speed_scale", "command": "speed_scale", "payload": {"speed": "0.5"}}
    ) == {"target": "speed", "value": 0.5}
    assert normalize_command_request(
        {"topic": "/robot/emergency_stop/set", "command": "emergency_stop", "payload": {"enabled": "true"}}
    ) == {"target": "emergency_stop", "value": True}
    assert normalize_command_request(
        {"topic": "/patrol_task/set", "command": "patrol_task", "payload": {"action": "START"}}
    ) == {"target": "patrol_task", "value": {"action": "start"}}


def test_command_normalizer_rejects_unknown_command_with_400():
    with pytest.raises(WebRequestError) as error:
        normalize_command_request({"command": "teleport"})

    assert error.value.status_code == 400


def test_command_normalizer_rejects_cmd_vel_with_403():
    with pytest.raises(WebRequestError) as error:
        normalize_command_request({"topic": "/cmd_vel", "command": "forward"})

    assert error.value.status_code == 403


def test_mode_speed_and_emergency_normalizers_are_strict():
    assert normalize_mode_request({"mode": " AUTO "}) == "auto"
    with pytest.raises(WebRequestError):
        normalize_mode_request({"mode": "flying"})
    with pytest.raises(WebRequestError):
        normalize_mode_request({})

    assert normalize_speed_request({"scale": 0.5}) == 0.5
    assert normalize_speed_request({"payload": {"speed": 0.25}}) == 0.25
    with pytest.raises(WebRequestError):
        normalize_speed_request({"scale": "fast"})
    with pytest.raises(WebRequestError):
        normalize_speed_request({})

    assert normalize_emergency_request({"enabled": True}) is True
    assert normalize_emergency_request({"payload": {"enabled": False}}) is False
    with pytest.raises(WebRequestError):
        normalize_emergency_request({"enabled": "maybe"})


def test_task_normalizer_limits_actions_to_what_the_executors_handle():
    assert normalize_task_request({"action": "start"}, "patrol_task") == {"action": "start"}
    assert normalize_task_request(
        {"payload": {"action": "dispatch", "status": "running"}}, "mission_task"
    ) == {"action": "dispatch", "status": "running"}

    with pytest.raises(WebRequestError):
        normalize_task_request({"action": "pause"}, "mission_task")
    with pytest.raises(WebRequestError):
        normalize_task_request({"action": "unknown"}, "patrol_task")


def test_web_api_targets_match_the_documented_ros2_control_intent_topics():
    assert TOPIC_TARGETS == {
        "/manual_cmd": "manual_cmd",
        "/robot/mode/set": "mode",
        "/robot/speed_scale": "speed",
        "/robot/emergency_stop/set": "emergency_stop",
        "/patrol_task/set": "patrol_task",
        "/mission_task/set": "mission_task",
    }
    assert "/cmd_vel" not in TOPIC_TARGETS
    assert FORBIDDEN_TOPICS == {"/cmd_vel"}


def test_web_node_publisher_whitelist_excludes_cmd_vel():
    tree = ast.parse(WEB_NODE.read_text(encoding="utf-8-sig"))

    published = _published_parameter_names(tree)

    assert published
    assert set(published) <= ALLOWED_PUBLISHER_PARAMETERS
    assert "cmd_vel" not in WEB_NODE.read_text(encoding="utf-8-sig")


def test_web_node_topic_parameters_are_the_documented_ros2_topics():
    tree = ast.parse(WEB_NODE.read_text(encoding="utf-8-sig"))
    declared = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "declare_parameter" or len(node.args) < 2:
            continue
        name, default = node.args[0], node.args[1]
        if isinstance(name, ast.Constant) and isinstance(default, ast.Constant):
            if isinstance(name.value, str) and name.value.endswith("_topic"):
                declared[name.value] = default.value

    assert declared == EXPECTED_TOPIC_PARAMETERS


def test_decision_controller_remains_the_only_cmd_vel_publisher():
    publishers = []
    for path in sorted(PACKAGE_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (isinstance(node.func, ast.Attribute) and node.func.attr == "create_publisher"):
                continue
            if any(isinstance(argument, ast.Attribute) and argument.attr == "cmd_vel_topic" for argument in node.args):
                publishers.append(path.name)

    assert publishers == ["decision_controller.py"]


def test_bind_address_prefers_environment_over_ros2_parameters():
    assert resolve_bind_address("127.0.0.1", 9000, {}) == ("127.0.0.1", 9000)
    assert resolve_bind_address("127.0.0.1", 9000, {"WEB_HOST": "0.0.0.0", "WEB_PORT": "8080"}) == (
        "0.0.0.0",
        8080,
    )
    assert resolve_bind_address(None, None, {}) == ("0.0.0.0", 8080)
    assert resolve_bind_address(None, "not-a-port", {}) == ("0.0.0.0", 8080)


def test_network_state_is_derived_from_status_freshness():
    assert derive_network(None) == "unknown"
    assert derive_network(0.5) == "connected"
    assert derive_network(5.0) == "stale"
    assert derive_network(60.0) == "disconnected"


def test_ws_frame_keeps_legacy_fields_and_adds_documented_envelope():
    snapshot = {"mode": "auto", "emergency_stop": False, "map_pose": {"ok": True, "x": 1.0, "y": 2.0, "yaw": 0.5}}

    frame = build_ws_status_frame(snapshot, ros_status_age_sec=0.2, now=1000.0)

    assert frame["mode"] == "auto"
    assert frame["type"] == "robot_status"
    assert frame["timestamp"] == 1000.0
    assert frame["data"] == {
        "status": "running",
        "mode": "auto",
        "battery": None,
        "speed": None,
        "position": {"x": 1.0, "y": 2.0, "yaw": 0.5},
        "network": "connected",
        "temperature": None,
        "current_task": None,
    }


def test_status_payload_documents_missing_hardware_instead_of_faking_it():
    payload = build_status_payload({"mode": "stop"}, ros_status_age_sec=None, now=10.0)

    assert payload["battery"] is None
    assert payload["temperature"] is None
    assert payload["position"] is None
    assert payload["speed"] is None
    assert payload["network"] == "unknown"
    assert payload["capabilities"]["battery"]["supported"] is False
    assert payload["capabilities"]["temperature"]["supported"] is False
    assert payload["capabilities"]["position"]["source"] == "map_pose (TF map->base_link)"


def test_current_task_prefers_the_most_recently_updated_task():
    snapshot = {
        "patrol_task": {"active": True, "action": "progress", "progress": 0.5, "updated_at": 10.0},
        "mission_task": {"active": True, "action": "dispatch", "status": "running", "updated_at": 20.0},
    }
    assert derive_current_task(snapshot)["type"] == "mission_task"
    assert derive_current_task({}) is None


def test_every_documented_mode_is_accepted_by_the_web_api():
    for mode in VALID_MODES:
        assert normalize_mode_request({"mode": mode}) == mode
