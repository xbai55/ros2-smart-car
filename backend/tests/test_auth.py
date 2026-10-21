def test_login_success(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["refresh_token"]
    assert data["token_type"] == "bearer"
    assert data["user"]["role"]["name"] == "admin"


def test_login_wrong_password(client):
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": "wrong"},
    )
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "AUTH_INVALID"


def test_me_with_token(client, login):
    token = login("admin", "admin123")
    response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["username"] == "admin"


def test_me_missing_token(client):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_refresh_returns_new_tokens(client):
    data = client.post(
        "/api/v1/auth/login",
        json={"username": "operator", "password": "operator123"},
    ).json()
    response = client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": data["refresh_token"]},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_register_creates_read_only_account(client):
    response = client.post("/api/v1/auth/register", json={
        "username": "student_preview", "password": "samplePass123",
        "display_name": "学生演示账号",
    })
    assert response.status_code == 201, response.text
    data = response.json()
    assert data["access_token"]
    assert data["user"]["role"]["name"] == "viewer"
    permission_names = {p["name"] for p in data["user"]["role"]["permissions"]}
    assert "robots.read" in permission_names
    assert "robots.control" not in permission_names
    headers = {"Authorization": f"Bearer {data['access_token']}"}
    assert client.get("/api/v1/robots", headers=headers).status_code == 200
    assert client.get("/api/v1/users", headers=headers).status_code == 403
    assert client.post("/api/v1/auth/register", json={
        "username": "student_preview", "password": "samplePass123",
    }).status_code == 409


def test_register_rejects_weak_inputs(client):
    response = client.post("/api/v1/auth/register", json={
        "username": "x", "password": "short",
    })
    assert response.status_code == 422
