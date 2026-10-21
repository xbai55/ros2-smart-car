"""车端 Web API 端点测试。

这些测试用 FastAPI TestClient + 鸭子类型假节点运行，**不需要 ROS2 环境**，
因此只能证明「Web API 测试通过」，不能替代真实小车硬件验证。
"""

from fastapi.testclient import TestClient

from smart_car_decision.web_api import create_app, log_message


def _client(node, **kwargs):
    return TestClient(create_app(node, **kwargs))


def test_health_reports_web_node_alive_without_ros2_data(fake_node, web_client):
    response = web_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["node"] == "web_app_node"
    assert body["ros2"]["available"] is True
    assert body["ros2"]["data_ok"] is False
    assert body["ros2"]["data_age_sec"] is None
    assert body["ros2"]["status"] == "unknown"
    assert "GET /api/status" in body["endpoints"]


def test_health_reports_ros2_data_state_when_status_stream_is_fresh(make_fake_node):
    body = _client(make_fake_node(ros_status_age_sec=0.4)).get("/health").json()
    assert body["ros2"]["data_ok"] is True
    assert body["ros2"]["status"] == "connected"


def test_status_exposes_documented_fields_without_inventing_hardware_data(fake_node, web_client):
    body = web_client.get("/api/status").json()

    assert body["status"] == "idle"
    assert body["mode"] == "stop"
    assert body["battery"] is None
    assert body["temperature"] is None
    assert body["position"] is None
    assert body["speed"] is None
    assert body["current_task"] is None
    assert body["capabilities"]["battery"]["supported"] is False
    # 旧控制台继续使用原有字段
    assert body["lidar"]["ok"] is False
    assert body["speed_scale"] == 1.0
    assert body["tracking_target"]["state"] == "searching"


def test_status_maps_odom_speed_and_tf_pose(fake_node, web_client):
    fake_node.store.update(
        odom={"ok": True, "linear_speed": 0.25, "angular_speed": 0.0},
        map_pose={"ok": True, "x": 1.2, "y": 2.4, "yaw": 1.57},
        mode="auto",
    )

    body = web_client.get("/api/status").json()

    assert body["speed"] == 0.25
    assert body["position"] == {"x": 1.2, "y": 2.4, "yaw": 1.57}
    assert body["status"] == "running"


def test_status_reports_emergency_stop_state(fake_node, web_client):
    fake_node.store.set_emergency_stop(True)
    body = web_client.get("/api/status").json()
    assert body["status"] == "emergency_stop"
    assert body["mode"] == "stop"


def test_map_endpoint_returns_404_until_ros2_map_arrives(fake_node, web_client):
    assert web_client.get("/api/map").status_code == 404

    fake_node.map_snapshot.update(
        {"info": {"width": 2, "height": 2, "resolution": 0.05, "origin": {"x": 0.0, "y": 0.0, "yaw": 0.0}}, "data": [0, 100, -1, 0]}
    )
    response = web_client.get("/api/map")

    assert response.status_code == 200
    assert response.json()["info"]["resolution"] == 0.05


def test_manual_command_is_published_when_mode_allows_it(fake_node, web_client):
    fake_node.set_mode("manual")

    response = web_client.post("/api/command", json={"command": "forward"})

    assert response.status_code == 200
    assert response.json() == {"ok": True, "target": "manual_cmd", "command": "forward"}
    assert fake_node.manual_commands == ["forward"]
    assert fake_node.store.snapshot()["last_command"] == "forward"


def test_manual_command_is_rejected_outside_manual_or_mapping_mode(fake_node, web_client):
    response = web_client.post("/api/command", json={"command": "forward"})

    assert response.status_code == 409
    assert "manual or mapping" in response.json()["detail"]
    assert fake_node.store.snapshot()["last_command"] == "stop"


def test_stop_is_accepted_in_every_mode_and_during_emergency_stop(fake_node, web_client):
    for mode in ("stop", "auto", "navigation", "manual", "mapping"):
        fake_node.set_mode(mode)
        response = web_client.post("/api/command", json={"command": "stop"})
        assert response.status_code == 200
        assert response.json()["command"] == "stop"
    fake_node.set_emergency_stop(True)
    assert web_client.post("/api/command", json={"command": "stop"}).status_code == 200


