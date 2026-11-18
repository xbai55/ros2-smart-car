import asyncio
import hashlib
import json
import time
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.models import AssistantExecution, AssistantPlan, AssistantSession, AssistantWorkerLock, User
from app.services import assistant_worker
from app.services.assistant_execution import request_cancellation
from conftest import TestingSessionLocal


@pytest.fixture
def queue(monkeypatch, seeded_db):
    robot_id = "fixture-robot-1"
    binding = (robot_id, "http://fixture")
    monkeypatch.setattr(assistant_worker, "vehicle_binding", lambda db: binding)
    worker = assistant_worker.AssistantWorker(TestingSessionLocal)
    assert worker.acquire_worker()
    records, actions, execution_ids = {}, [], []
    from types import SimpleNamespace
    controls = SimpleNamespace(stop_during_create=False, lost_response=False, lock={})

    def load(ident):
        with TestingSessionLocal() as db:
            row = db.get(AssistantExecution, ident)
            return {key: getattr(row, key) for key in ("state", "version", "run_id", "phase", "vehicle_state", "step_index")}

    def add(*actions):
        with TestingSessionLocal() as db:
            user = db.scalar(select(User).where(User.username == "operator"))
            session_id, plan_id, ident = (str(uuid4()) for _ in range(3))
            db.add(AssistantSession(id=session_id, user_id=user.id))
            steps = []
            for action in actions:
                names = ("A", "B") if action == "deliver" else () if action == "observe_target" else ("C",)
                refs = [{"reference": {"source": "business_place", "map_id": "fixture-map"}, "name": name} for name in names]
                steps.append({"action": action, "resources": refs, "cargo": "文件", "target": "服务器"})
            content = json.dumps({"steps": steps, "robot_id": robot_id})
            db.add(AssistantPlan(id=plan_id, session_id=session_id, robot_id=robot_id, state="confirmed",
                                 content=content, digest=hashlib.sha256(content.encode()).hexdigest(),
                                 expires_at=int(time.time()) + 300))
            db.add(AssistantExecution(id=ident, plan_id=plan_id, user_id=user.id, robot_id=robot_id))
            db.commit()
            execution_ids.append(ident)
            return ident

    async def validate(db, user, robot_id, steps):
        return binding, [[{"map_key": "map", "control_session_id": "session", "calibration_matrix": [],
                           "calibration_drawing": {}, "waypoints": [{"name": ref["name"]}]}
                          for ref in step["resources"]] for step in steps]

    async def create(payload, db, user):
        actions.append(("create", payload["kind"], payload["waypoints"][0]["name"]))
        record = {"run_id": payload["run_id"],
                  "state": "waiting_load" if payload["kind"] == "delivery" else "prepared"}
        records[payload["run_id"]] = record
        if controls.stop_during_create:
            with TestingSessionLocal() as other:
                request_cancellation(other, robot_id=robot_id)
                other.commit()
        if controls.lost_response:
            raise TimeoutError()
        return record

    async def action(kind, task_id, payload, db, user, *, guard):
        guard()
        actions.append((payload["action"], kind))
        record = records[payload["run_id"]]
        record["state"] = "completed" if payload["action"] == "handover" else "running"
        return record

    async def lookup(db, row, user):
        return records[row.run_id]

    async def search(db, binding, user, operation, wire, *, guard):
        guard()
        actions.append(("search", operation))
        run_id = wire["run_id"]
        result = {"run_id": run_id, "state": "searching" if operation == "start" else "finished"}
        records[run_id] = result
        return result

    monkeypatch.setattr(assistant_worker, "validate_steps", validate)
    monkeypatch.setattr(assistant_worker, "lookup_run", lookup)
    monkeypatch.setattr(assistant_worker, "execute_search", search)
    monkeypatch.setattr(assistant_worker, "robot_context_service", SimpleNamespace(context=lambda *args: {
        "available": True, "telemetry": {"search_control": controls.lock}}))
    monkeypatch.setattr(assistant_worker.navigation_tasks, "create_execution", create)
    monkeypatch.setattr(assistant_worker.navigation_tasks, "apply_execution_action", action)
    yield SimpleNamespace(worker=worker, add=add, load=load, records=records, actions=actions, controls=controls)
    with TestingSessionLocal() as db:
        for ident in execution_ids:
            db.delete(db.get(AssistantExecution, ident))
        db.delete(db.get(AssistantWorkerLock, 1))
        db.commit()


