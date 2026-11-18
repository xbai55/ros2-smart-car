"""Offline business/vehicle API integration with a simulated controller and Nav2."""
import asyncio
import json
from pathlib import Path
import sys
import time
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from app.api.routes import navigation_tasks, resources
from app.models import AssistantExecution, AssistantPlan, AssistantSession, AssistantTurn, MapModel, MapPlace, Route, User
from app.services import assistant_execution, assistant_operations, assistant_tools, assistant_worker, control_leases
from conftest import TestingSessionLocal

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "ros2_ws/src/smart_car_decision"))
from test_navigation_tasks import runner
from smart_car_decision.control_lease import ControlLease
from smart_car_decision.web_api import create_app


@pytest.fixture
def simulated(client, login, monkeypatch, tmp_path):
    headers = {"Authorization": f"Bearer {login('operator', 'operator123')}"}
    task, node, wire = runner(tmp_path)
    task.require_lease = True
    wire.update(kind="patrol", run_id=str(uuid4()), return_to_start=False)
    wire["waypoints"].append({"name": "第二站", "drawing": {"x": 60, "y": 60}, "yaw": 0})
    ctl = ControlLease()
    node.mode, node.estop, node.speed, node.deny_acquire = "auto", False, 0., False
    calls = []
    token = "offline-test-machine-token-000123"
    monkeypatch.setenv("ROBOT_SERVICE_TOKEN", token)

    def update_ack():
        now = time.monotonic()
        stationary = node.mode == "stop" and not node.estop and node.speed < .01
        node.control_lease_ack = {**ctl.snapshot(now), "received_at": now, "mode": node.mode,
                                  "emergency_stop": node.estop, "stationary": stationary}
        node.stop_velocity_sample = (now, {"ok": True, "odom_age_sec": 0.,
                                           "linear_speed_xy": node.speed, "angular_speed": 0.})

    def publish(value):
        calls.append(value["op"])
        assert not node.estop
        if node.deny_acquire and value["op"] == "acquire":
            ctl.rejected_request_id = value["request_id"]
        elif ctl.update(value, time.monotonic(), node.mode == "stop" and node.speed < .01):
            if value.get("navigation_park"):
                node.mode = "stop"
        update_ack()
        if value.get("navigation_park"):
            asyncio.get_running_loop().call_later(.025, update_ack)

    node.publish_control_lease = publish
    app = create_app(node)
    binding = ("fixture-robot-1", "http://fixture")
    gateway = control_leases.get_robot_gateway(binding[1])
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def vehicle_client(timeout):
        update_ack()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                     headers={"X-InsightRover-Service-Token": token}) as api:
            yield api

    monkeypatch.setattr(gateway, "_client", vehicle_client)
    manager = control_leases.ControlLeaseManager()
    monkeypatch.setattr(navigation_tasks, "control_lease_manager", manager)
    monkeypatch.setattr(assistant_worker, "control_lease_manager", manager)
    for module in (navigation_tasks, assistant_worker, assistant_operations, assistant_execution, assistant_tools, resources):
        monkeypatch.setattr(module, "vehicle_binding", lambda db: binding)
    for module in (navigation_tasks, control_leases, assistant_worker):
        monkeypatch.setattr(module, "get_robot_gateway", lambda address: gateway)
    return client, headers, wire, node, calls, manager, binding, gateway


def wait_for(predicate):
    for _ in range(100):
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError("离线状态未推进")


