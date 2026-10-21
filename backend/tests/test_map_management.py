import io

import pytest
from PIL import Image
from sqlalchemy import select

from app.models import MapModel, MapPlace
from app.services.storage import LocalStorageService


@pytest.fixture()
def maps_client(client, login, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.storage._storage", LocalStorageService(str(tmp_path)))
    return client, {"Authorization": f"Bearer {login('operator', 'operator123')}"}


def png(width=160, height=90):
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def upload(client, headers, name="实验室地图"):
    response = client.post("/api/v1/maps/upload", params={"name": name}, content=png(), headers={**headers, "Content-Type": "image/png"})
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_image_and_places_persist_in_database(maps_client):
    from conftest import TestingSessionLocal
    client, headers = maps_client
    item = upload(client, headers)
    assert (item["width"], item["height"]) == (160, 90)
    assert item["metadata"]["navigation_ready"] is False
    place = client.post(f"/api/v1/maps/{item['id']}/places", headers=headers, json={"name": " 老师处 ", "x": 120, "y": 25, "yaw": 1.2})
    assert place.status_code == 201, place.text
    place = place.json()
    with TestingSessionLocal() as db:
        assert db.get(MapModel, item["id"]).image_key == item["image_key"]
        saved = db.get(MapPlace, place["id"])
        assert saved.name == "老师处" and saved.x == 120 and saved.map_id == item["id"]
    assert client.get(f"/api/v1/maps/{item['id']}/places", headers=headers).json() == [place]
    image = client.get(item["image_url"], headers=headers)
    assert image.status_code == 200 and image.headers["content-type"] == "image/png"
    assert Image.open(io.BytesIO(image.content)).size == (160, 90)
    renamed = client.put(f"/api/v1/maps/{item['id']}", headers=headers, json={"name": "实验室一层", "active": False})
    assert renamed.status_code == 200 and renamed.json()["active"] is False
    moved = client.put(f"/api/v1/maps/{item['id']}/places/{place['id']}", headers=headers, json={"name": "讲台旁", "x": 100, "y": 30})
    assert moved.status_code == 200 and moved.json()["x"] == 100
    assert client.delete(f"/api/v1/maps/{item['id']}/places/{place['id']}", headers=headers).status_code == 204
    assert client.get(f"/api/v1/maps/{item['id']}/places", headers=headers).json() == []


def test_delete_removes_map_places_and_owned_image(maps_client):
    from conftest import TestingSessionLocal
    from app.services.storage import get_storage
    client, headers = maps_client
    item = upload(client, headers)
    place = client.post(f"/api/v1/maps/{item['id']}/places", headers=headers, json={"name": "门口", "x": 10, "y": 85}).json()
    assert client.delete(f"/api/v1/maps/{item['id']}", headers=headers).status_code == 204
    with TestingSessionLocal() as db:
        assert db.get(MapModel, item["id"]) is None
        assert db.get(MapPlace, place["id"]) is None
    assert get_storage().get(item["image_key"]) is None
    assert client.get(item["image_url"], headers=headers).status_code == 404


def test_referenced_map_cannot_be_deleted(maps_client):
    client, headers = maps_client
    item = upload(client, headers)
    route = client.post("/api/v1/routes", headers=headers, json={"name": "有关联的路线", "map_id": item["id"]})
    assert route.status_code == 201
    response = client.delete(f"/api/v1/maps/{item['id']}", headers=headers)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "MAP_IN_USE"
    assert client.get(item["image_url"], headers=headers).status_code == 200


def test_place_bounds_duplicates_and_map_isolation(maps_client):
    client, headers = maps_client
    first, second = upload(client, headers), upload(client, headers)
    url = f"/api/v1/maps/{first['id']}/places"
    for payload in ({"name": "门", "x": 160, "y": 0}, {"name": "门", "x": -1, "y": 2}, {"name": " ", "x": 1, "y": 2}):
        assert client.post(url, headers=headers, json=payload).status_code == 422
    point = {"name": "老师处", "x": 100, "y": 20}
    place = client.post(url, headers=headers, json=point).json()
    assert client.post(url, headers=headers, json=point).status_code == 409
    other = f"/api/v1/maps/{second['id']}/places"
    assert client.get(other, headers=headers).json() == []
    assert client.post(other, headers=headers, json=point).status_code == 201
    assert client.put(f"{other}/{place['id']}", headers=headers, json=point).status_code == 404
    assert client.delete(f"{other}/{place['id']}", headers=headers).status_code == 404


@pytest.mark.parametrize("content,mime,status", [(b"invalid", "image/png", 400), (b"", "image/jpeg", 400), (b"<svg/>", "image/svg+xml", 415), (b"x" * (10 * 1024 * 1024 + 1), "image/png", 413)], ids=["corrupt", "empty", "unsupported", "too-large"])
def test_invalid_upload_is_rejected_without_database_record(maps_client, content, mime, status):
    from conftest import TestingSessionLocal
    client, headers = maps_client
    name = "无效上传测试"
    response = client.post("/api/v1/maps/upload", params={"name": name}, headers={**headers, "Content-Type": mime}, content=content)
    assert response.status_code == status
    with TestingSessionLocal() as db:
        assert db.scalar(select(MapModel.id).where(MapModel.name == name)) is None


def test_map_management_requires_permission(maps_client, login):
    client, headers = maps_client
    item = upload(client, headers)
    readonly = {"Authorization": f"Bearer {login('auditor', 'auditor123')}"}
    assert client.get("/api/v1/maps").status_code == 401
    assert client.get(item["image_url"], headers=readonly).status_code == 200
    assert client.get(item["image_url"]).status_code == 401
    assert client.post("/api/v1/maps/upload", params={"name": "拒绝"}, content=png(), headers={**readonly, "Content-Type": "image/png"}).status_code == 403
    assert client.post(f"/api/v1/maps/{item['id']}/places", headers=readonly, json={"name": "拒绝", "x": 2, "y": 3}).status_code == 403
    assert client.put(f"/api/v1/maps/{item['id']}", headers=readonly, json={"name": "拒绝"}).status_code == 403
    assert client.delete(f"/api/v1/maps/{item['id']}", headers=readonly).status_code == 403
