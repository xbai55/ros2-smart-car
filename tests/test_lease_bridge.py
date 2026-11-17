import asyncio
from types import SimpleNamespace
import pytest
from smart_car_decision.control_lease import ControlLease
from smart_car_decision.lease_bridge import LeaseBridge


def setup_bridge(acknowledge=True):
    clock = [0.]
    gate = ControlLease()
    node = SimpleNamespace(control_lease_ack={**gate.snapshot(0), "received_at": 0.})
    sent = []
    def publish(value):
        sent.append(value)
        if acknowledge:
            gate.update(value, clock[0], stationary=True)
            node.control_lease_ack = {**gate.snapshot(clock[0]), "received_at": clock[0]}
    async def sleep(seconds):
        clock[0] += seconds
    node.publish_control_lease = publish
    return LeaseBridge(node, lambda: clock[0], sleep), gate, clock, sent


def payload(gate, op="acquire", seq=0):
    return {"controller_id": gate.controller_id, "control_epoch": gate.epoch,
            "owner": "host", "sequence": seq, "op": op}


def test_publication_without_controller_receipt_is_not_confirmation():
    bridge, gate, _, sent = setup_bridge(False)
    result = asyncio.run(bridge.request(payload(gate)))
    assert len(sent) == 1
    assert not result["confirmed"]


def test_acquire_and_stop_round_trip_invalidates_old_renewal():
    bridge, gate, _, sent = setup_bridge()
    assert asyncio.run(bridge.request(payload(gate)))["confirmed"]
    old = payload(gate, "renew", 1)
    result = asyncio.run(bridge.request(payload(gate, "stop")))
    assert result["confirmed"] and result["lease"]["blocked"]
    with pytest.raises(RuntimeError, match="失效"):
        asyncio.run(bridge.request(old))
    assert len(sent) == 2


def test_stale_ack_does_not_dispatch():
    bridge, gate, clock, sent = setup_bridge()
    clock[0] = 1
    with pytest.raises(RuntimeError, match="陈旧"):
        asyncio.run(bridge.request(payload(gate)))
    assert not sent

def test_explicit_controller_rejection_is_not_receipt_timeout():
    bridge, gate, clock, _ = setup_bridge()
    def reject(value):
        gate.update(value, clock[0], stationary=False)
        bridge.node.control_lease_ack = {**gate.snapshot(clock[0]), 'received_at':clock[0]}
    bridge.node.publish_control_lease = reject
    result = asyncio.run(bridge.request(payload(gate)))
    assert result['confirmed'] is True
    assert result['reason'] == 'controller_lease_rejected'
    assert gate.owner is None and clock[0] == 0
