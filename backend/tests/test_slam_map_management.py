import io
import json
from uuid import uuid4

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.models import MapModel
from app.services.storage import LocalStorageService, get_storage


def snapshot():
    return {"session_id": "slam-session", "revision": 7, "header": {"frame_id": "map"},
            "info": {"width": 3, "height": 2, "resolution": .05,
                     "origin": {"x": -1.2, "y": 2.3, "yaw": .4}}, "data": [0, -1, 100, 50, 65, -1]}


@pytest.fixture
def slam_client(client, login, tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.storage._storage", LocalStorageService(str(tmp_path)))
    calls = []
    async def export(_self):
        calls.append(True)
        return {"ok": True, "snapshot": snapshot(), "yaml_path": "/car/map.yaml", "pgm_path": "/car/map.pgm"}
    monkeypatch.setattr("app.gateway.robot_gateway.RobotGateway.save_slam_map", export)
    headers = {"Authorization": f"Bearer {login('operator', 'operator123')}"}
    return client, headers, calls


def payload():
    return {"request_id": str(uuid4()), "robot_id": "fixture-robot-1", "name": "真实 SLAM 地图", "floor": "1F"}


def test_slam_save_persists_preview_geometry_grid_and_idempotent_record(slam_client):
    from conftest import TestingSessionLocal
    client, headers, calls = slam_client
    body = payload()
    first = client.post('/api/v1/maps/slam', headers=headers, json=body)
    assert first.status_code == 201, first.text
    item = first.json()
    again = client.post('/api/v1/maps/slam', headers=headers, json=body)
    assert again.json()['id'] == item['id'] and len(calls) == 1
    assert item['origin'] == [-1.2, 2.3, .4] and item['resolution'] == .05
    assert item['metadata']['source'] == 'slam' and item['metadata']['navigation_ready'] is False
    with TestingSessionLocal() as db:
        assert db.get(MapModel, item['id']).width == 3
    picture = client.get(item['image_url'], headers=headers)
    image = Image.open(io.BytesIO(picture.content))
    assert image.size == (3, 2)
    assert list(image.getdata()) == [205, 0, 205, 254, 205, 0]
    grid = client.get(f"/api/v1/maps/{item['id']}/files/grid", headers=headers)
    assert grid.json()['data'] == snapshot()['data']
    assert client.get(f"/api/v1/maps/{item['id']}/files/yaml", headers=headers).text.count('0.05') == 1
    assert client.get(f"/api/v1/maps/{item['id']}/files/pgm", headers=headers).content.startswith(b'P5\n3 2\n255\n')


def test_selection_persists_and_selected_map_cannot_be_deleted(slam_client):
    client, headers, _ = slam_client
    item = client.post('/api/v1/maps/slam', headers=headers, json=payload()).json()
    assert client.post(f"/api/v1/maps/{item['id']}/select", headers=headers).json()['map_id'] == item['id']
    assert client.get('/api/v1/maps/selection', headers=headers).json()['map_id'] == item['id']
    assert client.delete(f"/api/v1/maps/{item['id']}", headers=headers).status_code == 409
    assert client.put(f"/api/v1/maps/{item['id']}", headers=headers, json={'active':False}).status_code == 409
    assert client.delete('/api/v1/maps/selection', headers=headers).status_code == 204
    assert client.get('/api/v1/maps/selection', headers=headers).json()['map_id'] is None
    assert client.get('/api/v1/maps/selection', headers=headers).json()['initialized'] is True
    keys = list(item['metadata']['assets'].values())
    assert client.delete(f"/api/v1/maps/{item['id']}", headers=headers).status_code == 204
    assert all(get_storage().get(key) is None for key in keys)


def test_vehicle_failure_does_not_create_a_map(slam_client, monkeypatch):
    from conftest import TestingSessionLocal
    client, headers, _ = slam_client
    async def broken(_self): raise httpx.ConnectError('vehicle offline')
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.save_slam_map', broken)
    body = {**payload(), 'name': 'offline-save-test'}
    result = client.post('/api/v1/maps/slam', headers=headers, json=body)
    assert result.status_code == 502
    with TestingSessionLocal() as db:
        assert db.scalar(select(MapModel).where(MapModel.name == body['name'])) is None


def test_invalid_grid_and_storage_failure_do_not_leave_records_or_files(slam_client, monkeypatch):
    client, headers, _ = slam_client
    async def invalid(_self): return {'ok': True, 'snapshot': {**snapshot(), 'data': []}}
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.save_slam_map', invalid)
    assert client.post('/api/v1/maps/slam', headers=headers, json=payload()).status_code == 502
    async def valid(_self): return {'ok': True, 'snapshot': snapshot()}
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.save_slam_map', valid)
    storage = get_storage()
    original = storage.put
    def partial(key, data, **kwargs):
        original(key, data, **kwargs)
        if key.endswith('map.yaml'): raise OSError('disk full')
    monkeypatch.setattr(storage, 'put', partial)
    assert client.post('/api/v1/maps/slam', headers=headers, json=payload()).status_code == 500
    assert not [p for p in storage.root.rglob('*') if p.is_file()]


def test_slam_save_and_selection_require_management_permission(slam_client, login):
    client, headers, calls = slam_client
    readonly = {'Authorization': f"Bearer {login('auditor', 'auditor123')}"}
    assert client.post('/api/v1/maps/slam', json=payload()).status_code == 401
    assert client.post('/api/v1/maps/slam', json=payload(), headers=readonly).status_code == 403
    assert calls == []
    item = client.post('/api/v1/maps/slam', json=payload(), headers=headers).json()
    assert client.post(f"/api/v1/maps/{item['id']}/select", headers=readonly).status_code == 403
    assert client.get(f"/api/v1/maps/{item['id']}/files/grid", headers=readonly).status_code == 200
    assert client.get(f"/api/v1/maps/{item['id']}/files/grid").status_code == 401
    client.put(f"/api/v1/maps/{item['id']}", headers=headers, json={'active': False})
    assert client.post(f"/api/v1/maps/{item['id']}/select", headers=headers).status_code == 409