@pytest.mark.parametrize("mode", ["auto", "manual", "stop"])
def test_patrol_parks_before_lease_and_runs_each_station_once(simulated, mode):
    client, headers, wire, node, calls, manager, binding, _ = simulated
    node.mode = mode
    payload = {**wire, "task_id": None, "robot_id": binding[0], "map_id": "fixture-map"}
    prepared = client.post("/api/v1/navigation-tasks", json=payload, headers=headers).json()
    assert prepared["state"] == "prepared", prepared
    url = f"/api/v1/navigation-tasks/patrol/{prepared['task_id']}"
    action = {"run_id": wire["run_id"], "action": "start"}
    result = client.post(url + "/action", json=action, headers=headers)
    assert result.status_code == 200, result.text
    assert client.post(url + "/action", json=action, headers=headers).status_code == 409
    assert calls == ["stop", "acquire"] and node.mode == "stop"
    wait_for(lambda: len(node.navigation.starts) == 1)
    for index in (1, 2):
        node.navigation.state["state"] = "succeeded"
        wait_for(lambda: node.navigation_tasks.snapshot()["completed_stops"] == index)
        if index == 1:
            wait_for(lambda: len(node.navigation.starts) == 2)
    assert client.get(url, headers=headers).json()["state"] == "completed"
    assert manager.current is None and calls[-1] == "release"
    assert len(node.navigation.starts) == 2


@pytest.mark.parametrize("fault", ["moving", "estop", "lease"])
def test_patrol_does_not_dispatch_when_start_is_rejected(simulated, fault):
    client, headers, wire, node, calls, _, binding, _ = simulated
    payload = {**wire, "task_id": None, "robot_id": binding[0], "map_id": "fixture-map"}
    prepared = client.post("/api/v1/navigation-tasks", json=payload, headers=headers).json()
    if fault == "moving":
        node.speed = .2
    elif fault == "estop":
        node.estop = True
    else:
        node.deny_acquire = True
    url = f"/api/v1/navigation-tasks/patrol/{prepared['task_id']}/action"
    result = client.post(url, json={"run_id": wire["run_id"], "action": "start"}, headers=headers)
    assert result.status_code == 409, result.text
    assert node.navigation_tasks.snapshot()["state"] == "prepared" and not node.navigation.starts
    assert ("acquire" in calls) == (fault == "lease")


