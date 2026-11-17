import asyncio
from types import SimpleNamespace as NS
from uuid import uuid4
import pytest
from fastapi import HTTPException
from app.services import direct_navigation as nav
from app.services.control_leases import ControlLeaseManager

@pytest.mark.parametrize('mode', ['manual','auto','stop'])
def test_preview_stops_before_planning(monkeypatch,mode):
    async def run():
        manager=ControlLeaseManager();state=NS(mode=mode);calls=[]
        monkeypatch.setattr(nav,'control_lease_manager',manager)
        monkeypatch.setattr(nav,'vehicle_binding',lambda db:('r','url'))
        async def stop():
            calls.append('stop');manager.generation+=1;state.mode='stop'
            return dict(controller_confirmed=True,stationary_confirmed=True,errors=[])
        async def request(path,payload):
            assert state.mode=='stop' and manager.preparing_navigation
            with pytest.raises(RuntimeError):
                await manager.acquire_for_run(('r','url'),'u','maps.read','other')
            calls.append(path);return {'plan_id':str(uuid4())}
        monkeypatch.setattr(nav,'get_robot_gateway',lambda _:NS(navigation_request=request))
        result=await nav.prepare_navigation_preview(None,('r','url'),NS(id='u'),{},stop)
        assert calls==['stop','plan'] and not manager.preparing_navigation
        assert nav.previews[('u',result['plan_id'])][1]==manager.generation
    asyncio.run(run())

@pytest.mark.parametrize('fault',['stationary','generation','concurrent','late_plan'])
def test_preparation_fences_races(monkeypatch,fault):
    async def run():
        manager=ControlLeaseManager();calls=[]
        monkeypatch.setattr(nav,'control_lease_manager',manager)
        monkeypatch.setattr(nav,'vehicle_binding',lambda _:('r','url'))
        async def stop():
            manager.generation+=2 if fault=='generation' else 1
            if fault=='concurrent':
                with pytest.raises(HTTPException,match='交接'):
                    await nav.prepare_navigation_preview(None,('r','url'),NS(id='other'),{},stop)
            return dict(controller_confirmed=True,stationary_confirmed=fault!='stationary')
        async def request(path,payload):
            calls.append(path)
            if fault=='late_plan':manager.generation+=1
            return {'plan_id':str(uuid4())}
        monkeypatch.setattr(nav,'get_robot_gateway',lambda _:NS(navigation_request=request))
        if fault=='concurrent':await nav.prepare_navigation_preview(None,('r','url'),NS(id='u'),{},stop)
        else:
            with pytest.raises(HTTPException):await nav.prepare_navigation_preview(None,('r','url'),NS(id='u'),{},stop)
        assert not manager.preparing_navigation
        if fault in ('stationary','generation'):assert not calls
    asyncio.run(run())

@pytest.mark.parametrize('failure,expected', [
    ('lease','租约被拒绝'),('ack','控制器回执超时'),('reject','小车拒绝了导航目标'),
    ('goal_timeout','Nav2 目标确认超时'),('network','导航通信异常'),('timeout','导航通信超时')])
def test_start_retains_specific_first_failure(monkeypatch,failure,expected):
    import httpx
    async def run():
        manager=ControlLeaseManager();ident=str(uuid4());lease=NS(identity=lambda:{'owner':'test'})
        monkeypatch.setattr(nav,'control_lease_manager',manager)
        monkeypatch.setattr(nav,'vehicle_binding',lambda _:('r','url'))
        monkeypatch.setattr(nav,'capability_snapshot',lambda *a:{'capabilities':{'navigate':{'executable':True}}})
        async def acquire(*args):
            if failure in ('lease','ack'):raise RuntimeError(expected)
            manager.current=lease;return lease
        async def release(*args,**kwargs):manager.current=None
        async def request(*args):
            if failure in ('reject','goal_timeout'):
                req=httpx.Request('POST','http://fixture/navigation/start')
                res=httpx.Response(409 if failure=='reject' else 504,json={'detail':'小车拒绝了导航目标'},request=req)
                raise httpx.HTTPStatusError('rejected',request=req,response=res)
            if failure=='network':raise httpx.ConnectError('offline')
            raise httpx.ReadTimeout('timeout')
        monkeypatch.setattr(manager,'acquire_for_run',acquire)
        monkeypatch.setattr(manager,'release_run',release)
        monkeypatch.setattr(nav,'get_robot_gateway',lambda _:NS(navigation_request=request))
        nav.register_preview(('r','url'),'u',ident,0)
        with pytest.raises(HTTPException) as error:
            await nav.start_direct_navigation(None,('r','url'),NS(id='u',permissions={'robots.control','maps.read'}),{'plan_id':ident})
        assert expected in error.value.detail
        with pytest.raises(HTTPException,match='预览'):
            await nav.start_direct_navigation(None,('r','url'),NS(id='u',permissions={'robots.control','maps.read'}),{'plan_id':ident})
    asyncio.run(run())

def test_preview_uses_real_gateway_plan_path(monkeypatch):
    import httpx
    from app.gateway.robot_gateway import RobotGateway
    async def run():
        manager=ControlLeaseManager()
        monkeypatch.setattr(nav,'control_lease_manager',manager)
        monkeypatch.setattr(nav,'vehicle_binding',lambda _:('r','http://fixture'))
        seen=[]
        def handle(request):
            assert request.method=='POST' and request.url.path=='/api/navigation/plan'
            seen.append(request.url.path)
            return httpx.Response(200,json={'plan_id':str(uuid4())})
        gateway=RobotGateway('http://fixture')
        monkeypatch.setattr(gateway,'_client',lambda timeout:httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        monkeypatch.setattr(nav,'get_robot_gateway',lambda _:gateway)
        async def stop():
            manager.generation+=1
            return {'controller_confirmed':True,'stationary_confirmed':True}
        await nav.prepare_navigation_preview(None,('r','http://fixture'),NS(id='u'),{'goal':{}},stop)
        assert seen==['/api/navigation/plan']
    asyncio.run(run())
