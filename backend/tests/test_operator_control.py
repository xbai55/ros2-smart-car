import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import control_leases, operator_control


def test_takeover_requires_confirmed_stationary_evidence(monkeypatch):
    manager = control_leases.ControlLeaseManager()
    monkeypatch.setattr(operator_control, "control_lease_manager", manager)
    user = SimpleNamespace(id="u", permissions={"robots.control"})

    async def stop():
        manager.generation += 1
        return {"controller_confirmed": True, "stationary_confirmed": False}

    with pytest.raises(HTTPException, match="未确认车辆静止"):
        asyncio.run(operator_control.select_operator_mode(None, ("r", "car"), user, "mode", "manual", stop))
    assert manager.current is None


@pytest.mark.parametrize('reuse', [True, False])
def test_only_same_client_can_reuse_current_manual_lease(monkeypatch, reuse):
    manager=control_leases.ControlLeaseManager()
    lease=control_leases.HeldLease('r','car','u',frozenset({'robots.control'}),'c','e','owner',
                                 run_id='drive',purpose='manual',client_id='client',drive_sequence=9)
    manager.current=lease
    monkeypatch.setattr(operator_control,'control_lease_manager',manager)
    monkeypatch.setattr(operator_control,'require_bound_vehicle',lambda *_:('r','car'))
    calls=[]
    async def control():
        return {**lease.identity(),'fresh':True,'blocked':False,'purpose':'manual','drive_sequence':8,
                'intent_sequence':5,'motion_epoch':'recovered','command_valid_until':1234.}
    async def status(_):return {'status':{'mode':'manual','emergency_stop':False}}
    monkeypatch.setattr(operator_control,'get_robot_gateway',lambda _:SimpleNamespace(control_lease=control,get_status=status))
    async def stop():
        calls.append('stop');manager.generation+=1
        return {'controller_confirmed':False,'stationary_confirmed':False}
    user=SimpleNamespace(id='u',permissions={'robots.control'})
    async def scenario():
        action=operator_control.select_operator_mode(None,('r','car'),user,'mode','manual',stop,
                                                     client_id='client' if reuse else 'another-client')
        if reuse:
            result=await action
            assert result['reused'] and result['drive_id']=='drive'
            assert result['drive_seq_floor']==9 and result['intent_seq_floor']==5
            assert result['motion_epoch']=='recovered' and not calls
        else:
            with pytest.raises(HTTPException):await action
            assert calls==['stop']
    asyncio.run(scenario())


@pytest.mark.parametrize("cleanup_errors", [[], ["search_cancel_failed"], ["assistant_queue_cancel_unconfirmed"]])
def test_drive_handle_is_bound_to_operator_and_orders_stop(monkeypatch, cleanup_errors):
    manager = control_leases.ControlLeaseManager()
    monkeypatch.setattr(operator_control, "control_lease_manager", manager)
    binding = ("r", "car")
    user = SimpleNamespace(id="u", permissions={"robots.control"})
    other = SimpleNamespace(id="other", permissions=user.permissions)
    calls = []

    async def lease_request(payload=None):
        calls.append(payload["op"] if payload else "query")
        if payload is None:
            return {"controller_id": "c", "control_epoch": "e", "fresh": True, "blocked": True}
        return {"confirmed": True, "lease": {**payload, "fresh": True, "blocked": False, "motion_epoch": "m", "command_valid_until": 1234.}}

    async def request(path, payload):
        calls.append((path, payload))
        return {"ok": True, **{key: payload[key] for key in ("mode", "command") if key in payload}}

    async def stop():
        calls.append("stop")
        manager.generation += 1
        return {"controller_confirmed": True, "stationary_confirmed": True, "errors": cleanup_errors}

    gateway = SimpleNamespace(control_lease=lease_request, operator_request=request)
    monkeypatch.setattr(control_leases, "get_robot_gateway", lambda _: gateway)
    monkeypatch.setattr(operator_control, "get_robot_gateway", lambda _: gateway)
    monkeypatch.setattr(operator_control, "require_bound_vehicle", lambda *_: binding)

    async def run():
        result = await operator_control.select_operator_mode(None, binding, user, "mode", "manual", stop)
        drive = result["drive_id"]
        assert result["takeover_warnings"] == cleanup_errors
        assert calls[:3] == ["stop", "query", "acquire"]
        assert calls[3][1]["control_lease"] == manager.current.identity()
        with pytest.raises(HTTPException, match="控制权已失效"):
            await operator_control.send_drive(binding, other, "forward", drive, 1)
        await operator_control.send_drive(binding, user, "stop", drive, 2, intent_seq=1, motion_epoch="m", command_deadline=1234.)
        with pytest.raises(HTTPException, match="更新的驾驶指令"):
            await operator_control.send_drive(binding, user, "forward", drive, 1, intent_seq=1, motion_epoch="m", command_deadline=1234.)
        await operator_control.send_drive(binding, user, "forward", drive, 3, intent_seq=2, motion_epoch="m", command_deadline=1234.)
        assert [(call[1]["command"], call[1]["drive_seq"]) for call in calls[4:]] == [("stop", 2), ("forward", 3)]

    asyncio.run(run())


def test_original_manual_protocol_retains_owner_sequence_and_api_validation(monkeypatch):
    from app.api.routes.vehicle_control import authorize_vehicle_write
    manager=control_leases.ControlLeaseManager()
    lease=control_leases.HeldLease('r','car','u',frozenset({'robots.control'}),'c','e','owner',
                                 run_id='drive',purpose='manual')
    manager.current=lease
    monkeypatch.setattr(operator_control,'control_lease_manager',manager)
    sent=[]
    async def request(path,payload):
        sent.append(payload)
        return {'ok':True,'command':payload['command']}
    monkeypatch.setattr(operator_control,'get_robot_gateway',lambda _:SimpleNamespace(operator_request=request))
    user=SimpleNamespace(id='u',permissions={'robots.control'})
    async def scenario():
        for seq,command in enumerate(('forward','forward','stop'),1):
            body={'command':command,'drive_id':'drive','drive_seq':seq}
            authorize_vehicle_write('command',body,user.permissions)
            await operator_control.send_drive(('r','car'),user,command,'drive',seq)
        assert all(set(p)=={'command','drive_seq','control_lease'} for p in sent)
        with pytest.raises(HTTPException,match='更新的驾驶指令'):
            await operator_control.send_drive(('r','car'),user,'forward','drive',2)
    asyncio.run(scenario())
