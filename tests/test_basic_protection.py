import json
import math
from types import SimpleNamespace as NS

import pytest

from smart_car_decision.avoidance import AvoidanceController, ZERO
from smart_car_decision.avoidance_settings import AvoidanceSettings, DEFAULTS
from smart_car_decision.control_lease import ControlLease
from smart_car_decision.footprint import Rectangle
from smart_car_decision.local_collision_guard import local_guard, velocity_evidence
from smart_car_decision.search_control import SearchGate
from smart_car_decision.stop_service import stationary_evidence
from test_avoidance import scene
from test_avoidance_adapter import controller


def ready(c, profile='basic'):
    c.avoidance.settings = {**DEFAULTS, 'protection_mode': profile}
    c.avoidance.footprint = Rectangle(.0935, .1565, .10)
    c.avoidance_confirmed = True
    c.publish_rate_hz = 20.
    c.scan_fault = None
    c.interruption_reason = None
    c.recovery_required = False
    c.velocity_at = 100.
    c.velocity_speed = c.velocity_angular = c.actual_angular_speed = 0.
    c.scan_evidence = scene(obstacles=())
    c.control_lease = lease = ControlLease()
    identity = {'controller_id': lease.controller_id, 'control_epoch': lease.epoch, 'owner': 'host'}
    c.on_control_lease(NS(data=json.dumps({**identity, 'op': 'acquire', 'purpose': 'manual', 'sequence': 0})))
    assert lease.owner == 'host'
    c.on_mode(NS(data='manual'))
    c.pose = c.evidence_pose = None
    return identity


def drive(c, identity, command, seq, intent=1, epoch=None, deadline=None):
    c.on_manual_command(NS(data=json.dumps({**identity, 'command': command, 'drive_seq': seq,
        'intent_seq': intent, 'motion_epoch': epoch or c.control_lease.motion_epoch,
        'command_deadline': deadline if deadline is not None else c.control_loop.__globals__['time'].monotonic()+.7})))
    c.control_loop()
    t = c.output[-1]
    return (t.linear.x, t.linear.y, t.angular.z)


def test_defaults_and_legacy_migration_are_basic_with_detour_off(tmp_path):
    assert AvoidanceController().settings == DEFAULTS
    p = tmp_path/'config.json'
    old = {'enabled': True, 'trigger_distance_m': .8}
    p.write_text(json.dumps(old))
    config = AvoidanceSettings(p)
    assert config.value == {**DEFAULTS, 'trigger_distance_m': .8}
    config.save(config.value)
    assert json.loads(p.with_name('config.json.pre-basic').read_text()) == old
    config.save({**DEFAULTS, 'enabled': True, 'protection_mode': 'full'})
    assert AvoidanceSettings(p).value['protection_mode'] == 'full'
    assert AvoidanceSettings(p).value['enabled'] is True


def test_manual_basic_needs_neither_pose_nor_global_tf(controller):
    identity = ready(controller)
    assert drive(controller, identity, 'forward', 1)[0] > 0
    assert controller.sensors_ready(100.)


@pytest.mark.parametrize('fault', ['scan', 'velocity', 'invalid_velocity', 'unknown'])
def test_fault_requires_new_press_and_invalidates_inflight_intent(controller, fault):
    c = controller
    identity = ready(c)
    old_epoch = c.control_lease.motion_epoch
    assert drive(c, identity, 'forward', 1)[0] > 0
    if fault == 'scan': c.evidence_at = 99.3
    if fault == 'velocity': c.velocity_at = 99.4
    if fault == 'invalid_velocity': c.velocity_angular = math.nan
    if fault == 'unknown': c.scan_evidence.rays = [None]*720
    c.control_loop()
    assert c.output[-1].linear.x == 0
    assert c.control_lease.motion_epoch != old_epoch
    c.evidence_at = c.velocity_at = 100.
    c.velocity_angular = 0.
    c.scan_evidence = scene(obstacles=())
    assert drive(c, identity, 'forward', 2, epoch=old_epoch) == (0, 0, 0)
    assert drive(c, identity, 'stop', 3, epoch=old_epoch) == (0, 0, 0)
    assert drive(c, identity, 'forward', 4, intent=2)[0] > 0


