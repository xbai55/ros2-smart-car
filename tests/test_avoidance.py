import math
import json
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from smart_car_decision.avoidance import AvoidanceController, ScanEvidence, ZERO
from smart_car_decision.avoidance_settings import AvoidanceService, AvoidanceSettings, DEFAULTS, validate_settings
from smart_car_decision.control_policy import decide_motion
from smart_car_decision.scan_visualization import simplify_scan_points

def detour_controller(*args, **kwargs):
    # These tests exercise the explicitly enabled planner, not product defaults.
    value = AvoidanceController(*args, **kwargs)
    value.settings['enabled'] = True
    return value



def scene(pose=(0, 0, 0), obstacles=((.8, 0, .10),), sequence=1, yaw=0):
    """Full raw scan, ray-cast against circular obstacles and a 8x8 m room."""
    ranges = []
    for i in range(720):
        angle = -math.pi + i * math.tau / 720 + pose[2] + yaw
        dx, dy = math.cos(angle), math.sin(angle)
        walls = [((4 if d > 0 else -4) - p) / d for d, p in ((dx, pose[0]), (dy, pose[1])) if abs(d) > 1e-9]
        distance = min(v for v in walls if v > 0)
        for x, y, radius in obstacles:
            ox, oy = pose[0] - x, pose[1] - y
            b, c = ox * dx + oy * dy, ox * ox + oy * oy - radius * radius
            disc = b * b - c
            if disc >= 0:
                hit = -b - math.sqrt(disc)
                if hit > .01:
                    distance = min(distance, hit)
        ranges.append(distance)
    scan = NS(angle_min=-math.pi, angle_increment=math.tau / 720, range_min=.01, range_max=12,
              ranges=ranges, header=NS(stamp=NS(sec=sequence, nanosec=0)))
    return ScanEvidence(scan, (0, 0, yaw))


FORWARD = {**ZERO, 'linear_x': .28}


def test_avoidance_matches_established_cloud_rotation_after_origin_correction():
    data=json.loads((Path(__file__).parent/'fixtures/avoidance-scan-20261028.json').read_text())
    scan=NS(**{k:data[k] for k in ('angle_min','angle_increment','range_min','range_max')},
            ranges=[float(v) for v in data['ranges']],header=NS(stamp=NS(**data['stamp'])))
    evidence=ScanEvidence(scan,data['transform'])
    cloud=simplify_scan_points(scan,max_points=len(scan.ranges),rotation_rad=math.pi)
    assert len(cloud)==len(evidence.points)
    tx,ty,_=data['transform']
    assert max(math.hypot(x-tx-p['x'],y-ty-p['y']) for (x,y),p in zip(evidence.points,cloud))<.00072


def test_rear_obstacle_does_not_veto_side_selection_but_turn_still_checks_it():
    evidence=scene(obstacles=((.8,0,.1),(-.3,0,.02)))
    c=detour_controller()
    assert c.choose(evidence,(0,0,0),.4)
    c.actual_speed,c.scan_age=0.,.05
    assert c.guard({**ZERO,'angular_z':.1},evidence,.4)==ZERO
    assert c.coverage['motion']=='turn' and c.blocking_point[0]<0


def test_overlap_clearance_is_zero_not_artificial_fifteen_centimeters():
    c=detour_controller()
    assert step(c,scene(obstacles=((.2,0,.01),)))==ZERO
    assert c.front==0 and c.blocking_point[0]>0


def test_recorded_scan_keeps_unclassified_close_returns_blocked():
    data = json.loads((Path(__file__).parent/'fixtures/avoidance-scan-20261028.json').read_text())
    scan = NS(**{k:data[k] for k in ('angle_min','angle_increment','range_min','range_max')},
              ranges=[float(v) for v in data['ranges']], header=NS(stamp=NS(**data['stamp'])))
    evidence = ScanEvidence(scan, data['transform'])
    assert len(evidence.rays) == 1080
    assert any(v is None for v in evidence.rays)
    assert min(math.hypot(*p) for p in evidence.points) < .15
    c = detour_controller()
    assert step(c, evidence) == ZERO
    assert '安全余量' in c.reason


def test_directional_unknown_rear_does_not_block_straight_forward():
    evidence = scene(obstacles=())
    # Include the side boundary ray wedges required by the swept margin.
    evidence.rays = [v if math.cos(evidence.start+i*evidence.increment) >= -.1 else None
                     for i, v in enumerate(evidence.rays)]
    assert not evidence.free_disk(0, 0, .4)
    c = detour_controller()
    assert step(c, evidence)['linear_x'] > 0
    c.reset()
    assert c.step({**ZERO, 'linear_x': -.1}, mode='manual', now=0,
                  evidence=evidence, scan_age=.05, pose=(0, 0, 0), odom_age=.05) == ZERO
    c.reset()
    assert c.step({**ZERO, 'angular_z': .1}, mode='manual', now=0,
                  evidence=evidence, scan_age=.05, pose=(0, 0, 0), odom_age=.05) == ZERO


