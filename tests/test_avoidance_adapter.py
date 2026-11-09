"""Run the real ROS adapter methods with transport replaced, without a ROS install."""
import ast
import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace as NS

import pytest

from smart_car_decision.avoidance import AvoidanceController, ZERO
from smart_car_decision.avoidance_settings import AvoidanceSettings, DEFAULTS
from test_avoidance import scene


@pytest.fixture
def controller(monkeypatch, tmp_path):
    def module(name, **values):
        value = ModuleType(name)
        value.__dict__.update(values)
        monkeypatch.setitem(sys.modules, name, value)
    class Stamp:
        def __init__(self, nanoseconds=100_000_000_000):
            self.nanoseconds = nanoseconds

        def __sub__(self, other):
            return NS(nanoseconds=self.nanoseconds-other.nanoseconds)

        @staticmethod
        def from_msg(message):
            return Stamp(message.sec*1_000_000_000+message.nanosec)
    class Message:
        data = ''
    class Twist:
        def __init__(self):
            self.linear = NS(x=0., y=0.)
            self.angular = NS(z=0.)
    module('rclpy')
    module('rclpy.node', Node=object)
    module('rclpy.qos', QoSProfile=object, DurabilityPolicy=NS(TRANSIENT_LOCAL=1), qos_profile_sensor_data=object())
    module('rclpy.time', Time=Stamp)
    module('tf2_ros', Buffer=object, TransformListener=object,
           ExtrapolationException=type('ExtrapolationException',(Exception,),{}))
    module('geometry_msgs.msg', Twist=Twist)
    module('nav_msgs.msg', Odometry=object)
    module('sensor_msgs.msg', LaserScan=object)
    module('std_msgs.msg', Bool=Message, Float32=Message, String=Message)
    path = Path(__file__).resolve().parents[1]/'ros2_ws/src/smart_car_decision/smart_car_decision/decision_controller.py'
    spec = importlib.util.spec_from_file_location('smart_car_decision._test_controller', path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    monkeypatch.setattr(loaded.time, 'monotonic', lambda: 100.)
    c = loaded.DecisionController.__new__(loaded.DecisionController)
    c.__dict__.update(mode='stop', emergency_stop=False, operator_stop=True, manual_command='stop',
                      follow_targets={'color_track':(False,0.),'object_follow':(False,0.)},
                      avoidance=AvoidanceController(), avoidance_config=AvoidanceSettings(tmp_path/'settings.json'),
                      avoidance_confirmed=False, avoidance_request_id=None, avoidance_instance_id='instance',
                      scan_evidence=scene(obstacles=()), evidence_at=100., evidence_pose=(0,0,0), pose=(0,0,0), odom_at=100.,
                      actual_speed=0., actual_angular=0., front_distance=3., last_scan_time=100.,
                      front_center=0., front_angle=.6, front_distance_percentile=20,
                      detection='', last_detection_time=100., lane_offset=0., last_lane_time=100.,
                      last_manual_time=100., navigation_motion=None, last_navigation_time=0.,
                      speed_scale=1., manual_turn_speed=.25, scan_timeout_sec=.6, command_timeout_sec=.7,
                      detection_timeout_sec=1.5, lane_timeout_sec=.5, navigation_timeout_sec=.5,
                      obstacle_stop_distance=.45, obstacle_slow_distance=.75, mode_obstacle_stop_distances={'manual':0},
                      cruise_speed=.28, slow_speed=.12, turn_speed=1., lane_kp=.9, max_angular_speed=1.2)
    c.get_clock = lambda: NS(now=lambda: Stamp())
    c.logs = []
    c.get_logger = lambda: NS(info=c.logs.append)
    output = []
    c.publisher = NS(publish=output.append)
    c.avoidance_status_pub = NS(publish=output.append)
    c.output = output
    return c


def test_live_controller_stop_records_actual_output_without_changing_twist(controller):
    from smart_car_decision.motion_diagnostics import MotionDiagnostics

    class Sink:
        enabled = True
        events = []

        def emit(self, kind, reason, **values):
            self.events.append((kind, reason, values))

    c = controller
    config(c)
    c.publish_rate_hz = 20.0
    c.on_mode(NS(data='manual'))
    c.on_manual_command(NS(data='forward'))
    c.control_loop()
    original = c.output[-1].linear.x
    c.motion_diagnostics = MotionDiagnostics(Sink())
    c.control_loop()
    assert original > 0
    assert c.output[-1].linear.x == original
    c.on_emergency_stop(NS(data=True))
    c.control_loop()
    assert c.output[-1].linear.x == 0
    assert c.motion_diagnostics.sink.events[0][:2] == ('motion.zero', 'emergency_stop')


def config(c, **changes):
    value = {'request_id': 'request', 'settings': dict(DEFAULTS), 'robot_radius_m': .25}
    value.update(changes)
    c.on_avoidance_config(NS(data=json.dumps(value)))


def test_navigation_bound_cannot_shrink_below_measured_body(controller):
    from smart_car_decision.footprint import Rectangle
    controller.avoidance.footprint=Rectangle(.0935,.2065,.1)
    config(controller,robot_radius_m=.2)
    assert not controller.avoidance_confirmed
    assert controller.avoidance.radius==.25


def test_controller_ack_requires_stationary_and_persists_only_valid_settings(controller):
    c = controller
    c.actual_speed = .03
    config(c)
    assert not c.avoidance_confirmed
    c.actual_speed = 0
    config(c, settings={'enabled':False, 'trigger_distance_m':.8}, robot_radius_m=.35)
    assert c.avoidance_confirmed and c.avoidance.radius == .35
    assert AvoidanceSettings(c.avoidance_config.path).value['enabled'] is False
    c.publish_avoidance_status()
    status = json.loads(c.output[-1].data)
    assert status['confirmed'] and status['request_id'] == 'request' and status['robot_radius_m'] == .35


def test_restart_waits_for_ack_and_release_stops_real_control_loop(controller):
    c = controller
    c.publish_rate_hz = 20.
    c.on_mode(NS(data='manual'))
    c.on_manual_command(NS(data='forward'))
    c.control_loop()
    assert c.output[-1].linear.x == 0
    c.on_mode(NS(data='stop'))
    config(c)
    c.on_mode(NS(data='manual'))
    c.on_manual_command(NS(data='forward'))
    c.control_loop()
    assert c.output[-1].linear.x > 0
    c.on_manual_command(NS(data='stop'))
    c.control_loop()
    assert c.output[-1].linear.x == 0 and c.output[-1].angular.z == 0
    assert c.avoidance.anchor is None


def test_out_of_order_manual_packet_cannot_restart_motion_after_release(controller):
    from smart_car_decision.control_lease import ControlLease

    c = controller
    config(c)
    c.control_lease = lease = ControlLease()
    c.publish_rate_hz = 20.0
    c.actual_angular_speed = 0.0
    identity = {"controller_id": lease.controller_id, "control_epoch": lease.epoch, "owner": "operator"}
    c.on_control_lease(NS(data=json.dumps({**identity, "sequence": 0, "op": "acquire", "purpose": "manual"})))
    c.on_mode(NS(data="manual"))

    def drive(command, seq):
        c.on_manual_command(NS(data=json.dumps({**identity, "command": command, "drive_seq": seq})))
        c.control_loop()
        return c.output[-1].linear.x

    assert drive("forward", 1) > 0
    assert drive("stop", 3) == 0
    assert drive("forward", 2) == 0
    assert drive("forward", 4) > 0
    c.on_mode(NS(data="stop"))
    c.on_mode(NS(data="manual"))
    assert drive("forward", 5) == 0


def test_exact_scan_transform_failure_and_stamp_reject_motion(controller):
    c = controller
    calls = []
    def transform(parent, child, stamp):
        calls.append((parent, child, stamp.nanoseconds))
        return NS(transform=NS(translation=NS(x=0.,y=0.), rotation=NS(x=0.,y=0.,z=0.,w=1.)))
    c.tf_buffer = NS(lookup_transform=transform)
    scan = NS(angle_min=0., angle_increment=.01, range_min=.01, range_max=12., ranges=[3.]*629,
              header=NS(frame_id='laser',stamp=NS(sec=100,nanosec=0)))
    c.on_scan(scan)
    assert c.scan_evidence is not None and calls[0] == ('base_link', 'laser', 100_000_000_000)
    assert calls[1] == ('odom', 'base_link', 100_000_000_000)
    scan.header.stamp.sec = 99
    c.on_scan(scan)
    assert c.scan_evidence is None
    scan.header.stamp.sec = 100
    c.tf_buffer.lookup_transform = lambda *args: (_ for _ in ()).throw(RuntimeError('missing TF'))
    c.on_scan(scan)
    assert c.scan_evidence is None


def test_future_tf_retries_exact_scan_without_renewing_old_evidence(controller):
    c=controller;c.publish_rate_hz=20.
    scan=NS(angle_min=0.,angle_increment=.01,range_min=.01,range_max=12.,ranges=[3.]*629,
            header=NS(frame_id='laser',stamp=NS(sec=100,nanosec=0)))
    error=c.on_scan.__globals__['ExtrapolationException']
    c.tf_buffer=NS(lookup_transform=lambda *a: (_ for _ in ()).throw(error('extrapolation into the future')))
    previous=c.scan_evidence;c.evidence_at=99.8
    c.on_scan(scan)
    assert c.scan_evidence is previous and c.evidence_at==99.8 and c._pending_tf_scan is scan
    c.on_scan(scan)
    assert c.evidence_at==99.8
    c.tf_buffer.lookup_transform=lambda *a: NS(transform=NS(translation=NS(x=0.,y=0.),rotation=NS(x=0.,y=0.,z=0.,w=1.)))
    c.control_loop()
    assert c._pending_tf_scan is None and c.scan_evidence is not previous and c.evidence_at==100.


def test_future_tf_cannot_keep_expired_evidence_alive(controller):
    c=controller;c.evidence_at=99.
    error=c.on_scan.__globals__['ExtrapolationException']
    c.tf_buffer=NS(lookup_transform=lambda *a: (_ for _ in ()).throw(error('extrapolation into the future')))
    scan=NS(angle_min=0.,angle_increment=.01,range_min=.01,range_max=12.,ranges=[3.]*629,
            header=NS(frame_id='laser',stamp=NS(sec=100,nanosec=0)))
    c.on_scan(scan)
    assert c.scan_evidence is None and c.evidence_at==99.


def test_odometry_does_not_wait_for_a_later_tf_publication(controller):
    c = controller
    c.tf_buffer = NS(lookup_transform=lambda *args: (_ for _ in ()).throw(RuntimeError('TF not broadcast yet')))
    odom = NS(header=NS(frame_id='odom',stamp=NS(sec=100,nanosec=0)), child_frame_id='base_link',
              pose=NS(pose=NS(position=NS(x=.02,y=.01),orientation=NS(x=0.,y=0.,z=0.,w=1.))),
              twist=NS(twist=NS(linear=NS(x=.1,y=0.),angular=NS(z=0.))))
    c.on_avoidance_odom(odom)
    assert c.pose == (.02,.01,0.) and c.actual_speed == .1


@pytest.mark.parametrize('mode', ['color_track', 'object_follow'])
def test_target_loss_cancels_detour_before_stale_offsets_can_move(controller, mode):
    c = controller
    c.publish_rate_hz = 20.
    config(c)
    c.on_mode(NS(data=mode))
    if mode == 'color_track':
        c.on_color_target(NS(data='{"found":true}'))
    else:
        c.on_tracking_target(NS(data='{"locked":true,"visible":true}'))
    c.on_lane_offset(NS(data=0.))
    c.control_loop()
    assert c.output[-1].linear.x > 0
    if mode == 'color_track':
        c.on_color_target(NS(data='{"found":false}'))
    else:
        # Retaining the track ID is not proof that this frame sees the person.
        c.on_tracking_target(NS(data='{"locked":true,"visible":false}'))
    c.on_lane_offset(NS(data=0.))  # delayed cached offset must not override lost target
    c.control_loop()
    assert c.output[-1].linear.x == 0 and c.output[-1].angular.z == 0
    assert c.avoidance.anchor is None


def test_only_decision_controller_publishes_twist():
    directory = Path(__file__).resolve().parents[1]/'ros2_ws/src/smart_car_decision/smart_car_decision'
    publishers = []
    for path in directory.glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'create_publisher' and node.args:
                if isinstance(node.args[0], ast.Name) and node.args[0].id == 'Twist':
                    publishers.append(path.name)
    assert publishers == ['decision_controller.py']