def test_mode_requests_cannot_release_emergency_stop(fake_node, web_client):
    fake_node.set_emergency_stop(True)
    assert web_client.post("/api/mode", json={"mode": "manual"}).status_code == 409
    assert web_client.post("/api/command", json={"command": "set_mode", "payload": {"mode": "manual"}}).status_code == 409
    assert fake_node.store.snapshot()["emergency_stop"] is True
    assert fake_node.store.snapshot()["mode"] == "stop"


def test_logging_keeps_fixed_severity_per_ros_caller(fake_node):
    import inspect

    class RosStyleLogger:
        def __init__(self):
            self.callers = {}
            self.messages = []

        def _record(self, severity, message):
            caller = inspect.currentframe().f_back.f_back
            key = (caller.f_code.co_filename, caller.f_lineno)
            previous = self.callers.setdefault(key, severity)
            if previous != severity:
                raise ValueError("Logger severity cannot be changed between calls.")
            self.messages.append((severity, message))

        def info(self, message):
            self._record("info", message)

        def warning(self, message):
            self._record("warning", message)

        def error(self, message):
            self._record("error", message)

    fake_node.logger = RosStyleLogger()
    for level in ("info", "warning", "error", "info", "warning"):
        log_message(fake_node, level, "control request")
    assert len(fake_node.logger.messages) == 5


def test_unknown_command_is_rejected_with_400(fake_node, web_client):
    response = web_client.post("/api/command", json={"command": "fly"})

    assert response.status_code == 400
    assert "fly" in response.json()["detail"]
    assert fake_node.manual_commands == []


def test_web_node_refuses_to_publish_cmd_vel(fake_node, web_client):
    response = web_client.post("/api/command", json={"topic": "/cmd_vel", "command": "forward"})

    assert response.status_code == 403
    assert "/cmd_vel" in response.json()["detail"]
    assert fake_node.manual_commands == []


def test_manual_command_does_not_rescale_speed_because_decision_controller_owns_it(fake_node, web_client):
    fake_node.set_mode("manual")

    response = web_client.post("/api/command", json={"command": "forward", "speed": 0.3})

    assert response.json()["command"] == "forward"
    assert fake_node.manual_commands == ["forward"]
    assert fake_node.speed_scale_commands == []


def test_gateway_robot_gateway_envelope_is_accepted(fake_node, web_client):
    fake_node.set_mode("manual")

    response = web_client.post(
        "/api/command",
        json={
            "robot_id": "r-001",
            "type": "manual_cmd",
            "topic": "/manual_cmd",
            "command": "rotate_left",
            "payload": {"speed": 0.3},
        },
    )

    assert response.status_code == 200
    assert response.json()["command"] == "turn_left"
    assert fake_node.manual_commands == ["turn_left"]


def test_api_command_dispatches_gateway_control_intents(fake_node, web_client):
    assert (
        web_client.post(
            "/api/command",
            json={"topic": "/robot/mode/set", "command": "set_mode", "payload": {"mode": "mapping"}},
        ).json()["mode"]
        == "mapping"
    )
    assert (
        web_client.post(
            "/api/command",
            json={"topic": "/robot/speed_scale", "command": "speed_scale", "payload": {"speed": 0.4}},
        ).json()["speed_scale"]
        == 0.4
    )
    assert (
        web_client.post(
            "/api/command",
            json={
                "topic": "/robot/emergency_stop/set",
                "command": "emergency_stop",
                "payload": {"enabled": True},
            },
        ).json()["emergency_stop"]
        is True
    )

    assert fake_node.mode_commands == ["mapping"]
    assert fake_node.speed_scale_commands == [0.4]
    assert fake_node.emergency_stop_commands == [True]


def test_api_command_forwards_task_intents_to_task_executors(fake_node, web_client):
    response = web_client.post(
        "/api/command",
        json={"topic": "/patrol_task/set", "command": "patrol_task", "payload": {"action": "start"}},
    )
    assert response.status_code == 200
    assert fake_node.patrol_tasks == [{"action": "start"}]

    response = web_client.post(
        "/api/command",
        json={
            "topic": "/mission_task/set",
            "command": "mission_task",
            "payload": {"action": "dispatch", "status": "running"},
        },
    )
    assert response.status_code == 200
    assert fake_node.mission_tasks == [{"action": "dispatch", "status": "running"}]