def test_directional_check_keeps_real_near_returns_and_unknown_front():
    evidence = scene(obstacles=((.35, 0, .02),))
    assert step(detour_controller(), evidence) == ZERO


def test_straight_motion_can_separate_from_rear_bag_but_cannot_reverse_into_it():
    evidence = scene(obstacles=((-0.30, 0, .03),))
    c = detour_controller()
    assert step(c, evidence)['linear_x'] > 0
    assert not evidence.directional_collision_free(0, 0, .4, (-.1, 0))
    assert not evidence.directional_collision_free(-.05, 0, .4, (-.1, 0))
    assert evidence.directional_collision_free(.05, 0, .4, (.1, 0))


def test_detour_selects_only_observed_prefix_not_occluded_far_waypoints():
    evidence = scene()
    original = evidence.observed
    evidence.observed = lambda x,y: math.hypot(x,y) <= .70 and original(x,y)
    c = detour_controller()
    assert c.choose(evidence, (0,0,0), .4)
    assert not evidence.free_segment(c.path[0], c.path[1], .4)
    # The unobserved continuation must still fail the execution guard.
    evidence.rays = [None]*len(evidence.rays)
    c.actual_speed, c.scan_age = 0., .05
    assert c.guard(FORWARD, evidence, .4) == ZERO
    evidence = scene(obstacles=())
    evidence.rays[360] = None
    assert step(detour_controller(), evidence) == ZERO


def test_stop_reason_survives_release():
    controller = detour_controller()
    controller.step(FORWARD, mode='manual', now=0, evidence=None, scan_age=1,
                    pose=None, odom_age=1)
    previous = controller.status()['last_stop_event']
    controller.step(ZERO, mode='manual', now=.1, evidence=None, scan_age=1,
                    pose=None, odom_age=1)
    assert controller.status()['state'] == 'idle'
    assert controller.status()['last_stop_event'] == previous
    assert previous['state'] == 'sensor_fault'


def step(controller, evidence=None, **changes):
    args = dict(mode='manual', now=0, evidence=evidence or scene(), scan_age=.05,
                pose=(0, 0, 0), odom_age=.05, confirmed=True)
    args.update(changes)
    return controller.step(FORWARD, **args)


@pytest.mark.parametrize('mode', ['manual', 'mapping', 'auto', 'color_track', 'object_follow'])
def test_two_distinct_scans_required_and_all_modes_choose(mode):
    c = detour_controller()
    assert c.settings == {**DEFAULTS, "enabled": True}
    e = scene()
    assert step(c, e, mode=mode) == ZERO
    step(c, e, mode=mode, now=.05)
    assert c.state == 'assessing'  # 20 Hz control must not count the same 7 Hz scan twice.
    step(c, scene(sequence=2), mode=mode, now=.15)
    assert c.direction == 'left' and c.path


def test_right_chosen_when_left_path_obstructed():
    c = detour_controller()
    obstacles = ((.8, 0, .1), (.5, .65, .25), (.1, .8, .2))
    step(c, scene(obstacles=obstacles))
    step(c, scene(obstacles=obstacles, sequence=2), now=.15)
    assert c.direction == 'right'


def test_both_sides_blocked_latches_until_stop():
    c = detour_controller()
    obstacles = ((.8, 0, .1), (.5, .65, .25), (.5, -.65, .25))
    step(c, scene(obstacles=obstacles))
    assert step(c, scene(obstacles=obstacles, sequence=2), now=.15) == ZERO
    assert c.state == 'blocked'
    assert step(c, scene(obstacles=(), sequence=3), now=.3) == ZERO
    c.step(ZERO, mode='manual', now=.4, evidence=None, scan_age=1, pose=None, odom_age=1)
    assert step(c, scene(obstacles=(), sequence=4), now=.5)['linear_x'] > 0


@pytest.mark.parametrize('change', [{'scan_age': .61}, {'odom_age': .51}, {'pose': None}, {'confirmed': False}, {'evidence': None}])
def test_unavailable_inputs_stop(change):
    c = detour_controller()
    args = dict(mode='manual', now=0, evidence=scene(obstacles=()), scan_age=.05, pose=(0, 0, 0), odom_age=.05)
    args.update(change)
    assert c.step(FORWARD, **args) == ZERO


