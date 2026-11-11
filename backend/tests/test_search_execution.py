import asyncio
import hashlib
import json
from types import SimpleNamespace as NS

import httpx
import pytest
from fastapi import HTTPException

from app.services import search_execution


@pytest.fixture
def search_dispatch(monkeypatch):
    binding = ("robot", "http://test")
    identity = {"controller_id": "controller", "control_epoch": "epoch", "owner": "owner"}
    state = NS(accepted=True, record=None, calls=[], lost_response=False, save=True, released=[])
    lease = NS(identity=lambda: identity)
    manager = NS(current=None)

    async def acquire(*args, **kwargs):
        assert kwargs["additional_permissions"] == {"maps.read"}
        state.calls.append("lease")
        manager.current = lease
        return lease

    async def release(run_id, *, lease):
        state.released.append(run_id)
        manager.current = None

    async def request(run_id, *, operation=None, payload=None):
        state.calls.append(operation or "get")
        if operation is None:
            return state.record
        assert payload["control_lease"] == identity
        request = {key: value for key, value in payload.items() if key != "control_lease"}
        result = {"run_id": run_id, "state": "searching", "control_lease": identity,
                  "request_fingerprint": hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()}
        if state.save:
            state.record = result
        if state.lost_response:
            raise httpx.ReadTimeout("lost response")
        return result

    manager.acquire_for_run, manager.release_run = acquire, release
    monkeypatch.setattr(search_execution, "control_lease_manager", manager)
    monkeypatch.setattr(search_execution, "get_robot_gateway", lambda address: NS(search_request=request))
    monkeypatch.setattr(search_execution, "vehicle_binding", lambda db: binding)
    monkeypatch.setattr(search_execution, "capability_snapshot", lambda *args: {
        "capabilities": {"patrol_search": {"executable": state.accepted}}})
    user = NS(id="user", permissions={"robots.control", "patrol.manage", "maps.read"})
    payload = {"run_id": "search-1", "travel": "patrol", "targets": [{"name": "机柜"}]}
    return state, lambda body=payload: asyncio.run(search_execution.execute_search(None, binding, user, "start", body))


def test_lost_response_reconciles_and_repeated_start_does_not_dispatch(search_dispatch):
    state, dispatch = search_dispatch
    state.lost_response = True
    assert dispatch()["state"] == "searching"
    assert dispatch() == state.record
    assert state.calls == ["get", "lease", "start", "get", "get"]
    assert not state.released


def test_unknown_dispatch_releases_only_the_new_lease(search_dispatch):
    state, dispatch = search_dispatch
    state.lost_response, state.save = True, False
    with pytest.raises(HTTPException) as error:
        dispatch()
    assert error.value.status_code == 502
    assert state.calls == ["get", "lease", "start", "get"]
    assert state.released == ["search-1"]


def test_unaccepted_capability_and_client_lease_are_denied(search_dispatch):
    state, dispatch = search_dispatch
    state.accepted = False
    with pytest.raises(HTTPException) as error:
        dispatch()
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        dispatch({"run_id": "search-1", "travel": "patrol", "control_lease": {}})
    assert error.value.status_code == 422
    assert state.calls == ["get"]


@pytest.mark.parametrize('status', [400, 422])
def test_explicit_rejection_does_not_query_missing_run(search_dispatch, monkeypatch, status):
    state, dispatch = search_dispatch
    async def request(run_id, *, operation=None, payload=None):
        state.calls.append(operation or 'get')
        if operation is None:
            return None
        response = httpx.Response(status, request=httpx.Request('POST', 'http://test/api/search/start'))
        raise httpx.HTTPStatusError('rejected', request=response.request, response=response)
    monkeypatch.setattr(search_execution, 'get_robot_gateway', lambda _: NS(search_request=request))
    with pytest.raises(search_execution.SearchRequestRejected):
        dispatch()
    assert state.calls == ['get', 'lease', 'start']
    assert state.released == ['search-1']