@pytest.mark.parametrize(("action", "mode", "history"), [
    ("navigate", "auto", "failed"), ("navigate", "stop", "other_robot"), ("patrol", "auto", None),
    ("navigate", "auto", "running"), ("navigate", "auto", "offline"),
])
def test_agent_resolves_and_executes_saved_targets(simulated, monkeypatch, action, mode, history):
    client, _, wire, node, calls, manager, binding, gateway = simulated
    node.mode = mode
    # Map/resource version is a test sensor input. Name lookup and business route expansion are real.
    context = lambda *args: {"available": True, "telemetry": {"active_map_key": wire["map_key"]}}
    for module in (resources, assistant_tools, assistant_execution):
        monkeypatch.setattr(module.robot_context_service, "context", context)
    for module in (assistant_tools, assistant_execution):
        monkeypatch.setattr(module, "capability_snapshot", lambda *args: {
            "capabilities": {action: {"executable": True, "fingerprint": "offline"}}})
    request = gateway.navigation_request
    old_run, old_task = str(uuid4()), str(uuid4())

    async def resolve(path, payload=None, **kwargs):
        if path == "task" and (kwargs.get("query") or {}).get("run_id") == old_run:
            if history == "offline":
                raise httpx.ConnectError("offline")
            return {"run_id": old_run, "task_id": old_task, "kind": "patrol",
                    "state": history, "message": "车端前一次任务回执"}
        if path == "resolve-resources":
            return {key: wire[key] for key in ("map_key", "control_session_id", "calibration_matrix",
                                               "calibration_drawing")} | {
                "waypoints": payload["points"], "resource_version": "a" * 64}
        if path == "config":
            return {}
        return await request(path, payload, **kwargs)

    monkeypatch.setattr(resources, "get_robot_gateway", lambda address: gateway)
    monkeypatch.setattr(gateway, "navigation_request", resolve)
    worker = assistant_worker.AssistantWorker(TestingSessionLocal)
    assert worker.acquire_worker()

    async def submit():
        with TestingSessionLocal() as db:
            user = db.scalar(select(User).where(User.username == "operator"))
            map_id, place1, place2, route_id, session_id, turn_id = (str(uuid4()) for _ in range(6))
            db.add(MapModel(id=map_id, name="隔离地图", active=True, image_key="local-test", width=100, height=100))
            db.add_all([MapPlace(id=place1, map_id=map_id, name="test2", x=50, y=50),
                        MapPlace(id=place2, map_id=map_id, name="主机室", x=60, y=60)])
            db.add(Route(id=route_id, name="巡检路线", map_id=map_id, parameters=json.dumps({"place_ids": [place1, place2]})))
            db.add(AssistantSession(id=session_id, user_id=user.id))
            db.add(AssistantTurn(id=turn_id, session_id=session_id, client_id=str(uuid4()),
                                 prompt="前往 test2" if action == "navigate" else "沿已保存的巡检路线巡航"))
            db.commit()
            place = action == "navigate"
            found = await assistant_tools.read_tool("find_places" if place else "find_routes",
                assistant_tools.Keyword(keyword="test2" if place else "巡检路线"), db, user, binding)
            ref = next(ref for ref in found["items"] if ref["map_id"] == map_id)
            ref = {key: ref[key] for key in ("resource_id", "source", "map_id")}
            args = assistant_tools.Proposal(steps=[{"action": action, "place" if place else "route": ref}])
            scope = assistant_operations.current_turn.set({"turn_id": turn_id, "session_id": session_id})
            try:
                return await assistant_operations.run_tool("execute_plan", args, db, user, binding)
            finally:
                assistant_operations.current_turn.reset(scope)

    old_id = str(uuid4())
    if history:
        with TestingSessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == "admin"))
            robot_id = "fixture-robot-2" if history == "other_robot" else binding[0]
            plan_id, session_id = str(uuid4()), str(uuid4())
            db.add(AssistantSession(id=session_id, user_id=admin.id))
            db.add(AssistantPlan(id=plan_id, session_id=session_id, robot_id=robot_id, state="confirmed",
                                 content="{}", digest="0" * 64, expires_at=0))
            db.add(AssistantExecution(id=old_id, plan_id=plan_id, robot_id=robot_id, user_id=admin.id,
                                     state="running" if history in {"running", "other_robot"} else "cancel_requested",
                                     version=5, vehicle_address=binding[1], run_id=old_run,
                                     run_kind="patrol", task_id=old_task, message="现场测试授权失效，正在结束本次任务"))
            db.commit()

    response = client.portal.call(submit)
    if history in {"running", "offline"}:
        assert response["state"] == "rejected" and old_id in response["error"], response
        assert ("仍未结束" if history == "running" else "尚未核实") in response["error"]
        assert not calls and not node.navigation.starts
        with TestingSessionLocal() as db:
            assert db.get(AssistantExecution, old_id).version == 5
            db.delete(db.get(AssistantExecution, old_id))
            from app.models import AssistantWorkerLock
            db.delete(db.get(AssistantWorkerLock, 1))
            db.commit()
        return
    assert response["state"] == "accepted", response
    if history == "failed":
        with TestingSessionLocal() as db:
            old = db.get(AssistantExecution, old_id)
            assert (old.state, old.vehicle_state, old.version) == ("cancelled", "failed", 6)
    ident = response["execution"]["id"]
    client.portal.call(worker.tick)
    with TestingSessionLocal() as db:
        assert db.get(AssistantExecution, ident).state == "running"
    names = ["test2"] if action == "navigate" else ["test2", "主机室"]
    for index, name in enumerate(names, start=1):
        wait_for(lambda: len(node.navigation.starts) == index)
        assert node.navigation.plans[-1]["goal"]["name"] == name
        node.navigation.state["state"] = "succeeded"
    wait_for(lambda: node.navigation_tasks.snapshot()["state"] == "completed")
    client.portal.call(worker.tick)
    with TestingSessionLocal() as db:
        assert db.get(AssistantExecution, ident).state == "completed"
        if history == "other_robot":
            old = db.get(AssistantExecution, old_id)
            assert old.state == "running" and old.version == 5
            db.delete(old)
        from app.models import AssistantWorkerLock
        db.delete(db.get(AssistantWorkerLock, 1))
        db.commit()
    assert calls[:2] == ["stop", "acquire"] and manager.current is None