def test_nan_inf_and_missing_scan_not_clear_space():
    evidence = scene(obstacles=())
    evidence.rays = [None] * len(evidence.rays)
    assert not evidence.free_disk(0, 0, .4)
    assert step(detour_controller(), evidence) == ZERO


def test_reverse_mounting_and_single_small_return():
    a, b = scene(), scene(yaw=math.pi)
    assert a.front_clearance(.25) == pytest.approx(b.front_clearance(.25), abs=.01)
    e = scene(obstacles=())
    scan = NS(angle_min=0, angle_increment=math.tau/720, range_min=.01, range_max=12,
              ranges=[4.] * 720, header=NS(stamp=NS(sec=1, nanosec=0)))
    scan.ranges[0] = .35
    tiny = ScanEvidence(scan)
    assert tiny.front_clearance(.25) == pytest.approx(.1)
    assert step(detour_controller(), tiny) == ZERO


def test_stamped_scan_can_be_compensated_for_motion_since_capture():
    evidence = scene()
    shifted = evidence.reframe(-.1, 0, 0)
    assert shifted.front_clearance(.25) == pytest.approx(evidence.front_clearance(.25)-.1, abs=.01)
    rotated = evidence.reframe(0, 0, math.pi)
    assert min(x for x,y in rotated.points) < -.65
    assert evidence.origin == (0,0) and shifted.origin == (-.1,0)


def test_disabled_still_blocks_and_navigation_does_not_steer():
    c = detour_controller()
    c.settings['enabled'] = False
    assert step(c, scene(obstacles=((.45, 0, .1),))) == ZERO
    assert c.direction is None
    nav = detour_controller()
    motion = {**ZERO, 'linear_x': .1, 'angular_z': -.1}
    result = nav.step(motion, mode='navigation', now=0, evidence=scene(obstacles=()), scan_age=.05,
                      pose=(0, 0, 0), odom_age=.05)
    assert result == motion and nav.direction is None


@pytest.mark.parametrize('command', ['backward', 'left', 'right', 'turn_l'])
def test_nonforward_commands_never_initiate_detour(command):
    motion = decide_motion(mode='manual', emergency_stop=False, front_distance=1, detection='',
                           manual_command=command, lane_offset=0, has_recent_detection=False,
                           has_recent_manual=True, has_recent_lane=False, apply_obstacle_stop=False)
    c = detour_controller()
    c.step(motion, mode='manual', now=0, evidence=scene(), scan_age=.05, pose=(0,0,0), odom_age=.05)
    assert c.anchor is None