def test_release_rejects_even_a_later_packet_from_same_press(controller):
    c = controller
    identity = ready(c)
    assert drive(c, identity, 'forward', 1)[0] > 0
    assert drive(c, identity, 'stop', 2) == (0, 0, 0)
    assert drive(c, identity, 'forward', 3) == (0, 0, 0)
    assert drive(c, identity, 'forward', 4, intent=2)[0] > 0


def test_delayed_first_packet_expires_even_if_release_was_lost(controller, monkeypatch):
    c = controller
    identity = ready(c)
    monkeypatch.setattr(c.control_loop.__globals__['time'], 'monotonic', lambda: 100.2)
    c.evidence_at = c.velocity_at = 100.2
    assert drive(c, identity, 'forward', 1, deadline=100.1) == (0, 0, 0)
    assert drive(c, identity, 'forward', 2, intent=2, deadline=100.9)[0] > 0


def test_delivery_cannot_extend_the_original_command_deadline(controller, monkeypatch):
    c = controller
    identity = ready(c)
    assert drive(c, identity, 'forward', 1, deadline=100.2)[0] > 0
    monkeypatch.setattr(c.control_loop.__globals__['time'], 'monotonic', lambda: 100.21)
    c.evidence_at = c.velocity_at = 100.21
    c.control_loop()
    assert c.output[-1].linear.x == 0
    assert c.interruption_reason == 'manual_command_timeout'


def test_manual_timeout_invalidates_intent_before_a_delayed_refresh(controller, monkeypatch):
    c = controller
    identity = ready(c)
    epoch = c.control_lease.motion_epoch
    assert drive(c, identity, 'forward', 1)[0] > 0
    monkeypatch.setattr(c.control_loop.__globals__['time'], 'monotonic', lambda: 100.71)
    c.velocity_at = c.evidence_at = 100.71
    c.control_loop()
    assert c.output[-1].linear.x == 0
    assert c.control_lease.motion_epoch != epoch
    assert drive(c, identity, 'forward', 2, epoch=epoch) == (0, 0, 0)


def test_lease_expiry_and_estop_prevent_output(controller, monkeypatch):
    c = controller
    identity = ready(c)
    assert drive(c, identity, 'forward', 1)[0] > 0
    c.on_emergency_stop(NS(data=True))
    assert drive(c, identity, 'forward', 2) == (0, 0, 0)
    assert c.control_lease.owner is None
    c.emergency_stop = False
    c.on_mode(NS(data='stop'))
    identity = ready(c)
    monkeypatch.setattr(c.control_loop.__globals__['time'], 'monotonic', lambda: 103.01)
    c.velocity_at = c.evidence_at = 103.01
    assert drive(c, identity, 'forward', 3) == (0, 0, 0)
    assert c.control_lease.owner is None


def test_full_recovery_needs_stopped_confirmation_with_current_token(controller):
    c = controller
    identity = ready(c, 'full')
    assert drive(c, identity, 'forward', 1) == (0, 0, 0)
    assert c.recovery_required
    c.interrupt_intent('speed_scale_invalid')
    assert c.recovery_required  # Another stop cause cannot clear the full latch.
    c.pose = c.evidence_pose = (0, 0, 0)
    c.publish_avoidance_status()
    status = json.loads(c.output[-1].data)
    assert status['sensors_ready'] and not status['available'] and status['recovery_required']
    assert drive(c, identity, 'forward', 2, intent=2) == (0, 0, 0)
    c.on_mode(NS(data='stop'))
    request = {'settings': c.avoidance.settings, 'request_id': 'recover', 'robot_radius_m': .25,
               'recovery_epoch': 'obsolete'}
    c.on_avoidance_config(NS(data=json.dumps(request)))
    assert c.recovery_required
    request['recovery_epoch'] = c.control_lease.motion_epoch
    c.on_avoidance_config(NS(data=json.dumps(request)))
    assert not c.recovery_required
    assert c.manual_command == 'stop' and c.last_navigation_time == 0


@pytest.mark.parametrize('motion,blocked', [
    ({**ZERO, 'linear_x': .08}, True),
    ({**ZERO, 'linear_x': -.08}, False),
    ({**ZERO, 'linear_y': .08}, False),
    ({**ZERO, 'angular_z': .3}, True),
])
def test_directional_escape_and_rotating_corners(motion, blocked):
    c = AvoidanceController()
    c.footprint = Rectangle(.0935, .1565, .10)
    evidence = scene(obstacles=((.13, .07, .01),))
    result = local_guard(c, motion, evidence=evidence, scan_age=.02, speed=0., angular=0., velocity_age=.02)
    assert (result == ZERO) == blocked


