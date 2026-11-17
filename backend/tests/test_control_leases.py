import asyncio
from types import SimpleNamespace
import pytest
from app.services import control_leases


def test_stop_during_acquisition_cannot_install_late_lease(monkeypatch):
    async def scenario():
        manager = control_leases.ControlLeaseManager()
        sent = asyncio.Event()
        release = asyncio.Event()
        calls = []
        async def request(payload):
            calls.append(payload["op"])
            if payload["op"] == "acquire":
                sent.set()
                await release.wait()
                return {"confirmed": True, "lease": {**payload, "fresh": True, "blocked": False}}
            return {"confirmed": True, "lease": {"blocked": True}}
        monkeypatch.setattr(control_leases, "get_robot_gateway", lambda address: SimpleNamespace(control_lease=request))
        task = asyncio.create_task(manager.acquire("r", "url", "u", {"robots.control"}, {"controller_id": "c", "control_epoch": "e"}))
        await sent.wait()
        await manager.stop()
        release.set()
        with pytest.raises(RuntimeError):
            await task
        assert manager.current is None
        assert calls == ["acquire", "release"]
    asyncio.run(scenario())


def test_request_accepted_without_matching_receipt_is_not_held(monkeypatch):
    async def request(payload):
        return {"confirmed": False}
    monkeypatch.setattr(control_leases, "get_robot_gateway", lambda address: SimpleNamespace(control_lease=request))
    manager = control_leases.ControlLeaseManager()
    with pytest.raises(RuntimeError):
        asyncio.run(manager.acquire("r", "url", "u", set(), {"controller_id": "c", "control_epoch": "e"}))
    assert manager.current is None and not manager.acquiring