def test_patrol_and_mission_endpoints_validate_actions(fake_node, web_client):
    assert web_client.post("/api/patrol-task", json={"action": "start"}).status_code == 200
    assert web_client.post("/api/mission-task", json={"action": "dispatch"}).status_code == 200

    assert web_client.post("/api/patrol-task", json={"action": "teleport"}).status_code == 422
    assert web_client.post("/api/mission-task", json={}).status_code == 422


def test_mode_endpoint_accepts_legacy_and_gateway_payloads(fake_node, web_client):
    assert web_client.post("/api/mode", json={"mode": "auto"}).json()["mode"] == "auto"
    assert fake_node.store.snapshot()["mode"] == "auto"

    response = web_client.post("/api/mode", json={"payload": {"mode": "manual"}})
    assert response.status_code == 200
    assert response.json()["mode"] == "manual"

    assert web_client.post("/api/mode", json={"mode": "fly"}).status_code == 422
    assert web_client.post("/api/mode", json={}).status_code == 422


def test_emergency_stop_uses_existing_ros2_estop_mechanism(fake_node, web_client):
    fake_node.set_mode("manual")

    response = web_client.post("/api/emergency-stop", json={"enabled": True})

    assert response.status_code == 200
    assert response.json()["emergency_stop"] is True
    assert fake_node.emergency_stop_commands == [True]
    assert fake_node.manual_commands[-1] == "stop"
    assert fake_node.store.snapshot()["mode"] == "stop"

    response = web_client.post("/api/emergency-stop", json={"payload": {"enabled": False}})
    assert response.json()["emergency_stop"] is False
    assert fake_node.emergency_stop_commands == [True, False]

    assert web_client.post("/api/emergency-stop", json={}).status_code == 422


def test_speed_endpoint_accepts_all_documented_payload_shapes(fake_node, web_client):
    assert web_client.post("/api/speed", json={"scale": 0.5}).json()["speed_scale"] == 0.5
    assert web_client.post("/api/speed", json={"speed_scale": 0.8}).json()["speed_scale"] == 0.8
    assert web_client.post("/api/speed", json={"speed": 0.2}).json()["speed_scale"] == 0.2
    assert web_client.post("/api/speed", json={"payload": {"speed": 0.3}}).json()["speed_scale"] == 0.3

    assert fake_node.speed_scale_commands == [0.5, 0.8, 0.2, 0.3]


def test_speed_scale_is_clamped_to_safe_range(fake_node, web_client):
    assert web_client.post("/api/speed", json={"scale": 0.01}).json()["speed_scale"] == 0.15
    assert web_client.post("/api/speed", json={"scale": 3.0}).json()["speed_scale"] == 1.0
    assert web_client.post("/api/speed", json={"scale": "fast"}).status_code == 422


def test_ws_status_pushes_legacy_snapshot_and_documented_envelope(fake_node, web_client):
    with web_client.websocket_connect("/ws/status") as websocket:
        frame = websocket.receive_json()

    assert frame["type"] == "robot_status"
    assert isinstance(frame["timestamp"], float)
    assert frame["mode"] == "stop"
    assert frame["lidar"]["ok"] is False
    assert set(frame["data"]) == {
        "status",
        "mode",
        "battery",
        "speed",
        "position",
        "network",
        "temperature",
        "current_task",
    }
    assert frame["data"]["mode"] == "stop"
    assert frame["data"]["battery"] is None


def test_ws_control_publishes_manual_command_and_stops_on_disconnect(fake_node, web_client):
    fake_node.set_mode("manual")

    with web_client.websocket_connect("/ws/control") as websocket:
        websocket.send_json({"command": "forward"})
        assert websocket.receive_json() == {"ok": True, "command": "forward"}

    assert fake_node.manual_commands == ["forward", "stop"]


def test_ws_control_rejects_cmd_vel_requests(fake_node, web_client):
    fake_node.set_mode("manual")

    with web_client.websocket_connect("/ws/control") as websocket:
        websocket.send_json({"topic": "/cmd_vel", "command": "forward"})
        payload = websocket.receive_json()

    assert payload["ok"] is False
    assert "/cmd_vel" in payload["detail"]
    assert fake_node.manual_commands == ["stop"]


