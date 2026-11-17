from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def execution_client(client, login, monkeypatch):
    from app.services.control_leases import ControlLeaseManager
    manager = ControlLeaseManager()
    monkeypatch.setattr("app.api.routes.navigation_tasks.control_lease_manager", manager)
    async def lease_request(self, payload=None):
        if payload is None:
            return {"controller_id": "test-controller", "control_epoch": "test-epoch", "fresh": True, "blocked": True}
        return {"confirmed": True, "lease": {**payload, "fresh": True, "blocked": payload["op"] != "acquire"}}
    monkeypatch.setattr("app.gateway.robot_gateway.RobotGateway.control_lease", lease_request)
    monkeypatch.setattr("app.api.routes.navigation_tasks.vehicle_binding", lambda db: ("fixture-robot-1", ""))
    runs, calls = {}, []
    async def request(self, path, payload=None, *, query=None):
        calls.append((path, payload, query))
        if path == "task" and payload:
            return runs.setdefault(payload["run_id"], {"run_id": payload["run_id"], "task_id": payload["task_id"],
                "kind": payload["kind"], "state": "waiting_load" if payload["kind"] == "delivery" else "prepared",
                "message": "等待确认", "goals": payload["waypoints"], "completed_stops": 0})
        if path == "task":
            if query['run_id'] not in runs:
                req=httpx.Request('GET','http://fixture/api/navigation/task')
                raise httpx.HTTPStatusError('missing',request=req,response=httpx.Response(404,request=req,json={'detail':{'code':'NAVIGATION_RUN_NOT_FOUND'}}))
            return runs[query["run_id"]]
        if path == "task/action":
            value = runs[payload["run_id"]]
            if payload["action"] == "loaded":
                assert payload["control_lease"] == manager.current.identity()
                value["control_lease"] = payload["control_lease"]
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
    pending = client.post("/api/v1/navigation-tasks", json=body, headers=headers)
    assert pending.status_code == 200 and pending.json()['state']=='unconfirmed'
    assert pending.json()['sync_state']=='unreachable'
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


def test_missing_record_converges_and_retry_reuses_exact_saved_request(execution_client,monkeypatch):
    import copy
    client,headers,body,runs,calls=execution_client
    original=__import__('app.gateway.robot_gateway',fromlist=['RobotGateway']).RobotGateway.navigation_request
    async def lost(self,*a,**kw):raise httpx.ReadTimeout('lost')
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.navigation_request',lost)
    pending=client.post('/api/v1/navigation-tasks',headers=headers,json=body).json()
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.navigation_request',original)
    url=f"/api/v1/navigation-tasks/delivery/{pending['task_id']}"
    # Explicit query bypasses network backoff only through retry, first verify
    # missing and then verify repeated background/UI reads are served locally.
    from app.services import task_sync
    missing=client.get(url,headers=headers).json()
    assert missing['sync_state']=='record_missing' and missing['poll_required'] is False
    count=len(calls)
    for _ in range(3):assert client.get(url,headers=headers).json()['sync_state']=='record_missing'
    assert len(calls)==count
    changed=copy.deepcopy(body);changed['waypoints'][0]['drawing']['x']+=1
    assert client.post('/api/v1/navigation-tasks',headers=headers,json=changed).status_code==409
    result=client.post(url+'/action',headers=headers,json={'run_id':body['run_id'],'action':'retry'})
    assert result.status_code==200 and result.json()['state']=='waiting_load'
    dispatches=[p for path,p,q in calls if path=='task' and p]
    assert dispatches[-1]==missing['request'] and dispatches[-1]['run_id']==body['run_id']
    assert result.json()['request_fingerprint']==missing['request_fingerprint']


def test_mismatched_record_blocks_retry_and_polling(execution_client,monkeypatch):
    client,headers,body,runs,calls=execution_client
    value=client.post('/api/v1/navigation-tasks',headers=headers,json=body).json()
    runs[body['run_id']]={**value,'task_id':'foreign-task'}
    url=f"/api/v1/navigation-tasks/delivery/{value['task_id']}"
    result=client.get(url,headers=headers).json()
    assert result['sync_state']=='record_mismatch' and not result['poll_required']
    n=len(calls);client.get(url,headers=headers);assert len(calls)==n
    assert client.post(url+'/action',headers=headers,json={'run_id':body['run_id'],'action':'retry'}).status_code==409


def test_cancel_timeout_keeps_barrier_and_blocks_new_dispatch(execution_client,monkeypatch):
    client,headers,body,runs,calls=execution_client
    value=client.post('/api/v1/navigation-tasks',headers=headers,json=body).json()
    async def lost(*a,**kw):raise httpx.ReadTimeout('cancel lost')
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.navigation_request',lost)
    url=f"/api/v1/navigation-tasks/delivery/{value['task_id']}"
    assert client.post(url+'/action',headers=headers,json={'run_id':body['run_id'],'action':'cancel'}).status_code==502
    pending=client.get(url,headers=headers).json()
    assert pending['sync_state']=='cancel_pending'
    assert client.post(url+'/action',headers=headers,json={'run_id':body['run_id'],'action':'retry'}).status_code==409
    again=client.post('/api/v1/navigation-tasks',headers=headers,json=body).json()
    assert again['sync_state']=='cancel_pending'


def test_unreachable_query_backs_off_without_claiming_missing(execution_client,monkeypatch):
    from types import SimpleNamespace
    from app.services import task_sync
    client,headers,body,runs,calls=execution_client
    value=client.post('/api/v1/navigation-tasks',headers=headers,json=body).json()
    url=f"/api/v1/navigation-tasks/delivery/{value['task_id']}"
    counter=[]
    async def offline(*a,**kw):counter.append(1);raise httpx.ConnectError('offline')
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.navigation_request',offline)
    monkeypatch.setattr(task_sync,'time',SimpleNamespace(time=lambda:100.))
    v=client.get(url,headers=headers).json()
    assert v['sync_state']=='unreachable' and v['next_poll_at']==102.
    for _ in range(3):client.get(url,headers=headers)
    assert len(counter)==1
    monkeypatch.setattr(task_sync,'time',SimpleNamespace(time=lambda:103.))
    v=client.get(url,headers=headers).json()
    assert v['next_poll_at']==107. and v['state']=='waiting_load'


def test_late_lookup_cannot_override_another_clients_cancellation(execution_client,monkeypatch):
    from app.models import MissionTask
    from app.services.navigation_execution import store_execution
    from app.api.deps import get_db
    client,headers,body,runs,calls=execution_client
    prepared=client.post('/api/v1/navigation-tasks',headers=headers,json=body).json()
    async def delayed(self,path,payload=None,*,query=None):
        session = client.app.dependency_overrides[get_db]()
        db = next(session)
        try:
            item=db.get(MissionTask,prepared['task_id'])
            store_execution(db,item,{**prepared,'state':'cancelled','version':10})
            db.commit()
        finally:
            session.close()
        return {**prepared,'state':'running','version':11}
    monkeypatch.setattr('app.gateway.robot_gateway.RobotGateway.navigation_request',delayed)
    url=f"/api/v1/navigation-tasks/delivery/{prepared['task_id']}"
    value=client.get(url,headers=headers).json()
    assert value['state']=='cancelled'
    assert client.post('/api/v1/navigation-tasks',headers=headers,json=body).json()['state']=='cancelled'
