from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def execution_client(client, login, monkeypatch):
    runs, calls = {}, []
    async def request(self, path, payload=None, *, query=None):
        calls.append((path, payload, query))
        if path == "task" and payload:
            return runs.setdefault(payload["run_id"], {"run_id": payload["run_id"], "task_id": payload["task_id"],
                "kind": payload["kind"], "state": "waiting_load" if payload["kind"] == "delivery" else "prepared",
                "message": "等待确认", "goals": payload["waypoints"], "completed_stops": 0})
        if path == "task":
            return runs[query["run_id"]]
        if path == "task/action":
            value = runs[payload["run_id"]]
            transitions = {"loaded": "running", "handover": "completed", "cancel": "cancelled"}
            value.update(state=transitions[payload["action"]], message="已更新")
            return value
        raise AssertionError(path)
    monkeypatch.setattr("app.gateway.robot_gateway.RobotGateway.navigation_request", request)
    headers = {"Authorization": f"Bearer {login('operator', 'operator123')}"}
    body = {"run_id": str(uuid4()), "kind": "delivery", "name": "文件运输测试", "robot_id": "fixture-robot-1",
            "map_id": "fixture-map", "waypoints": [{"drawing": {"x": 50, "y": 50}, "yaw": 0}]}
    return client, headers, body, runs, calls


def test_business_task_tracks_matching_vehicle_results_and_blocks_manual_completion(execution_client):
    client, headers, body, runs, calls = execution_client
    result = client.post("/api/v1/navigation-tasks", headers=headers, json=body)
    assert result.status_code == 200, result.text
    value = result.json()
    ident, run = value["task_id"], value["run_id"]
    assert client.post("/api/v1/navigation-tasks", headers=headers, json=body).json()["task_id"] == ident
    assert client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()["execution"]["state"] == "waiting_load"
    record = client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()
    assert record["cargo_name"] == "文件" and record["start_location"] == "当前装件点" and record["end_location"] == "自选位置"
    assert client.post(f"/api/v1/missions/{ident}/actions", headers=headers, json={"action": "handover"}).status_code == 409
    assert client.put(f"/api/v1/mission-tasks/{ident}", headers=headers, json={"status": "completed"}).status_code == 409
    url = f"/api/v1/navigation-tasks/delivery/{ident}"
    assert client.post(url + "/action", headers=headers, json={"run_id": "wrong", "action": "loaded"}).status_code == 409
    assert client.post(url + "/action", headers=headers, json={"run_id": run, "action": "loaded"}).json()["state"] == "running"
    assert client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()["status"] == "transporting"
    runs[run].update(state="waiting_handover", completed_stops=1)
    assert client.get(url, headers=headers).json()["state"] == "waiting_handover"
    assert client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()["status"] != "completed"
    client.post(url + "/action", headers=headers, json={"run_id": run, "action": "handover"})
    assert client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()["status"] == "completed"


def test_lost_dispatch_response_is_retried_with_same_run(execution_client, monkeypatch):
    client, headers, body, runs, calls = execution_client
    original = __import__("app.gateway.robot_gateway", fromlist=["RobotGateway"]).RobotGateway.navigation_request
    async def lost(*args, **kwargs):
        raise httpx.ReadTimeout("reply lost")
    monkeypatch.setattr("app.gateway.robot_gateway.RobotGateway.navigation_request", lost)
    assert client.post("/api/v1/navigation-tasks", json=body, headers=headers).status_code == 502
    records = client.get("/api/v1/mission-tasks", headers=headers).json()
    pending = next(t for t in records if t["execution"] and t["execution"]["run_id"] == body["run_id"])
    assert pending["execution"]["state"] == "unconfirmed" and pending["status"] != "completed"
    monkeypatch.setattr("app.gateway.robot_gateway.RobotGateway.navigation_request", original)
    result = client.post(f"/api/v1/navigation-tasks/delivery/{pending['id']}/action", headers=headers,
                         json={"run_id": body["run_id"], "action": "retry"})
    assert result.status_code == 200 and result.json()["run_id"] == body["run_id"]


def test_execution_requires_permission_before_contacting_vehicle(execution_client, login):
    client, _, body, _, calls = execution_client
    readonly = {"Authorization": f"Bearer {login('auditor', 'auditor123')}"}
    assert client.post("/api/v1/navigation-tasks", json=body, headers=readonly).status_code == 403
    assert not calls


def test_stale_status_does_not_undo_cancel_and_completion_time_is_stable(execution_client):
    client, headers, body, runs, _ = execution_client
    initial = client.post("/api/v1/navigation-tasks", json=body, headers=headers).json()
    ident, run = initial["task_id"], initial["run_id"]
    url = f"/api/v1/navigation-tasks/delivery/{ident}"
    runs[run] = {**initial, "state": "completed", "version": 8}
    client.get(url, headers=headers)
    first = client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()
    client.get(url, headers=headers)
    again = client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()
    assert first["completed_at"] == again["completed_at"]
    runs[run] = {**initial, "state": "running", "version": 6}
    response = client.get(url, headers=headers)
    assert response.json()["state"] == "completed"
    assert client.get(f"/api/v1/mission-tasks/{ident}", headers=headers).json()["status"] == "completed"