def test_delivery_waits_for_each_human_action(client, login, queue):
    ident = queue.add("deliver")
    tick = lambda: asyncio.run(queue.worker.tick())
    headers = {"Authorization": "Bearer " + login("operator", "operator123")}
    path = f"/api/v1/assistant/executions/{ident}/actions"
    tick()
    pickup = queue.load(ident)
    assert queue.actions == [("create", "patrol", "A"), ("start", "patrol")]
    queue.records[pickup["run_id"]]["state"] = "completed"
    tick()
    tick()
    delivery = queue.load(ident)
    assert delivery["state"] == "waiting_human" and delivery["vehicle_state"] == "waiting_load"
    assert queue.actions[-1] == ("create", "delivery", "B")
    assert client.post(path, headers=headers, json={"action": "handover", "version": delivery["version"]}).status_code == 409
    assert client.post(path, headers=headers, json={"action": "loaded", "version": delivery["version"]}).status_code == 200
    tick()
    queue.records[delivery["run_id"]]["state"] = "waiting_handover"
    tick()
    handover = queue.load(ident)
    assert handover["state"] == "waiting_human" and handover["vehicle_state"] == "waiting_handover"
    assert client.post(path, headers=headers, json={"action": "handover", "version": handover["version"]}).status_code == 200
    tick()
    assert queue.load(ident)["state"] == "completed"


def test_stop_during_prepare_prevents_late_navigation_start(queue):
    ident = queue.add("navigate")
    queue.controls.stop_during_create = True
    asyncio.run(queue.worker.tick())
    assert queue.load(ident)["state"] == "cancel_requested"
    assert queue.actions == [("create", "patrol", "C")]


def test_restart_reconciles_without_advancing(queue):
    ident = queue.add("navigate", "navigate")
    asyncio.run(queue.worker.tick())
    record = queue.load(ident)
    queue.worker.recover()
    queue.records[record["run_id"]]["state"] = "completed"
    asyncio.run(queue.worker.tick())
    current = queue.load(ident)
    assert current["state"] == "paused" and current["vehicle_state"] == "completed"
    assert current["step_index"] == 0


def test_lost_prepare_response_is_reconciled_without_retry(queue):
    ident = queue.add("navigate")
    queue.controls.lost_response = True
    asyncio.run(queue.worker.tick())
    assert queue.load(ident)["state"] == "unconfirmed"
    asyncio.run(queue.worker.tick())
    assert queue.load(ident)["state"] == "paused"
    assert queue.load(ident)["vehicle_state"] == "prepared"
    assert queue.actions == [("create", "patrol", "C")]


def test_search_requires_human_decision_and_released_lock_before_next_step(client, login, queue):
    ident = queue.add("observe_target", "navigate")
    tick = lambda: asyncio.run(queue.worker.tick())
    tick()
    run_id = queue.load(ident)["run_id"]
    queue.records[run_id]["state"] = "found"
    tick()
    waiting = queue.load(ident)
    tick()
    assert waiting["state"] == "waiting_human" and queue.actions == [("search", "start")]
    headers = {"Authorization": "Bearer " + login("operator", "operator123")}
    response = client.post(f"/api/v1/assistant/executions/{ident}/actions", headers=headers,
                           json={"action": "continue_plan", "version": waiting["version"]})
    assert response.status_code == 200, response.text
    tick()
    assert queue.load(ident)["step_index"] == 0
    assert queue.actions == [("search", "start"), ("search", "action")]
    queue.controls.lock = {"run_id": run_id, "active": False}
    tick()
    assert queue.load(ident)["step_index"] == 1
    tick()
    assert queue.actions[-1] == ("start", "patrol")
