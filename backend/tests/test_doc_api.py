"""项目文档接口表（/api/v1/patrol-tasks、/mission-tasks、/roles、/system/* 等）的测试。

新增数据统一使用 DOC- 前缀命名，测试结束后清理，避免影响其它测试文件。
"""
import shutil
import tempfile
from pathlib import Path

import pytest
from conftest import TestingSessionLocal
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.core.config import settings as app_settings
from app.db.migrate import ensure_schema
from app.models import Incident, MapModel, MissionTask, PatrolTask, Robot, Role, Route
from app.services import storage as storage_module


@pytest.fixture
def cleanup():
    yield
    db = TestingSessionLocal()
    try:
        for model in (Robot, PatrolTask, MissionTask, MapModel, Route, Role):
            for obj in db.query(model).filter(model.name.like("DOC-%")).all():
                db.delete(obj)
        for obj in db.query(Incident).filter(Incident.title.like("DOC-%")).all():
            db.delete(obj)
        db.commit()
    finally:
        db.close()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def _robot_id(client, token, index=0):
    robots = client.get("/api/v1/robots", headers=_headers(token)).json()
    return robots[index]["id"]


def test_role_and_permission_endpoints(client, login, cleanup):
    token = login("admin", "admin123")
    permissions = client.get("/api/v1/permissions", headers=_headers(token)).json()
    assert any(p["name"] == "robots.read" for p in permissions)

    created = client.post(
        "/api/v1/roles",
        json={"name": "DOC-role", "description": "文档接口测试角色", "permission_names": ["robots.read"]},
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    role = created.json()
    assert [p["name"] for p in role["permissions"]] == ["robots.read"]

    updated = client.put(
        f"/api/v1/roles/{role['id']}",
        json={"permission_names": ["robots.read", "maps.read"]},
        headers=_headers(token),
    )
    assert updated.status_code == 200
    assert {p["name"] for p in updated.json()["permissions"]} == {"robots.read", "maps.read"}

    roles = client.get("/api/v1/roles", headers=_headers(token)).json()
    assert any(item["name"] == "DOC-role" for item in roles)


def test_robot_crud_and_status(client, login, cleanup):
    token = login("admin", "admin123")
    created = client.post(
        "/api/v1/robots",
        json={
            "name": "DOC-Robot-01",
            "robot_code": "DOC-R-0001",
            "model": "ROSMASTER X3",
            "status": "online",
            "mode": "patrol",
            "battery": 88.0,
            "position": {"x": 1.0, "y": 2.0},
        },
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    robot = created.json()
    assert robot["robot_code"] == "DOC-R-0001"
    assert robot["position"] == {}

    updated = client.put(
        f"/api/v1/robots/{robot['id']}",
        json={"battery": 55.0, "health": "warning", "speed": 0.25},
        headers=_headers(token),
    )
    assert updated.status_code == 200
    assert updated.json()["battery"] is None
    assert updated.json()["health"] == "unknown"

    status = client.get(f"/api/v1/robots/{robot['id']}/status", headers=_headers(token)).json()
    assert status["robot_id"] == robot["id"]
    assert status["battery"] is None
    assert status["source"] == "unavailable"

    filtered = client.get(
        "/api/v1/robots", params={"keyword": "DOC-Robot-01"}, headers=_headers(token)
    ).json()
    assert len(filtered) == 1
    paged = client.get(
        "/api/v1/robots", params={"page": 1, "page_size": 1}, headers=_headers(token)
    ).json()
    assert set(paged) == {"items", "total", "page", "page_size"}


def test_robot_control_and_emergency_stop(client, login, cleanup):
    token = login("operator", "operator123")
    robot = client.post(
        "/api/v1/robots",
        json={"name": "DOC-Robot-02", "robot_code": "DOC-R-0002", "status": "online"},
        headers=_headers(token),
    ).json()

    control = client.post(
        f"/api/v1/robots/{robot['id']}/control",
        json={"command": "forward", "speed": 0.3},
        headers=_headers(token),
    )
    assert control.status_code == 200, control.text
    body = control.json()
    assert body["command"] == "forward"
    assert body["gateway"]["mode"] == "offline"
    assert body["gateway"]["command"]["topic"] == "/manual_cmd"

    bad = client.post(
        f"/api/v1/robots/{robot['id']}/control",
        json={"command": "teleport"},
        headers=_headers(token),
    )
    assert bad.status_code == 400

    estop = client.post(
        f"/api/v1/robots/{robot['id']}/emergency-stop",
        json={"enabled": True, "reason": "测试急停"},
        headers=_headers(token),
    )
    assert estop.status_code == 200, estop.text
    assert not estop.json()["ok"]
    assert estop.json()["robot"]["status"] == "offline"
    assert estop.json()["robot"]["emergency_stop"] is None
    # Only observed telemetry can latch the state, never the failed request.
    from app.services.realtime import get_realtime_store
    get_realtime_store().set_status(robot["id"], {"status":"estop", "emergency_stop":True})

    blocked = client.post(
        f"/api/v1/robots/{robot['id']}/control",
        json={"command": "forward", "speed": 0.2},
        headers=_headers(token),
    )
    assert blocked.status_code == 409

    stopped = client.post(
        f"/api/v1/robots/{robot['id']}/control",
        json={"command": "stop"},
        headers=_headers(token),
    )
    assert stopped.status_code == 200
    assert stopped.json()["command"] == "stop"

    released = client.post(
        f"/api/v1/robots/{robot['id']}/emergency-stop",
        json={"enabled": False, "reason": "测试解除"},
        headers=_headers(token),
    ).json()
    assert not released["ok"]
    assert released["robot"]["emergency_stop"] is True
    assert released["robot"]["status"] == "estop"


def test_patrol_task_documented_flow(client, login, cleanup):
    token = login("operator", "operator123")
    robot = client.post(
        "/api/v1/robots",
        json={"name": "DOC-Robot-03", "robot_code": "DOC-R-0003"},
        headers=_headers(token),
    ).json()
    maps = client.get("/api/v1/maps", headers=_headers(token)).json()
    route = client.post(
        "/api/v1/routes",
        json={"name": "DOC-Route-01", "map_id": maps[0]["id"], "points": [{"x": 0, "y": 0}]},
        headers=_headers(token),
    ).json()

    created = client.post(
        "/api/v1/patrol-tasks",
        json={
            "name": "DOC-Patrol-01",
            "description": "文档接口巡检任务",
            "robot_id": robot["id"],
            "map_id": maps[0]["id"],
            "route_id": route["id"],
            "target_area": "A 区化学实验室",
        },
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "pending"
    assert task["map_id"] == maps[0]["id"]

    listed = client.get(
        "/api/v1/patrol-tasks", params={"status": "pending"}, headers=_headers(token)
    ).json()
    assert any(item["id"] == task["id"] for item in listed)

    updated = client.put(
        f"/api/v1/patrol-tasks/{task['id']}",
        json={"description": "已修改", "progress": 10.0},
        headers=_headers(token),
    ).json()
    assert updated["description"] == "已修改"

    started = client.post(f"/api/v1/patrol-tasks/{task['id']}/start", headers=_headers(token))
    assert started.status_code == 200
    assert started.json()["status"] == "running"
    assert started.json()["started_at"]

    stopped = client.post(f"/api/v1/patrol-tasks/{task['id']}/stop", headers=_headers(token))
    assert stopped.json()["status"] == "cancelled"

    detail = client.get(f"/api/v1/patrol-tasks/{task['id']}", headers=_headers(token)).json()
    assert detail["status"] == "cancelled"


def test_mission_task_documented_flow(client, login, cleanup):
    token = login("operator", "operator123")
    created = client.post(
        "/api/v1/mission-tasks",
        json={
            "name": "DOC-Mission-01",
            "description": "文档接口运输任务",
            "cargo_name": "档案袋",
            "start_location": "A 栋前台",
            "end_location": "实验室 302",
        },
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    task = created.json()
    assert task["status"] == "queued"
    assert task["cargo"] == "档案袋"
    assert task["origin"] == "A 栋前台"
    assert task["end_location"] == "实验室 302"

    updated = client.put(
        f"/api/v1/mission-tasks/{task['id']}",
        json={"progress": 40.0, "cargo_name": "试剂箱"},
        headers=_headers(token),
    ).json()
    assert updated["progress"] == 40.0
    assert updated["cargo"] == "试剂箱"

    detail = client.get(f"/api/v1/mission-tasks/{task['id']}", headers=_headers(token)).json()
    assert detail["id"] == task["id"]


def test_incident_update_and_filters(client, login, cleanup):
    token = login("operator", "operator123")
    created = client.post(
        "/api/v1/incidents",
        json={
            "type": "DOC-smoke",
            "severity": "critical",
            "title": "DOC-烟雾告警",
            "description": "巡检点发现烟雾",
            "location": "A 区",
        },
        headers=_headers(token),
    )
    assert created.status_code == 201, created.text
    incident = created.json()
    assert incident["status"] == "open"
    assert incident["occurred_at"]

    handled = client.put(
        f"/api/v1/incidents/{incident['id']}",
        json={"status": "processing", "handle_result": "已派人核查"},
        headers=_headers(token),
    ).json()
    assert handled["status"] == "handling"
    assert handled["handle_result"] == "已派人核查"

    resolved = client.put(
        f"/api/v1/incidents/{incident['id']}",
        json={"status": "resolved"},
        headers=_headers(token),
    ).json()
    assert resolved["status"] == "resolved"
    assert resolved["resolved_at"]

    filtered = client.get(
        "/api/v1/incidents",
        params={"severity": "critical", "status": "resolved"},
        headers=_headers(token),
    ).json()
    assert any(item["id"] == incident["id"] for item in filtered)


def test_analytics_documented_endpoints(client, login):
    token = login("admin", "admin123")
    for path in (
        "/api/v1/analytics/overview",
        "/api/v1/analytics/tasks",
        "/api/v1/analytics/robots",
        "/api/v1/analytics/incidents",
        "/api/v1/statistics/overview",
    ):
        response = client.get(path, headers=_headers(token))
        assert response.status_code == 200, path
        assert response.json()

    overview = client.get("/api/v1/analytics/overview", headers=_headers(token)).json()
    assert {"total", "completed", "failed", "completion_rate"} <= set(overview["tasks"])
    tasks = client.get("/api/v1/analytics/tasks", headers=_headers(token)).json()
    assert len(tasks["trend"]) == 7


def test_system_and_settings_endpoints(client, login):
    token = login("admin", "admin123")
    info = client.get("/api/v1/system/info", headers=_headers(token)).json()
    assert info["database"] in {"sqlite", "postgresql"}
    assert info["realtime"]["backend"] in {"redis", "memory"}
    assert info["storage"]["backend"] in {"local", "minio"}

    settings = client.get("/api/v1/system/settings", headers=_headers(token)).json()
    assert "system_name" in settings

    updated = client.put(
        "/api/v1/system/settings",
        json={"values": {"log_retention_days": "45"}},
        headers=_headers(token),
    )
    assert updated.status_code == 200
    assert updated.json()["log_retention_days"] == "45"

    legacy = client.get("/api/v1/settings", headers=_headers(token)).json()
    assert legacy["log_retention_days"] == "45"


@pytest.fixture
def storage_dir(monkeypatch):
    """本地对象存储目录。不用 pytest 的 tmp_path，避免受限环境下的临时目录权限问题。"""
    path = Path(tempfile.mkdtemp(prefix=".tmp_doc_media_", dir=Path.cwd()))
    monkeypatch.setattr(app_settings, "storage_local_dir", str(path))
    storage_module.reset_storage()
    try:
        yield path
    finally:
        storage_module.reset_storage()
        shutil.rmtree(path, ignore_errors=True)


def test_media_local_object_roundtrip(client, login, storage_dir):
    token = login("operator", "operator123")
    presign = client.post(
        "/api/v1/media/presign",
        json={"key": "doc-test/frame.png"},
        headers=_headers(token),
    )
    assert presign.status_code == 200, presign.text
    assert presign.json()["backend"] == "local"

    upload = client.put(
        "/api/v1/media/object/doc-test/frame.png",
        content=b"fake-png-bytes",
        headers={"Content-Type": "image/png", **_headers(token)},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["size"] == len(b"fake-png-bytes")

    completed = client.post(
        "/api/v1/media/complete",
        json={"key": "doc-test/frame.png", "size": 14},
        headers=_headers(token),
    )
    assert completed.status_code == 200

    download = client.get("/api/v1/media/object/doc-test/frame.png", headers=_headers(token))
    assert download.status_code == 200
    assert download.content == b"fake-png-bytes"
    assert download.headers["content-type"] == "image/png"

    missing = client.get("/api/v1/media/object/doc-test/none.png", headers=_headers(token))
    assert missing.status_code == 404


def test_audit_logs_filter_and_pagination(client, login):
    token = login("admin", "admin123")
    logs = client.get(
        "/api/v1/audit-logs", params={"action": "auth.login"}, headers=_headers(token)
    ).json()
    assert logs
    assert all(log["action"] == "auth.login" for log in logs)

    paged = client.get(
        "/api/v1/audit-logs", params={"page": 1, "page_size": 5}, headers=_headers(token)
    ).json()
    assert set(paged) == {"items", "total", "page", "page_size"}
    assert len(paged["items"]) <= 5


def test_notifications_unread_filter(client, login):
    token = login("operator", "operator123")
    notes = client.get("/api/v1/notifications", headers=_headers(token)).json()
    assert notes
    unread = client.get(
        "/api/v1/notifications", params={"unread": True}, headers=_headers(token)
    ).json()
    assert all(not note["read"] for note in unread)

    first = notes[0]
    marked = client.post(
        f"/api/v1/notifications/{first['id']}/read",
        json={"read": True},
        headers=_headers(token),
    ).json()
    assert marked["read"] is True
    remaining = client.get(
        "/api/v1/notifications", params={"unread": True}, headers=_headers(token)
    ).json()
    assert all(note["id"] != first["id"] for note in remaining)


def test_robot_websocket_initial_frame(client, login):
    token = login("operator", "operator123")
    robot_id = _robot_id(client, token)
    from app.services.realtime import get_realtime_store
    get_realtime_store().set_status(robot_id, {"status":"online", "mode":"patrol", "battery":77.0,"position":{"x":1.0,"y":2.0}})
    with client.websocket_connect(f"/ws/v1/robots/{robot_id}") as websocket:
        message = websocket.receive_json()
        assert message["type"] == "robot_status"
        assert message["robot_id"] == robot_id
        assert message["status"]["battery"] == 77.0
        assert message["status"]["position"] == {"x": 1.0, "y": 2.0}


def test_openapi_document_generation(client):
    schema = client.get("/openapi.json").json()
    assert "/api/v1/patrol-tasks" in schema["paths"]
    assert "/api/v1/mission-tasks" in schema["paths"]
    assert "/api/v1/robots/{robot_id}/emergency-stop" in schema["paths"]


def test_ensure_schema_adds_missing_columns():
    engine = create_engine("sqlite://", poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE robots ("
                "id VARCHAR(36) PRIMARY KEY, name VARCHAR(128), serial VARCHAR(128))"
            )
        )
    added = ensure_schema(engine)
    assert "robots.robot_code" in added
    assert "robots.health" in added
    columns = {c["name"] for c in inspect(engine).get_columns("robots")}
    assert {"robot_code", "health", "speed", "network", "temperature"} <= columns
    # 幂等：再次执行不应重复添加
    assert ensure_schema(engine) == []
