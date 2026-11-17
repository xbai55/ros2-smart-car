"""Original held-button commands remain independent of status-issued credentials."""
import json
from types import SimpleNamespace as N
from test_avoidance_adapter import controller
from test_basic_protection import ready


def command(c, identity, value, sequence):
    c.on_manual_command(N(data=json.dumps({**identity, 'command': value, 'drive_seq': sequence})))
    c.control_loop()
    t=c.output[-1]
    return t.linear.x, t.linear.y, t.angular.z


def test_repeated_original_commands_continue_without_epoch_or_deadline(controller):
    c=controller;identity=ready(c)
    for sequence in range(1, 15):
        assert command(c,identity,'forward',sequence)[0]>0
    assert command(c,identity,'stop',15)==(0,0,0)
    assert command(c,identity,'forward',14)==(0,0,0)  # Late pre-release packet.


def test_original_command_still_expires_when_refresh_stops(controller,monkeypatch):
    c=controller;identity=ready(c)
    assert command(c,identity,'forward',1)[0]>0
    monkeypatch.setattr(c.control_loop.__globals__['time'],'monotonic',lambda:100.71)
    c.evidence_at=c.velocity_at=100.71
    c.control_loop()
    assert c.output[-1].linear.x==0
    assert c.interruption_reason=='manual_command_timeout'


def test_original_command_cannot_bypass_expired_lease_or_full_recovery(controller,monkeypatch):
    c=controller;identity=ready(c)
    c.recovery_required=True
    assert command(c,identity,'forward',1)==(0,0,0)
    c.recovery_required=False
    monkeypatch.setattr(c.control_loop.__globals__['time'],'monotonic',lambda:103.01)
    c.evidence_at=c.velocity_at=103.01
    assert command(c,identity,'forward',2)==(0,0,0)
