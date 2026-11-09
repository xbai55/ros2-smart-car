import hashlib
import json
import time
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.api.routes import assistant
from app.db.base import Base
from app.db.migrate import ensure_schema
from app.models import AssistantPlan, AssistantSession, Role, User
from app.services import assistant_execution, assistant_tools


def headers(login, username):
    return {"Authorization": "Bearer " + login(username, username + "123")}


def test_assistant_sessions_and_tool_boundary(client, login, monkeypatch):
    class Model:
        calls = 0

        async def complete(self, messages, tools):
            self.calls += 1
            assert "command" not in {item["function"]["name"] for item in tools}
            if self.calls == 1:
                return {"tool_calls": [{"id": "call-1", "function": {
                    "name": "command", "arguments": '{"command":"forward"}'}}]}
            assert "error" in json.loads(messages[-1]["content"])
            return {"content": "当前无法确认车辆位置。"}

    model = Model()
    monkeypatch.setattr(assistant, "configured_provider", lambda: model)
    operator = headers(login, "operator")
    auditor = headers(login, "auditor")
    admin = headers(login, "admin")
    root = "/api/v1/assistant"
    assert client.get(root + "/sessions").status_code == 401
    assert client.post(root + "/sessions", headers=auditor).status_code == 403
    assert client.put(root + "/settings", headers=operator, json={"enabled": True}).status_code == 403
    assert client.put(root + "/settings", headers=admin, json={"enabled": True}).status_code == 200
    try:
        session = client.post(root + "/sessions", headers=operator).json()["id"]
        path = f"{root}/sessions/{session}/messages"
        assert client.get(path, headers=auditor).status_code == 404
        message = {"client_id": str(uuid4()), "text": "现在在哪里？"}
        first = client.post(path, headers=operator, json=message)
        assert first.status_code == 200, first.text
        assert first.json()["reply"] == {"text": "当前无法确认车辆位置。", "plan": None}
        assert client.post(path, headers=operator, json=message).json() == first.json()
        assert client.post(path, headers=operator, json={**message, "text": "另一条消息"}).status_code == 409
        assert client.get(path, headers=operator).json()["items"] == [first.json()]
        assert model.calls == 2
    finally:
        assert client.put(root + "/settings", headers=admin, json={"enabled": False}).status_code == 200


def test_draft_requires_real_resource_and_carries_its_version(client, login, monkeypatch):
    class Model:
        async def complete(self, messages, tools):
            if messages[-1]["role"] == "tool" and messages[-1]["tool_call_id"] == "draft":
                assert json.loads(messages[-1]["content"])["state"] == "draft"
                return {"content": "草案已生成。"}
            if messages[-1]["role"] != "tool":
                return {"tool_calls": [{"id": "lookup", "function": {
                    "name": "find_places", "arguments": '{"keyword":"实验台"}'}}]}
            return {"tool_calls": [{"id": "draft", "function": {"name": "propose_plan", "arguments": json.dumps({
                "steps": [{"action": "navigate", "place": {
                    "source": "business_place", "resource_id": "fixture-place", "map_id": "fixture-map"}}]
            })}}]}

    async def resolve(payload, db, user):
        assert payload.references[0].resource_id == "fixture-place"
        return {"resource_version": "v1", "map_key": "active-map", "waypoints": [{"name": "实验台"}]}

    async def find(*args):
        return {"items": [{"source": "business_place", "resource_id": "fixture-place", "map_id": "fixture-map"}]}

    monkeypatch.setattr(assistant, "configured_provider", Model)
    monkeypatch.setattr(assistant_tools.resources, "resolve", resolve)
    monkeypatch.setattr(assistant_tools.resources, "find_places", find)
    monkeypatch.setattr(assistant_tools, "vehicle_binding", lambda db: ("fixture-robot-1", ""))
    admin, operator = headers(login, "admin"), headers(login, "operator")
    root = "/api/v1/assistant"
    client.put(root + "/settings", headers=admin, json={"enabled": True})
    try:
        session = client.post(root + "/sessions", headers=operator).json()["id"]
        result = client.post(f"{root}/sessions/{session}/messages", headers=operator,
                             json={"client_id": str(uuid4()), "text": "去实验台"})
        assert result.status_code == 200, result.text
        plan = result.json()["reply"]["plan"]
        assert plan["state"] == "draft"
        assert plan["steps"][0]["resources"][0]["resource_version"] == "v1"
        assert not plan["steps"][0]["capability"]["executable"]
        assert client.get(f"{root}/plans/{plan['id']}", headers=operator).json() == plan
        assert client.get(f"{root}/plans/{plan['id']}", headers=admin).status_code == 404
    finally:
        client.put(root + "/settings", headers=admin, json={"enabled": False})


