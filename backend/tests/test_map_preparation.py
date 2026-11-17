from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from sqlalchemy import select
from app.models import User,MapPreparation
from app.services.control_leases import control_lease_manager


@pytest.fixture
def preparation_client(client,login,monkeypatch):
    from conftest import TestingSessionLocal
    monkeypatch.setattr('app.services.control_access.vehicle_binding',lambda db:('fixture-robot-1','vehicle'))
    with TestingSessionLocal() as db:
        user=db.scalar(select(User).where(User.username=='operator'))
        lease=NS(purpose='mapping',user_id=user.id,robot_id='fixture-robot-1',address='vehicle',run_id='run')
    monkeypatch.setattr(control_lease_manager,'current',lease)
    headers={'Authorization':'Bearer '+login('operator','operator123')}
    yield client,headers
    with TestingSessionLocal() as db:
        for job in db.scalars(select(MapPreparation)).all(): db.delete(job)
        db.commit()


def test_preparation_is_idempotent_and_prevents_parallel_robot_jobs(preparation_client):
    c,h=preparation_client
    p={'request_id':str(uuid4()),'robot_id':'fixture-robot-1','session_id':'session','name':'fresh map'}
    url='/api/v1/maps/slam/finish-for-tasks'
    first=c.post(url,headers=h,json=p)
    assert first.status_code==202,first.text
    assert c.post(url,headers=h,json=p).json()['id']==first.json()['id']
    assert c.post(url,headers=h,json={**p,'name':'changed'}).status_code==409
    assert c.post(url,headers=h,json={**p,'request_id':str(uuid4())}).status_code==409
    assert c.get('/api/v1/maps/slam/preparations/'+first.json()['id'],headers=h).json()['state']=='pending'


def test_no_mapping_lease_cannot_prepare(preparation_client,monkeypatch):
    c,h=preparation_client
    monkeypatch.setattr(control_lease_manager,'current',None)
    p={'request_id':str(uuid4()),'robot_id':'fixture-robot-1','session_id':'session','name':'fresh map'}
    assert c.post('/api/v1/maps/slam/finish-for-tasks',headers=h,json=p).status_code==409


def test_cancel_frees_robot_slot_and_same_request_never_restarts(preparation_client,monkeypatch):
    from conftest import TestingSessionLocal
    c,h=preparation_client
    p={'request_id':str(uuid4()),'robot_id':'fixture-robot-1','session_id':'session','name':'fresh map'}
    ident=c.post('/api/v1/maps/slam/finish-for-tasks',headers=h,json=p).json()['id']
    async def cleanup(job): pass
    monkeypatch.setattr('app.api.routes.map_preparation.cleanup',cleanup)
    result=c.post('/api/v1/maps/slam/preparations/'+ident+'/cancel',headers=h,json={})
    assert result.json()['state']=='cancelled'
    assert c.post('/api/v1/maps/slam/finish-for-tasks',headers=h,json=p).json()['state']=='cancelled'
    with TestingSessionLocal() as db:
        assert db.get(MapPreparation,ident).active_robot is None


def test_restart_marks_pending_failed_without_replaying(preparation_client,monkeypatch):
    from conftest import TestingSessionLocal
    from app.services import map_preparation as service
    c,h=preparation_client
    p={'request_id':str(uuid4()),'robot_id':'fixture-robot-1','session_id':'session','name':'fresh map'}
    ident=c.post('/api/v1/maps/slam/finish-for-tasks',headers=h,json=p).json()['id']
    monkeypatch.setattr(service,'SessionLocal',TestingSessionLocal)
    service.recover_map_preparations()
    with TestingSessionLocal() as db:
        job=db.get(MapPreparation,ident)
        assert job.state=='failed' and job.active_robot is None


def test_worker_sends_pose_once_and_records_completion(preparation_client,monkeypatch):
    import asyncio
    from conftest import TestingSessionLocal
    from app.services import map_preparation as service
    c,h=preparation_client
    p={'request_id':str(uuid4()),'robot_id':'fixture-robot-1','session_id':'session','name':'fresh map'}
    ident=c.post('/api/v1/maps/slam/finish-for-tasks',headers=h,json=p).json()['id']
    calls=[]
    async def finish(payload): return {'handoff_id':'handoff','digest':'digest','snapshot':{}}
    async def stop(): return {'controller_confirmed':True,'stationary_confirmed':True}
    async def nav(path,payload):
        calls.append(path)
        return {'initial_pose_ready':True,'localized':True,'state':'ready'}
    async def release(*args,**kwargs): pass
    def register(job_id,exported):
        with TestingSessionLocal() as db:
            db.get(MapPreparation,job_id).map_id='preserved';db.commit()
        return 'preserved'
    control_lease_manager.current.identity=lambda:{'owner':'test'}
    monkeypatch.setattr(service,'SessionLocal',TestingSessionLocal)
    monkeypatch.setattr(service,'get_robot_gateway',lambda address:NS(finish_mapping_for_tasks=finish,stop=stop,navigation_request=nav))
    monkeypatch.setattr(service,'register_map',register)
    monkeypatch.setattr(control_lease_manager,'release_run',release)
    asyncio.run(service.prepare(ident))
    assert calls.count('handoff-seed')==1
    with TestingSessionLocal() as db:
        job=db.get(MapPreparation,ident)
        assert job.state=='completed' and job.map_id=='preserved' and job.active_robot is None
