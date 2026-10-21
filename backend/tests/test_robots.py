def _auth(client, username, password):
    return client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    ).json()["access_token"]


def test_list_robots_returns_seeded(client, login):
    token = login("operator", "operator123")
    response = client.get("/api/v1/robots", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    names = {r["name"] for r in data}
    assert "Patrol-01" in names


def test_simulate_cannot_invent_status(client, login):
    control = login("operator", "operator123")
    robots = client.get(
        "/api/v1/robots", headers={"Authorization": f"Bearer {control}"}
    ).json()
    robot_id = robots[0]["id"]

    response = client.post(
        f"/api/v1/robots/{robot_id}/simulate",
        json={"status": "online", "mode": "patrol", "battery": 80.0, "pose": {"x": 1, "y": 2, "yaw": 0.5}},
        headers={"Authorization": f"Bearer {control}"},
    )
    assert response.status_code == 404


def test_activity_cannot_be_injected(client, login):
    control = login("operator", "operator123")
    robots = client.get(
        "/api/v1/robots", headers={"Authorization": f"Bearer {control}"}
    ).json()
    robot_id = robots[0]["id"]

    post = client.post(
        f"/api/v1/robots/{robot_id}/activity",
        json={"kind": "patrol", "title": "巡检开始", "body": "沿路线 A 行驶"},
        headers={"Authorization": f"Bearer {control}"},
    )
    assert post.status_code == 405

    activity = client.get(
        f"/api/v1/robots/{robot_id}/activity",
        headers={"Authorization": f"Bearer {control}"},
    ).json()
    assert not any(event["title"] == "巡检开始" for event in activity)