def test_unobserved_reference_is_rejected_even_with_lookup_in_same_batch(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    reference = {"source": "business_place", "resource_id": "real-place", "map_id": "real-map"}
    calls = []

    async def read(*args):
        return {"items": [reference]}

    async def resolve(*args):
        calls.append("resolve")
        raise AssertionError("Unobserved references must not reach resource resolution")

    class Model:
        async def complete(self, messages, tools):
            if messages[-1]["role"] == "tool":
                assert "error" in json.loads(messages[-1]["content"])
                return {"content": "请先查询地点，再确认草案。"}
            return {"tool_calls": [
                {"id": "lookup", "function": {"name": "find_places", "arguments": '{"keyword":"实验台"}'}},
                {"id": "guess", "function": {"name": "propose_plan", "arguments": json.dumps({
                    "steps": [{"action": "navigate", "place": reference}]})}},
            ]}

    monkeypatch.setattr(assistant_tools, "vehicle_binding", lambda db: ("r", ""))
    monkeypatch.setattr(assistant_tools, "read_tool", read)
    monkeypatch.setattr(assistant_tools.resources, "resolve", resolve)
    _, plan, _ = asyncio.run(assistant_tools.ask(Model(), None, SimpleNamespace(), [], "去实验台"))
    assert plan is None and not calls


def test_assistant_permission_migration_does_not_restore_revoked_permission():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Role(id="operator", name="operator"))
        db.commit()
    ensure_schema(engine)
    with Session(engine) as db:
        operator = db.get(Role, "operator")
        assert {permission.name for permission in operator.permissions} == {"assistant.read", "assistant.use", "diagnostics.read"}
        operator.permissions = [permission for permission in operator.permissions if permission.name != "assistant.use"]
        db.commit()
    ensure_schema(engine)
    with Session(engine) as db:
        assert {permission.name for permission in db.get(Role, "operator").permissions} == {"assistant.read", "diagnostics.read"}


def test_confirmation_is_idempotent_and_owner_scoped(client, login, monkeypatch, seeded_db):
    owner = seeded_db.scalar(select(User).where(User.username == "operator"))
    session = AssistantSession(id=str(uuid4()), user_id=owner.id)
    seeded_db.add(session)
    robot_id = "fixture-robot-1"
    resource = {"reference": {"source": "business_place", "resource_id": "desk", "map_id": "fixture-map"},
                "resource_version": "a" * 64, "map_key": "test-map"}
    content = json.dumps({"robot_id": robot_id, "steps": [{
        "action": "navigate", "resources": [resource], "capability": {"fingerprint": "build-1"},
    }]})
    digest = hashlib.sha256(content.encode()).hexdigest()
    plan = AssistantPlan(id=str(uuid4()), session_id=session.id, robot_id=robot_id, content=content,
                         digest=digest, expires_at=int(time.time()) + 300)
    seeded_db.add(plan)
    seeded_db.commit()
    binding = (robot_id, "http://mock")
    monkeypatch.setattr(assistant_execution, "vehicle_binding", lambda db: binding)
    monkeypatch.setattr(assistant_execution, "capability_snapshot", lambda *args: {
        "capabilities": {"navigate": {"executable": True, "fingerprint": "build-1"}}})
    resource_version = ["b" * 64]
    calls = []

    async def resolve(payload, db, user):
        calls.append(payload.expected_version)
        return {"map_key": "test-map", "resource_version": resource_version[0]}

    monkeypatch.setattr(assistant_execution.resources, "resolve", resolve)
    path = f"/api/v1/assistant/plans/{plan.id}/confirm"
    confirm = {"version": 1, "digest": digest}
    operator, admin = headers(login, "operator"), headers(login, "admin")
    assert client.post(path, headers=admin, json=confirm).status_code == 404
    assert client.post(path, headers=operator, json={**confirm, "version": 2}).status_code == 409
    assert client.post(path, headers=operator, json=confirm).status_code == 409
    resource_version[0] = resource["resource_version"]
    first = client.post(path, headers=operator, json=confirm)
    assert first.status_code == 200, first.text
    assert first.json()["state"] == "queued"
    assert client.post(path, headers=operator, json=confirm).json() == first.json()
    assert calls == ["a" * 64] * 2
    execution = f"/api/v1/assistant/executions/{first.json()['id']}"
    assert client.get(execution, headers=admin).status_code == 404
    cancelled = client.post(execution + "/actions", headers=operator, json={"action": "cancel"})
    assert cancelled.json()["state"] == "cancelled"
    assert client.get(execution, headers=operator).json()["version"] == 2
    assert client.post(path, headers=operator, json=confirm).json() == cancelled.json()

    from conftest import TestingSessionLocal
    monkeypatch.setattr(assistant, "SessionLocal", TestingSessionLocal)
    batch = assistant.event_batch(operator["Authorization"], 0)
    relevant = [(cursor, value) for cursor, value in batch if value["payload"].get("plan_id") == plan.id]
    assert [value["kind"] for _, value in relevant] == ["execution.queued", "execution.cancelled"]
    assert assistant.event_batch(operator["Authorization"], relevant[-1][0]) == []
    assert assistant.event_batch(admin["Authorization"], 0) == []
