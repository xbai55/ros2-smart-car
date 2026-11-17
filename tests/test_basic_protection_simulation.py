"""Deterministic kinematic/sensor replay; no ROS, networking or physical motion."""
import json
from types import SimpleNamespace as NS

from smart_car_decision.footprint import Rectangle
from test_avoidance import scene
from test_avoidance_adapter import controller
from test_basic_protection import ready, drive


def test_closed_loop_approach_brake_and_no_restart_after_obstacle_disappears(controller, monkeypatch, tmp_path):
    c = controller
    identity = ready(c)
    epoch = c.control_lease.motion_epoch
    clock = [100.]
    monkeypatch.setattr(c.control_loop.__globals__['time'], 'monotonic', lambda: clock[0])
    body = Rectangle(.0935, .1565, .1)
    x, speed, minimum = 0., 0., 10.
    rows, seq = [], 0
    obstacle = (.40, 0., .04)
    interrupted = False
    for index in range(100):
        clock[0] = 100. + index*.05
        c.control_lease.update({**identity, 'op': 'renew', 'sequence': index+1}, clock[0])
        c.velocity_speed, c.velocity_angular, c.velocity_at = abs(speed), 0., clock[0]
        c.scan_evidence = scene(pose=(x, 0., 0.), obstacles=(obstacle,), sequence=index+1)
        c.evidence_at = clock[0]-.05
        seq += 1
        requested = drive(c, identity, 'forward', seq, epoch=epoch)[0]
        # A simple acceleration-limited chassis makes braking take time.
        speed += max(-.3*.05, min(.3*.05, requested-speed))
        x += speed*.05
        clearance = body.clearance(obstacle[:2], (x, 0., 0.)) - obstacle[2]
        minimum = min(minimum, clearance)
        rows.append({'at': clock[0], 'x': x, 'speed': speed, 'output': requested, 'clearance': clearance})
        if c.interruption_reason:
            interrupted = True
            if abs(speed) < 1e-8:
                break
    assert interrupted and minimum >= .05
    c.scan_evidence = scene(pose=(x, 0., 0.), obstacles=())
    c.evidence_at = c.velocity_at = clock[0]
    c.velocity_speed = 0.
    assert drive(c, identity, 'forward', seq+1, epoch=epoch) == (0, 0, 0)
    drive(c, identity, 'stop', seq+2, epoch=epoch)
    assert drive(c, identity, 'forward', seq+3, intent=2)[0] > 0
    (tmp_path/'kinematic-replay.json').write_text(json.dumps({'minimum_clearance_m': minimum,
        'old_intent_restarted': False, 'samples': rows}), encoding='utf-8')
