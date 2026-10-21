import copy
import io
import json
from uuid import uuid4

from PIL import Image
import pytest

from app.services.map_optimization import optimize_snapshot
from test_slam_map_management import slam_client, payload


def grid():
    return {"session_id": "original", "header": {"frame_id": "map"}, "info": {
        "width": 12, "height": 12, "resolution": .05, "origin": {"x": -2, "y": 1, "yaw": .4}}, "data": [0] * 144}


def test_despeckle_preserves_geometry_parent_and_large_obstacles():
    source = grid()
    source["data"][5 * 12 + 5] = 100
    source["data"][9 * 12:9 * 12 + 4] = [100] * 4
    before = copy.deepcopy(source)
    result, changed = optimize_snapshot(source, [{"type": "despeckle", "max_cells": 2}])
    assert source == before and result["info"] == source["info"]
    assert changed == 1 and result["data"][65] == -1
    assert result["data"][108:112] == [100] * 4
    assert result["session_id"] != source["session_id"]


def test_wall_uses_image_y_and_small_segments_rasterize():
    source = grid()
    result, changed = optimize_snapshot(source, [{"type": "wall", "start": {"x": 1, "y": 1}, "end": {"x": 1.1, "y": 1.1}, "width_m": .02}])
    assert changed > 0 and result["data"][10 * 12 + 1] == 100
    assert result["data"][1 * 12 + 1] == 0
    with pytest.raises(ValueError):
        optimize_snapshot(source, [{"type": "wall", "start": {"x": 10 ** 400, "y": 0}, "end": {"x": 1, "y": 1}}])


def test_preview_then_derive_preserves_original_assets_and_retries(slam_client):
    client, headers, _ = slam_client
    original = client.post("/api/v1/maps/slam", json=payload(), headers=headers).json()
    before = client.get(original["image_url"], headers=headers).content
    body = {"request_id": str(uuid4()), "name": "清理版本", "operations": [{"type": "despeckle", "max_cells": 1}]}
    prefix = f"/api/v1/maps/{original['id']}"
    preview = client.post(prefix + "/optimization-preview", json=body, headers=headers)
    assert preview.status_code == 200 and preview.json()["preview_url"].startswith("data:image/png;base64,")
    child = client.post(prefix + "/derive", json=body, headers=headers)
    assert child.status_code == 201, child.text
    value = child.json()
    assert value["id"] != original["id"] and value["origin"] == original["origin"]
    assert value["metadata"]["parent_map_id"] == original["id"]
    assert value["metadata"]["session_id"] != original["metadata"]["session_id"]
    assert client.get(original["image_url"], headers=headers).content == before
    assert client.post(prefix + "/derive", json=body, headers=headers).json()["id"] == value["id"]
    assert client.get(f"/api/v1/maps/{value['id']}/files/grid", headers=headers).json()["info"] == client.get(prefix + "/files/grid", headers=headers).json()["info"]


def test_optimization_rejects_readonly_and_unsupported_operations(slam_client, login):
    client, headers, _ = slam_client
    original = client.post("/api/v1/maps/slam", json=payload(), headers=headers).json()
    readonly = {"Authorization": f"Bearer {login('auditor', 'auditor123')}"}
    body = {"request_id": str(uuid4()), "name": "bad", "operations": [{"type": "erase_everything"}]}
    url = f"/api/v1/maps/{original['id']}/derive"
    assert client.post(url, json=body, headers=readonly).status_code == 403
    assert client.post(url, json=body, headers=headers).status_code == 422
