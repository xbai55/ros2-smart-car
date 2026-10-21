def test_auditor_can_read_robots(client, login):
    token = login("auditor", "auditor123")
    response = client.get("/api/v1/robots", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200


def test_auditor_forbidden_from_users(client, login):
    token = login("auditor", "auditor123")
    response = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"


def test_admin_can_list_users(client, login):
    token = login("admin", "admin123")
    response = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()}
    assert "auditor" in usernames