@pytest.mark.parametrize('obstacles', [((.8,0,.1),), ((.8,0,.1),(.5,.65,.25),(.1,.8,.2))])
def test_closed_loop_detour_clears_obstacle_and_recovers_heading(obstacles):
    c = detour_controller()
    pose = [0., 0., 0.]
    speed = 0.
    seen = set()
    collision = False
    for i in range(900):
        now = i * .05
        evidence = scene(tuple(pose), obstacles=obstacles, sequence=i // 3)
        result = step(c, evidence, now=now, pose=tuple(pose), actual_speed=speed)
        seen.add(c.state)
        speed = math.hypot(result['linear_x'], result['linear_y'])
        pose[0] += math.cos(pose[2]) * result['linear_x'] * .05
        pose[1] += math.sin(pose[2]) * result['linear_x'] * .05
        pose[2] += result['angular_z'] * .05
        collision |= any(math.hypot(pose[0]-x, pose[1]-y) < radius+.25+.15-.005 for x,y,radius in obstacles)
        if c.anchor is None and 'recovering' in seen:
            break
    assert not collision
    assert {'turning', 'passing', 'recovering'} <= seen
    assert c.anchor is None, (c.state, c.reason, pose, c.distance)
    assert pose[0] > 1.0 and abs(pose[2]) < .06


def test_a_new_obstacle_during_detour_stops_without_switching_sides():
    c = detour_controller()
    step(c)
    step(c, scene(sequence=2), now=.15)
    selected = c.direction
    assert step(c, scene(obstacles=((.3,0,.1),), sequence=3), now=.3) == ZERO
    assert c.state == 'blocked' and c.direction == selected


def test_a_gap_smaller_than_vehicle_and_margin_is_not_passable():
    c = detour_controller()
    assert step(c, scene(obstacles=((0,.5,.2),(0,-.5,.2))), now=0) == ZERO
    assert c.state == 'blocked'


def test_obstacle_entering_safety_corridor_triggers_before_guard_blocks():
    c = detour_controller()
    evidence = scene(obstacles=((.55,.29,.03),))
    assert evidence.front_clearance(.25) > 2
    assert step(c, evidence) == ZERO
    assert c.state == 'assessing'


def test_timeout_and_odometry_jump_stop():
    c = detour_controller()
    step(c)
    step(c, scene(sequence=2), now=.15)
    assert step(c, scene(sequence=3), now=46) == ZERO and c.state == 'timeout'
    other = detour_controller()
    step(other, scene(obstacles=()))
    assert step(other, scene(obstacles=()), pose=(1, 0, 0), now=.1) == ZERO
    assert other.state == 'sensor_fault'


@pytest.mark.parametrize('mode', ['manual', 'mapping', 'auto', 'color_track', 'object_follow', 'navigation'])
def test_stop_intent_cancels_every_stage(mode):
    c = detour_controller()
    step(c, mode=mode)
    step(c, scene(sequence=2), mode=mode, now=.15)
    for state in ('turning', 'passing', 'recovering', 'blocked', 'timeout'):
        c.state = state
        c.step(ZERO, mode=mode, now=.2, evidence=scene(), scan_age=.05, pose=(0,0,0), odom_age=.05)
        assert c.path == [] and c.anchor is None and c.state == 'idle'


@pytest.mark.parametrize('mode', ['auto', 'color_track', 'object_follow', 'manual', 'navigation'])
def test_explicit_safety_intents_do_not_get_replaced(mode):
    common = dict(mode=mode, emergency_stop=False, front_distance=.5, detection='red_light',
                  manual_command='stop', lane_offset=0, has_recent_detection=False,
                  has_recent_manual=False, has_recent_lane=False, has_recent_navigation=False,
                  apply_obstacle_stop=False)
    assert decide_motion(**common) == ZERO
    common.update(has_recent_detection=True, has_recent_manual=True, has_recent_lane=True, emergency_stop=True)
    assert decide_motion(**common) == ZERO


def test_speed_ratio_and_extra_legacy_stop_do_not_disable_floor():
    c = detour_controller()
    step(c)
    step(c, scene(sequence=2), now=.15)
    # Place car on its first leg with matching heading; output cannot exceed 80%.
    heading = math.atan2(c.path[0][1], c.path[0][0])
    result = step(c, scene(pose=(0,0,heading), sequence=3), now=.2, pose=(0,0,heading))
    # A pose jump must stop even if it would align the candidate path.
    assert result == ZERO and c.state == 'sensor_fault'
    other = detour_controller()
    assert step(other, scene(obstacles=((.45, 0, .05),)), legacy_stop=0) == ZERO


def test_persistence_and_corrupt_file_preserved(tmp_path):
    path = tmp_path/'settings.json'
    settings = AvoidanceSettings(path)
    assert settings.value == DEFAULTS
    settings.save({'enabled': False, 'trigger_distance_m': .8})
    assert AvoidanceSettings(path).value['enabled'] is False
    path.write_text('broken', encoding='utf-8')
    assert AvoidanceSettings(path).error and path.read_text() == 'broken'


@pytest.mark.parametrize('value', [{'enabled': 1, 'trigger_distance_m': .6}, {'enabled': True, 'trigger_distance_m': float('nan')}, {'enabled': False, 'trigger_distance_m': .39}])
def test_settings_validation(value):
    with pytest.raises(ValueError):
        validate_settings(value)


def test_acknowledgement_restart_and_stopped_only(fake_node, tmp_path):
    clock = [0.]
    sent = []
    service = AvoidanceService(fake_node, tmp_path/'settings.json', sent.append, lambda: clock[0])
    assert not service.snapshot()['confirmed']
    service.transmit()
    ack = {'settings': DEFAULTS, 'request_id': service.request_id, 'confirmed': True, 'available': True, 'robot_radius_m': .25}
    service.observe(ack)
    assert service.snapshot()['confirmed']
    service.observe({**ack, 'robot_radius_m': .2})
    assert not service.snapshot()['confirmed']
    service.observe(ack)
    clock[0] = .7
    assert not service.snapshot()['confirmed']
    service.observe({**ack, 'confirmed': False, 'instance_id': 'new-controller'})
    assert not service.snapshot()['confirmed']
    with pytest.raises(RuntimeError):
        service.update({'enabled': False})
    fake_node._ros_status_age_sec = .1
    fake_node.store.update(mode='stop', odom={'ok': True, 'linear_speed_xy': 0., 'angular_speed': 0.})
    assert not service.update({'enabled': False})['confirmed']
    assert sent[-1]['settings']['enabled'] is False
    assert not (tmp_path/'settings.json').exists()  # Only controller may persist/ack.
