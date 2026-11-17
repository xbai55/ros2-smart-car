import json
from types import SimpleNamespace as N
import pytest
from test_avoidance_adapter import controller
from test_basic_protection import ready
from smart_car_decision.service_budgets import NAVIGATION_START_WAIT


def navigation(c):
    ready(c);c.mode='stop';c.control_lease.purpose='navigation'
    c.on_mode(N(data='navigation'))
    return c.control_lease


def advance(c,monkeypatch,now):
    monkeypatch.setattr(c.control_loop.__globals__['time'],'monotonic',lambda:now)
    c.evidence_at=c.velocity_at=c.odom_at=c.last_scan_time=now
    c.control_lease.deadline=now+3
    c.control_loop()
    t=c.output[-1]
    return t.linear.x,t.linear.y,t.angular.z


def test_start_wait_never_moves_or_revokes_then_accepts_first_fresh_command(controller,monkeypatch):
    c=controller;lease=navigation(c);owner=lease.owner
    assert advance(c,monkeypatch,100.+NAVIGATION_START_WAIT-.1)==(0,0,0)
    assert lease.owner==owner and 'navigation_waiting_command' in c.output_status['reasons']
    c.on_navigation_command(N(linear=N(x=.02,y=0.),angular=N(z=0.)))
    assert advance(c,monkeypatch,100.+NAVIGATION_START_WAIT-.05)[0]>0
    assert lease.owner==owner


def test_start_timeout_revokes_once_and_rejects_late_first_command(controller,monkeypatch):
    c=controller;lease=navigation(c)
    assert advance(c,monkeypatch,100.+NAVIGATION_START_WAIT+.1)==(0,0,0)
    assert lease.owner is None and c.interruption_reason=='navigation_start_timeout'
    epoch=lease.epoch
    c.on_navigation_command(N(linear=N(x=.02,y=0.),angular=N(z=0.)))
    assert advance(c,monkeypatch,100.+NAVIGATION_START_WAIT+.2)==(0,0,0)
    assert lease.epoch==epoch and c.interruption_reason=='navigation_start_timeout'


def test_after_first_command_original_stream_expiry_still_stops(controller,monkeypatch):
    c=controller;lease=navigation(c)
    c.on_navigation_command(N(linear=N(x=.02,y=0.),angular=N(z=0.)))
    assert advance(c,monkeypatch,100.01)[0]>0
    assert advance(c,monkeypatch,100.+c.navigation_timeout_sec+.01)==(0,0,0)
    assert lease.owner is None and c.interruption_reason=='navigation_command_timeout'


def test_scan_fault_still_interrupts_start_wait(controller):
    c=controller;lease=navigation(c);c.evidence_at=c.last_scan_time=0.
    c.control_loop()
    assert c.output[-1].linear.x==0 and lease.owner is None
