import pytest
from fastapi import HTTPException
from app.api.routes.vehicle_control import authorize_vehicle_write


@pytest.mark.parametrize("path,payload,permissions,status", [
    ("mode", {"mode": "auto"}, set(), 403),
    ("navigation/task", {}, {"robots.control", "missions.manage"}, 409),
    ("command", {"command": "set_mode", "payload": {"mode": "auto"}}, {"robots.control"}, 422),
    ("search/start", {}, {"robots.control"}, 403),
    ("navigation/calibration", {}, {"robots.control"}, 403),
    ("navigation/handoff-seed", {}, {"robots.control", "maps.manage"}, 409),
    ("mapping/finish-for-tasks", {}, {"robots.control", "maps.manage"}, 409),
])
def test_compatibility_control_cannot_bypass_permissions(path, payload, permissions, status):
    with pytest.raises(HTTPException) as error:
        authorize_vehicle_write(path, payload, permissions)
    assert error.value.status_code == status


def test_controlled_stop_remains_available():
    authorize_vehicle_write("command", {"command": "stop"}, {"robots.control"})
    authorize_vehicle_write("emergency-stop", {"enabled": True}, {"robots.control"})


def test_anonymous_compatibility_write_is_rejected(client):
    assert client.post("/api/control/mode", json={"mode": "auto"}).status_code == 401
    assert client.post("/api/mode", json={"mode": "auto"}).status_code == 401


def test_anonymous_vehicle_reads_are_rejected(client):
    for path in ("status", "map", "video", "navigation/config"):
        assert client.get("/api/control/" + path).status_code == 401


def test_status_socket_rejects_missing_authentication(client):
    from starlette.websockets import WebSocketDisconnect
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect("/ws/status") as socket:
            socket.send_json({"type": "hello"})
            socket.receive_json()
    assert error.value.code == 4401
