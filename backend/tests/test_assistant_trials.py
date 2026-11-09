import hashlib
import json
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.models import AssistantPlan, AssistantSession, AssistantTrialAuthorization, CapabilityAcceptance, User
from app.services import assistant_execution, assistant_trials


def test_single_plan_trial_is_admin_scoped_consumed_once_and_not_acceptance(client, login, seeded_db, monkeypatch):
    robot_id = "fixture-robot-1"
    binding = (robot_id, "http://field-test")
    capability = {"supported": True, "ready": True, "accepted": False, "executable": False,
                  "fingerprint": "a"*64, "reasons": ["vehicle_acceptance_required"]}
    for module in (assistant_execution, assistant_trials):
        monkeypatch.setattr(module, "vehicle_binding", lambda db: binding)
        monkeypatch.setattr(module, "capability_snapshot", lambda db, ctx: {"capabilities":{"observe_target":capability}})
    monkeypatch.setattr(assistant_trials, "robot_context_service", SimpleNamespace(context=lambda *args: {}))
    monkeypatch.setattr(assistant_execution, "robot_context_service", SimpleNamespace(context=lambda *args: {}))
    admin = seeded_db.scalar(select(User).where(User.username == "admin"))
    session = AssistantSession(id=str(uuid4()), user_id=admin.id)
    content = json.dumps({"robot_id":robot_id,"steps":[{
        "action":"observe_target","target":"瓶子","resources":[],"capability":capability}]})
    plan = AssistantPlan(id=str(uuid4()),session_id=session.id,robot_id=robot_id,state="draft",
        content=content,digest=hashlib.sha256(content.encode()).hexdigest(),expires_at=int(time.time())+300)
    seeded_db.add_all([session,plan]);seeded_db.commit()
    headers={"Authorization":"Bearer "+login("admin","admin123")}
    operator={"Authorization":"Bearer "+login("operator","operator123")}
    base="/api/v1/assistant/plans/"+plan.id
    wire={"version":plan.version,"digest":plan.digest}
    original_count=len(seeded_db.scalars(select(CapabilityAcceptance)).all())
    assert client.post(base+"/confirm",headers=headers,json=wire).status_code==409
    assert client.post(base+"/trial-authorize",headers=operator,json=wire).status_code==403
    assert client.post(base+"/trial-authorize",headers=headers,json={**wire,"digest":"b"*64}).status_code==409
    assert client.post(base+"/trial-authorize",headers=headers,json=wire).status_code==200
    assert client.post(base+"/trial-authorize",headers=headers,json=wire).status_code==200
    first=client.post(base+"/confirm",headers=headers,json=wire)
    assert first.status_code==200,first.text
    assert client.post(base+"/confirm",headers=headers,json=wire).json()["id"]==first.json()["id"]
    seeded_db.expire_all()
    grant=seeded_db.get(AssistantTrialAuthorization,plan.id)
    assert grant.execution_id==first.json()["id"]
    assert len(seeded_db.scalars(select(CapabilityAcceptance)).all())==original_count
    assert client.post(base+"/trial-authorize",headers=headers,json=wire).status_code==409
    # Runtime checks must bind to the exact execution and expire independently.
    with pytest.raises(HTTPException):
        assistant_trials.require_trial(seeded_db,admin,plan.id,"observe_target","a"*64,"other-execution")
    grant.expires_at=int(time.time())-1;seeded_db.commit()
    with pytest.raises(HTTPException):
        assistant_trials.require_trial(seeded_db,admin,plan.id,"observe_target","a"*64,grant.execution_id)
    # The shared test database must not leave a pending execution for another worker fixture.
    result = client.post('/api/v1/assistant/executions/' + first.json()['id'] + '/actions',
                         headers=headers, json={'action': 'cancel'})
    assert result.json()['state'] == 'cancelled'


@pytest.mark.parametrize("action",["navigate","patrol","patrol_search","deliver"])
def test_trial_never_authorizes_ordinary_navigation_or_transport(action):
    plan=SimpleNamespace(content=json.dumps({"steps":[{"action":action}]}))
    plan.digest=hashlib.sha256(plan.content.encode()).hexdigest()
    with pytest.raises(HTTPException):
        assistant_trials.trial_step(plan)