@pytest.mark.parametrize("same_user", [True, False])
def test_manual_lease_is_only_released_for_its_owner(simulated, same_user):
    client, headers, wire, node, calls, manager, binding, _ = simulated
    node.mode = "stop"
    with TestingSessionLocal() as db:
        owner = db.scalar(select(User).where(User.username == ("operator" if same_user else "admin"))).id

    async def take_manual():
        return await manager.acquire_for_run(binding, owner, "robots.control", str(uuid4()), purpose="manual")

    held = client.portal.call(take_manual)
    node.mode = "manual"
    calls.clear()
    payload = {**wire, "task_id": None, "robot_id": binding[0], "map_id": "fixture-map"}
    prepared = client.post("/api/v1/navigation-tasks", json=payload, headers=headers).json()
    url = f"/api/v1/navigation-tasks/patrol/{prepared['task_id']}/action"
    result = client.post(url, json={"run_id": wire["run_id"], "action": "start"}, headers=headers)
    if same_user:
        assert result.status_code == 200, result.text
        assert calls == ["release", "stop", "acquire"]
        cancelled = client.post(url, json={"run_id": wire["run_id"], "action": "cancel"}, headers=headers)
        assert cancelled.json()["state"] == "cancelled"
        assert manager.current is None and calls[-1] == "release"
        next_payload = {**payload, "run_id": str(uuid4())}
        next_run = client.post("/api/v1/navigation-tasks", json=next_payload, headers=headers).json()
        assert next_run["state"] == "prepared"
    else:
        assert result.status_code == 409 and calls == [] and manager.current is held
        assert not node.navigation.starts


def test_worker_finishes_version_five_cancellation_from_exact_vehicle_receipt(simulated):
    client, headers, wire, node, _, manager, binding, _ = simulated
    payload = {**wire, "task_id": None, "robot_id": binding[0], "map_id": "fixture-map"}
    prepared = client.post("/api/v1/navigation-tasks", json=payload, headers=headers).json()
    url = f"/api/v1/navigation-tasks/patrol/{prepared['task_id']}"
    result = client.post(url + "/action", json={"run_id": wire["run_id"], "action": "start"}, headers=headers)
    assert result.status_code == 200, result.text
    wait_for(lambda: bool(node.navigation.starts))
    node.navigation.state.update(state="failed", message="模拟车端执行失败")
    wait_for(lambda: node.navigation_tasks.snapshot()["state"] == "failed")
    ident, plan_id, session_id = (str(uuid4()) for _ in range(3))
    with TestingSessionLocal() as db:
        user = db.scalar(select(User).where(User.username == "operator"))
        db.add(AssistantSession(id=session_id, user_id=user.id))
        db.add(AssistantPlan(id=plan_id, session_id=session_id, robot_id=binding[0], state="confirmed",
                             content="{}", digest="0" * 64, expires_at=0))
        db.add(AssistantExecution(id=ident, plan_id=plan_id, robot_id=binding[0], user_id=user.id,
                                 state="cancel_requested", version=5, vehicle_address=binding[1],
                                 run_id=wire["run_id"], run_kind="patrol", task_id=prepared["task_id"]))
        db.commit()

    worker = assistant_worker.AssistantWorker(TestingSessionLocal)
    client.portal.call(worker.tick)
    with TestingSessionLocal() as db:
        row = db.get(AssistantExecution, ident)
        assert (row.state, row.vehicle_state, row.version) == ("cancelled", "failed", 6)
    assert manager.current is None
    assert client.get(url, headers=headers).json()["state"] == "failed"
