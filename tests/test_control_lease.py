import pytest
from smart_car_decision.control_lease import ControlLease


def request(lease, op="acquire", sequence=0, owner="host"):
    return {"controller_id": lease.controller_id, "control_epoch": lease.epoch,
            "owner": owner, "sequence": sequence, "op": op}


def test_startup_and_expiry_require_new_stationary_acquisition():
    lease = ControlLease()
    assert lease.blocked(0)
    assert not lease.update(request(lease), 0, stationary=False)
    assert lease.update(request(lease), 0, stationary=True)
    old = request(lease, "renew", 1)
    assert not lease.blocked(2.999)
    assert lease.blocked(3)
    assert not lease.update(old, 3)
    assert lease.update(request(lease), 3, stationary=True)


def test_old_or_foreign_heartbeats_do_not_extend_lease():
    lease = ControlLease()
    assert lease.update(request(lease), 0, stationary=True)
    assert lease.update(request(lease, "renew", 1), 1)
    assert not lease.update(request(lease, "renew", 1), 2)
    assert not lease.update(request(lease, "renew", 2, "other"), 2)
    assert lease.blocked(4)


@pytest.mark.parametrize("reason", ["stop", "emergency_stop", "manual_takeover"])
def test_revocation_invalidates_delayed_requests(reason):
    lease = ControlLease()
    assert lease.update(request(lease), 0, stationary=True)
    delayed = request(lease, "renew", 99)
    lease.revoke(reason)
    assert not lease.update(delayed, 1, stationary=True)
    assert lease.snapshot(1)["reason"] == reason


def test_controller_restart_and_nonfinite_time_fail_closed():
    old = ControlLease()
    restarted = ControlLease()
    assert not restarted.update(request(old), 1, stationary=True)
    assert not restarted.update(request(restarted), float("nan"), stationary=True)


def test_manual_release_rejects_out_of_order_motion_and_allows_a_new_press():
    lease = ControlLease()
    claim = {**request(lease), "purpose": "manual"}
    assert lease.update(claim, 0, stationary=True)
    claim.update(intent_seq=1, motion_epoch=lease.motion_epoch, command_deadline=1.7)
    assert lease.accepts_drive({**claim, "drive_seq": 2, "command": "stop"}, 1, "manual")
    assert not lease.accepts_drive({**claim, "drive_seq": 1, "command": "forward"}, 1.1, "manual")
    assert not lease.accepts_drive({**claim, "drive_seq": 3, "command": "forward"}, 1.2, "mapping")
    assert lease.accepts_drive({**claim, "intent_seq": 2, "drive_seq": 3, "command": "forward"}, 1.2, "manual")
    lease.revoke("operator_stop")
    assert not lease.accepts_drive({**claim, "drive_seq": 4}, 1.3, "manual")


def test_automation_lease_never_accepts_manual_commands():
    lease = ControlLease()
    claim = request(lease)
    assert lease.update(claim, 0, stationary=True)
    assert not lease.accepts_drive({**claim, "drive_seq": 1}, 1, "manual")

def test_old_scoped_stop_and_release_cannot_revoke_new_owner():
    lease = ControlLease()
    old = request(lease)
    assert lease.update(old, 0, stationary=True)
    lease.revoke('operator_stop')
    assert lease.update(request(lease, owner='new'), 1, stationary=True)
    for op in ('stop','release','renew'):
        assert not lease.update({**old, 'op':op, 'sequence':99}, 1.1)
        assert lease.owner == 'new'