def test_current_task_tracks_active_patrol_and_mission_tasks(fake_node, web_client):
    assert web_client.get("/api/status").json()["current_task"] is None

    web_client.post("/api/patrol-task", json={"action": "start", "progress": 0.1})
    assert web_client.get("/api/status").json()["current_task"]["type"] == "patrol_task"

    web_client.post("/api/patrol-task", json={"action": "cancel"})
    assert web_client.get("/api/status").json()["current_task"] is None

    web_client.post("/api/mission-task", json={"action": "dispatch", "status": "running"})
    assert web_client.get("/api/status").json()["current_task"] == {
        "type": "mission_task",
        "action": "dispatch",
        "status": "running",
    }


def test_video_endpoints_do_not_run_the_real_camera(fake_node, web_client):
    assert web_client.get("/api/video").json() == {
        "ok": False,
        "stream_url": None,
        "message": "camera is not available",
    }
    assert web_client.get("/video_feed").status_code == 503


def test_mapping_save_export_passes_through_the_exact_saved_snapshot(fake_node):
    calls=[]
    def save(**kwargs):
        calls.append(kwargs)
        return {"ok":True,"yaml_path":"saved.yaml","pgm_path":"saved.pgm","snapshot":{"session_id":"current","revision":9,"data":[0,100]}}
    fake_node.map_snapshot.save=save
    response=_client(fake_node).post('/api/mapping/save',json={'include_snapshot':True})
    assert response.status_code==200
    assert response.json()['snapshot']['revision']==9
    assert calls==[{'include_snapshot':True}]


def test_video_info_reports_annotated_fallback_when_ros2_mode_owns_camera(fake_node):
    class _Camera:
        def is_blocked_by_mode(self):
            return True

    info = _client(fake_node, camera=_Camera()).get("/api/video").json()

    assert info["ok"] is True
    assert info["stream_url"] == "/video_feed"
    assert info["source"] == "annotated"
    assert info["blocked_by_mode"] is True


def test_finite_video_frame_is_fresh_and_cannot_be_cached(fake_node):
    class Camera:
        def is_blocked_by_mode(self):
            return False

        def frame_snapshot(self):
            return {"jpeg": b"jpeg", "sequence": 15, "age_ms": 23.5}

    response = _client(fake_node, camera=Camera()).get("/api/video?frame=true")
    assert response.status_code == 200
    assert response.content == b"jpeg"
    assert response.headers["content-type"] == "image/jpeg"
    assert "no-store" in response.headers["cache-control"]
    assert response.headers["x-frame-sequence"] == "15"
    assert response.headers["x-frame-age-ms"] == "23.5"


def test_finite_video_rejects_stale_frame_instead_of_replaying_it(fake_node):
    class Camera:
        def is_blocked_by_mode(self):
            return False

        def frame_snapshot(self):
            return None

    assert _client(fake_node, camera=Camera()).get("/api/video?frame=true").status_code == 503


def test_finite_video_in_vision_mode_uses_annotated_frames_only(fake_node):
    class Camera:
        closed = False

        def is_blocked_by_mode(self):
            return True

        def close(self):
            self.closed = True

        def frame_snapshot(self):
            raise AssertionError("vision mode must not reopen the camera")

    class Annotated:
        def frame_snapshot(self):
            return {"jpeg": b"annotated", "sequence": 2, "age_ms": 10}

    camera = Camera()
    response = _client(fake_node, camera=camera, annotated_stream=Annotated()).get("/api/video?frame=true")
    assert response.content == b"annotated"
    assert response.headers["x-frame-source"] == "annotated"
    assert camera.closed


def test_web_console_is_served_from_the_configured_static_dir(fake_node, tmp_path):
    (tmp_path / "index.html").write_text("<html>console</html>", encoding="utf-8")

    response = _client(fake_node, static_dir=tmp_path).get("/")

    assert response.status_code == 200
    assert "console" in response.text


def test_root_returns_404_when_the_console_is_not_installed(fake_node, web_client):
    assert web_client.get("/").status_code == 404


def test_http_requests_and_control_actions_are_logged(fake_node, web_client):
    fake_node.set_mode("manual")
    web_client.post("/api/command", json={"command": "forward"})

    messages = [message for _, message in fake_node.logger.messages]
    assert any("HTTP POST /api/command" in message for message in messages)
    assert any("手动命令请求 -> forward" in message for message in messages)