def test_stale_scan_is_not_renewed_by_new_velocity():
    c = AvoidanceController()
    result = local_guard(c, {**ZERO, 'linear_x': .1}, evidence=scene(obstacles=()),
                         scan_age=.601, speed=0., angular=0., velocity_age=0.)
    assert result == ZERO and c.state == 'sensor_fault'


def test_velocity_is_usable_with_invalid_pose_but_not_invalid_frame_or_twist():
    msg = NS(header=NS(stamp=NS(sec=100, nanosec=0)), child_frame_id='base_link',
             pose=None, twist=NS(twist=NS(linear=NS(x=.1, y=.2), angular=NS(z=.3))))
    assert velocity_evidence(msg, 100.1, 5.)[0] == pytest.approx(math.hypot(.1, .2))
    msg.child_frame_id = 'untrusted'
    with pytest.raises(ValueError): velocity_evidence(msg, 100.1, 5.)
    msg.child_frame_id = 'base_link'
    msg.twist.twist.angular.z = math.nan
    with pytest.raises(ValueError): velocity_evidence(msg, 100.1, 5.)


def test_lateral_motion_is_never_confirmed_stationary():
    odom = {'ok': True, 'odom_age_sec': .01, 'linear_speed': 0., 'linear_speed_xy': .2, 'angular_speed': 0.}
    assert not stationary_evidence((10.2, odom), 10., 10.3)
    del odom['linear_speed_xy']
    assert not stationary_evidence((10.2, odom), 10., 10.3)


def test_old_search_gate_cannot_block_or_rearm_new_manual_owner():
    lease, gate = ControlLease(), SearchGate()
    claim = {'controller_id': lease.controller_id, 'control_epoch': lease.epoch, 'owner': 'search',
             'sequence': 0, 'op': 'acquire', 'purpose': 'navigation'}
    assert lease.update(claim, 0., True)
    message = {'controller_id': gate.instance_id, 'control_epoch': lease.epoch, 'run_id': 'old',
               'version': 1, 'op': 'arm', 'control_lease': {k: claim[k] for k in ('controller_id', 'control_epoch', 'owner')}}
    assert gate.update(message, 0., True, lease=lease)
    assert gate.blocked_for(lease, 'navigation', .1)
    lease.revoke('operator_stop')
    assert lease.update({**claim, 'control_epoch': lease.epoch, 'owner': 'manual', 'purpose': 'manual'}, .2, True)
    assert not gate.blocked_for(lease, 'manual', .3)
    assert not gate.update({**message, 'version': 999, 'op': 'hold'}, .3, True, lease=lease)


def test_basic_scan_path_does_not_request_odom_tf(controller):
    c = controller
    ready(c)
    requested = []
    def transform(parent, child, stamp):
        requested.append((parent, child))
        if parent == 'odom': raise RuntimeError('no global/odom pose')
        return NS(transform=NS(translation=NS(x=0., y=0.), rotation=NS(x=0., y=0., z=0., w=1.)))
    c.tf_buffer = NS(lookup_transform=transform)
    scan = NS(header=NS(stamp=NS(sec=100, nanosec=0), frame_id='laser'), angle_min=-math.pi,
              angle_increment=math.tau/720, range_min=.01, range_max=12., ranges=[3.]*720)
    c.on_scan(scan)
    assert c.scan_evidence is not None
    assert requested == [('base_link', 'laser')]


def test_setting_change_is_rejected_while_moving_without_losing_applied_config(controller):
    c = controller
    ready(c)
    before = dict(c.avoidance.settings)
    c.on_avoidance_config(NS(data=json.dumps({'settings': {**before, 'protection_mode': 'full'},
        'request_id': 'moving-change', 'robot_radius_m': .25})))
    assert c.avoidance.settings == before and c.avoidance_confirmed
    assert c.rejected_request_id == 'moving-change'


