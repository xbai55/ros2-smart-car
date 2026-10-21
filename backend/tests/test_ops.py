def _auth(client, username, password):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    ).json()["access_token"]


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_map_route_patrol_flow(client, login):
    token = login("operator", "operator123")
    maps = client.get("/api/v1/maps", headers=_headers(token)).json()
    assert maps
    route = client.post(
        "/api/v1/routes",
        json={"name": "测试路线", "map_id": maps[0]["id"], "points": [{"x": 1, "y": 2}]},
        headers=_headers(token),
    ).json()
    assert route["name"] == "测试路线"

    robots = client.get("/api/v1/robots", headers=_headers(token)).json()
    patrol = client.post(
        "/api/v1/patrols",
        json={"name": "夜班巡检", "robot_id": robots[0]["id"], "route_id": route["id"]},
        headers=_headers(token),
    ).json()
    assert patrol["status"] == "pending"
    started = client.post(
        f"/api/v1/patrols/{patrol['id']}/actions",
        json={"action": "start"},
        headers=_headers(token),
    ).json()
    assert started["status"] == "running"
    completed = client.post(
        f"/api/v1/patrols/{patrol['id']}/actions",
        json={"action": "complete"},
        headers=_headers(token),
    ).json()
    assert completed["status"] == "completed"


def test_mission_flow(client, login):
    token = login("operator", "operator123")
    robots = client.get("/api/v1/robots", headers=_headers(token)).json()
    mission = client.post(
        "/api/v1/missions",
        json={
            "name": "送文件到实验室",
            "robot_id": robots[0]["id"],
            "cargo": "档案袋",
            "origin": "A 栋前台",
            "destination": "实验室 302",
            "pickup_code": "1234",
        },
        headers=_headers(token),
    ).json()
    assert mission["status"] == "queued"
    dispatched = client.post(
        f"/api/v1/missions/{mission['id']}/actions",
        json={"action": "dispatch"},
        headers=_headers(token),
    ).json()
    assert dispatched["status"] == "dispatched"
    picked = client.post(
        f"/api/v1/missions/{mission['id']}/actions",
        json={"action": "pickup"},
        headers=_headers(token),
    ).json()
    assert picked["status"] == "transporting"
    done = client.post(
        f"/api/v1/missions/{mission['id']}/actions",
        json={"action": "handover"},
        headers=_headers(token),
    ).json()
    assert done["status"] == "completed"


def test_incident_and_notification(client, login):
    token = login("operator", "operator123")
    robots = client.get("/api/v1/robots", headers=_headers(token)).json()
    incident = client.post(
        "/api/v1/incidents",
        json={
            "type": "smoke_fire",
            "severity": "critical",
            "robot_id": robots[0]["id"],
            "title": "检测到烟雾",
            "description": "巡检点发现烟雾",
        },
        headers=_headers(token),
    ).json()
    assert incident["status"] == "open"
    resolved = client.post(
        f"/api/v1/incidents/{incident['id']}/actions",
        json={"action": "confirm"},
        headers=_headers(token),
    ).json()
    assert resolved["status"] == "acknowledged"

    notes = client.get("/api/v1/notifications", headers=_headers(token)).json()
    assert any(n["ref_id"] == incident["id"] for n in notes)


def test_analytics_and_audit(client, login):
    token = login("admin", "admin123")
    summary = client.get("/api/v1/analytics/summary", headers=_headers(token)).json()
    assert {"total", "completed", "completion_rate"} <= set(summary["patrol"])
    logs = client.get("/api/v1/audit-logs", headers=_headers(token)).json()
    assert any(log["resource"] in {"patrol", "mission", "incident"} for log in logs)


def test_auditor_forbidden_from_ops_write(client, login):
    token = login("auditor", "auditor123")
    response = client.post(
        "/api/v1/patrols",
        json={"name": "越权巡检"},
        headers=_headers(token),
    )
    assert response.status_code == 403