def test_bad_speed_setting_stops_instead_of_becoming_full_speed(controller):
    c = controller
    identity = ready(c)
    assert drive(c, identity, 'forward', 1)[0] > 0
    epoch = c.control_lease.motion_epoch
    c.on_speed_scale(NS(data=math.nan))
    c.control_loop()
    assert c.speed_scale == 0 and c.output[-1].linear.x == 0
    assert c.control_lease.motion_epoch != epoch


def test_velocity_transport_delay_does_not_refresh_old_measurement(fake_node, tmp_path):
    from smart_car_decision.avoidance_settings import AvoidanceService
    service = AvoidanceService(fake_node, tmp_path/'settings.json', lambda _: None, lambda: 10.)
    service.observe({'confirmed': True, 'velocity': {'ok': True, 'measured_at': 9.4,
        'age_sec': .01, 'linear_speed_xy': 0., 'angular_speed': 0.}})
    assert not service.snapshot()['velocity']['ok']


def test_rejected_setting_restores_effective_preference_instead_of_showing_it_applied(fake_node, tmp_path):
    from smart_car_decision.avoidance_settings import AvoidanceService
    service = AvoidanceService(fake_node, tmp_path/'settings.json', lambda _: None, lambda: 10.)
    rejected = service.request_id
    service.observe({'confirmed': True, 'request_id': 'applied', 'rejected_request_id': rejected,
        'settings': dict(DEFAULTS), 'robot_radius_m': .25, 'config_rejection': 'still moving'})
    assert service.request_id == 'applied' and service.requested == DEFAULTS
    assert service.snapshot()['confirmed']


def test_navigation_safety_stop_revokes_lease_until_explicit_restart(controller):
    c = controller
    ready(c)
    c.control_lease.revoke()
    lease = c.control_lease
    identity = {'controller_id': lease.controller_id, 'control_epoch': lease.epoch, 'owner': 'navigation'}
    c.on_mode(NS(data='stop'))
    c.on_control_lease(NS(data=json.dumps({**identity, 'purpose': 'navigation', 'op': 'acquire', 'sequence': 0})))
    c.on_mode(NS(data='navigation'))
    c.navigation_motion = {**ZERO, 'linear_x': .1}
    c.last_navigation_time = 100.
    c.control_loop()
    assert c.output[-1].linear.x > 0
    c.scan_evidence = None
    c.control_loop()
    assert c.output[-1].linear.x == 0 and lease.owner is None
    c.scan_evidence = scene(obstacles=())
    c.on_navigation_command(NS(linear=NS(x=.1, y=0.), angular=NS(z=0.)))
    c.control_loop()
    assert c.output[-1].linear.x == 0


@pytest.mark.parametrize('mode', ['auto', 'color_track', 'object_follow'])
def test_task_modes_keep_their_required_input_gate_under_basic_profile(controller, mode):
    c = controller
    ready(c)
    c.control_lease.revoke()
    c.on_mode(NS(data='stop'))
    lease = c.control_lease
    c.on_control_lease(NS(data=json.dumps({'controller_id': lease.controller_id, 'control_epoch': lease.epoch,
        'owner': 'task', 'purpose': mode, 'sequence': 0, 'op': 'acquire'})))
    c.on_mode(NS(data=mode))
    c.last_detection_time = c.last_lane_time = 0.
    c.control_loop()
    assert c.output[-1].linear.x == 0 and lease.owner is None
    assert c.avoidance.settings['protection_mode'] == 'basic'


@pytest.mark.parametrize("fault", [None, "foreign_owner", "estop", "stale_epoch"])
def test_navigation_park_is_fenced_and_changes_mode_with_stop_ack(controller, fault):
    c = controller
    identity = ready(c)
    c.emergency_stop = fault == "estop"
    expected = dict(identity)
    if fault == "foreign_owner":
        expected["owner"] = "foreign"
    if fault == "stale_epoch":
        expected["control_epoch"] = "old"
    payload = {**expected, "op": "stop", "navigation_park": True, "request_id": "park"}
    c.on_control_lease(NS(data=json.dumps(payload)))
    if fault:
        assert c.mode == "manual" and c.control_lease.owner == "host"
        assert c.control_lease.rejected_request_id == "park"
    else:
        assert c.mode == "stop" and c.operator_stop and c.stationary()
        assert c.control_lease.owner is None and c.control_lease.epoch != identity["control_epoch"]
        assert c.control_lease.last_request_id == "park"
