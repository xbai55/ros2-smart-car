import json
import math
import time
from pathlib import Path
from uuid import uuid4

import rclpy
from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy
from rclpy.qos import qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener, ExtrapolationException
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, Float32, String

from .common import front_range_statistic, normalize_command
from .control_policy import decide_motion, normalize_mode
from .mapping_settings import turn_speed
from .avoidance import AvoidanceController, ScanEvidence, ZERO, wrap
from .avoidance_settings import AvoidanceSettings, validate_settings
from .footprint import Rectangle
from .search_control import SearchGate
from .diagnostic_log import DiagnosticLog, wire_ids
from .motion_diagnostics import MotionDiagnostics, vector
from .control_lease import ControlLease
from .scan_provenance import visibility
from .scan_health import ScanHealth


class DecisionController(Node):
    def __init__(self):
        super().__init__("decision_controller")
        self._declare_parameters()
        self._load_parameters()

        self.front_distance = float("inf")
        self.last_scan_time = 0.0
        self.detection = ""
        self.last_detection_time = 0.0
        self.lane_offset = 0.0
        self.last_lane_time = 0.0
        self.manual_command = "stop"
        self.last_manual_time = 0.0
        self.mode = "stop"
        self.emergency_stop = False
        self.speed_scale = 1.0
        self.manual_turn_speed = .15
        self.navigation_motion = None
        self.last_navigation_time = 0.0
        self.operator_stop = True
        self.follow_targets = {'color_track': (False, 0.0), 'object_follow': (False, 0.0)}
        self.avoidance = AvoidanceController(float(self.get_parameter('avoidance_robot_radius').value),
                                            motion_model=self.get_parameter('avoidance_motion_model').value)
        self.assume_missing_clear=bool(self.get_parameter('avoidance_assume_missing_clear').value)
        self.avoidance_config = AvoidanceSettings(self.get_parameter('avoidance_settings_path').value)
        self.avoidance.settings = dict(self.avoidance_config.value)
        self.self_returns=[]
        self.footprint_error=None
        calibration_path=Path(self.get_parameter('avoidance_footprint_path').value).expanduser()
        if calibration_path.exists():
            try:
                calibration=json.loads(calibration_path.read_text())
                f=Rectangle(**calibration['rectangle'])
                if f.radius>self.avoidance.radius:raise ValueError('Measured body exceeds navigation bounding radius')
                points=calibration.get('self_returns',[])
                if not all(len(p)==2 and all(math.isfinite(v) for v in p) and f.clearance(p)<=0 for p in points):
                    raise ValueError('Invalid calibrated body returns')
                self.avoidance.footprint=f
                self.self_returns=points
            except Exception as exc:
                self.footprint_error=str(exc)
                self.avoidance_config.error='车体标定配置无效：'+str(exc)
        self.avoidance_confirmed = False
        self.avoidance_request_id = None
        self.avoidance_instance_id = uuid4().hex
        self.scan_evidence = None
        self.evidence_pose = None
        self.evidence_at = 0.0
        self.pose = None
        self.odom_at = 0.0
        self.actual_speed = 0.0
        self.search_gate = SearchGate()
        self.diagnostic_log = DiagnosticLog('controller')
        self.motion_diagnostics = MotionDiagnostics(self.diagnostic_log)
        self.lease_diagnostic_ids = {}
        self.drive_diagnostic_ids = {}
        self.scan_packets = {}
        self.scan_health = ScanHealth()
        self.scan_profile = {}
        profile_path = calibration_path.parent/'scan-no-return-profile.json'
        if profile_path.exists():
            try:
                self.scan_profile=json.loads(profile_path.read_text())
            except (ValueError,OSError):
                self.scan_profile={}
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.publisher = self.create_publisher(Twist, self.cmd_vel_topic, 10)
        self.control_lease = ControlLease()
        self.lease_status_pub = self.create_publisher(String, '/robot/control_lease/status', 10)
        self.create_subscription(String, '/robot/control_lease/request', self.on_control_lease, 10)
        self.create_timer(.1, self.publish_control_lease)
        self.search_status_pub = self.create_publisher(String, '/robot/search/status', 10)
        self.create_subscription(String, '/robot/search/control', self.on_search_control, 10)
        self.create_timer(.1, self.publish_search_status)
        self.create_subscription(LaserScan, self.scan_topic, self.on_scan, qos_profile_sensor_data)
        self.create_subscription(String, '/scan/provenance', self.on_scan_provenance, 10)
        self.create_subscription(Odometry, '/odom', self.on_avoidance_odom, qos_profile_sensor_data)
        durable = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.avoidance_status_pub = self.create_publisher(String, '/robot/avoidance/status', durable)
        self.create_subscription(String, '/robot/avoidance/config', self.on_avoidance_config, durable)
        self.create_timer(.2, self.publish_avoidance_status)
        self.create_subscription(String, self.detection_topic, self.on_detection, 10)
        self.create_subscription(Float32, self.lane_offset_topic, self.on_lane_offset, 10)
        self.create_subscription(String, '/vision/color_target', self.on_color_target, 10)
        self.create_subscription(String, '/vision/tracking_target', self.on_tracking_target, 10)
        self.create_subscription(String, self.manual_cmd_topic, self.on_manual_command, 10)
        self.create_subscription(String, self.mode_topic, self.on_mode, 10)
        self.create_subscription(Bool, self.emergency_stop_topic, self.on_emergency_stop, 10)
        self.create_subscription(Float32, self.speed_scale_topic, self.on_speed_scale, 10)
        self.create_subscription(Float32, "/robot/turn_speed", self.on_turn_speed,
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_subscription(String, self.mode_obstacle_stop_distance_topic, self.on_mode_obstacle_stop_distances, 10)
        self.create_subscription(Twist, self.navigation_cmd_topic, self.on_navigation_command, 10)
        self.create_timer(1.0 / self.publish_rate_hz, self.control_loop)

        self.get_logger().info("Decision controller started")

    def _declare_parameters(self):
        self.declare_parameter("scan_topic", "/scan")
        self.declare_parameter("detection_topic", "/vision/detection")
        self.declare_parameter("lane_offset_topic", "/lane/offset")
        self.declare_parameter("manual_cmd_topic", "/manual_cmd")
        self.declare_parameter("cmd_vel_topic", "/cmd_vel")
        self.declare_parameter("navigation_cmd_topic", "/navigation/cmd_vel")
        self.declare_parameter("navigation_timeout_sec", 0.5)
        self.declare_parameter("mode_topic", "/robot/mode")
        self.declare_parameter("emergency_stop_topic", "/robot/emergency_stop")
        self.declare_parameter("speed_scale_topic", "/robot/speed_scale")
        self.declare_parameter("mode_obstacle_stop_distance_topic", "/robot/mode_obstacle_stop_distances")
        self.declare_parameter("front_angle_deg", 35.0)
        self.declare_parameter("front_center_deg", 180.0)
        self.declare_parameter("front_distance_percentile", 20.0)
        self.declare_parameter("obstacle_stop_distance", 0.45)
        self.declare_parameter("obstacle_slow_distance", 0.75)
        self.declare_parameter("mode_obstacle_stop_distances", "{}")
        self.declare_parameter("cruise_speed", 0.18)
        self.declare_parameter("slow_speed", 0.08)
        self.declare_parameter("turn_speed", 0.75)
        self.declare_parameter("lane_kp", 0.9)
        self.declare_parameter("max_angular_speed", 1.2)
        self.declare_parameter("command_timeout_sec", 0.7)
        self.declare_parameter("detection_timeout_sec", 1.5)
        self.declare_parameter("lane_timeout_sec", 0.5)
        self.declare_parameter("scan_timeout_sec", 0.6)
        self.declare_parameter("publish_rate_hz", 20.0)
        self.declare_parameter('avoidance_robot_radius', .25)
        self.declare_parameter('avoidance_motion_model', 'holonomic')
        self.declare_parameter('avoidance_assume_missing_clear', True)
        self.declare_parameter('avoidance_settings_path', '~/.ros/insightrover/obstacle-avoidance.json')
        self.declare_parameter('avoidance_footprint_path', '~/.ros/insightrover/avoidance-footprint.json')

    def _load_parameters(self):
        self.scan_topic = self.get_parameter("scan_topic").value
        self.detection_topic = self.get_parameter("detection_topic").value
        self.lane_offset_topic = self.get_parameter("lane_offset_topic").value
        self.manual_cmd_topic = self.get_parameter("manual_cmd_topic").value
        self.cmd_vel_topic = self.get_parameter("cmd_vel_topic").value
        self.navigation_cmd_topic = self.get_parameter("navigation_cmd_topic").value
        self.navigation_timeout_sec = float(self.get_parameter("navigation_timeout_sec").value)
        self.mode_topic = self.get_parameter("mode_topic").value
        self.emergency_stop_topic = self.get_parameter("emergency_stop_topic").value
        self.speed_scale_topic = self.get_parameter("speed_scale_topic").value
        self.mode_obstacle_stop_distance_topic = self.get_parameter("mode_obstacle_stop_distance_topic").value
        self.front_angle = math.radians(float(self.get_parameter("front_angle_deg").value))
        self.front_center = math.radians(float(self.get_parameter("front_center_deg").value))
        self.front_distance_percentile = float(self.get_parameter("front_distance_percentile").value)
        self.obstacle_stop_distance = float(self.get_parameter("obstacle_stop_distance").value)
        self.obstacle_slow_distance = float(self.get_parameter("obstacle_slow_distance").value)
        self.mode_obstacle_stop_distances = self._parse_mode_obstacle_stop_distances(
            self.get_parameter("mode_obstacle_stop_distances").value
        )
        self.cruise_speed = float(self.get_parameter("cruise_speed").value)
        self.slow_speed = float(self.get_parameter("slow_speed").value)
        self.turn_speed = float(self.get_parameter("turn_speed").value)
        self.lane_kp = float(self.get_parameter("lane_kp").value)
        self.max_angular_speed = float(self.get_parameter("max_angular_speed").value)
        self.command_timeout_sec = float(self.get_parameter("command_timeout_sec").value)
        self.detection_timeout_sec = float(self.get_parameter("detection_timeout_sec").value)
        self.lane_timeout_sec = float(self.get_parameter("lane_timeout_sec").value)
        self.scan_timeout_sec = float(self.get_parameter("scan_timeout_sec").value)
        self.publish_rate_hz = float(self.get_parameter("publish_rate_hz").value)

    @staticmethod
    def _parse_mode_obstacle_stop_distances(value):
        if isinstance(value, dict):
            raw = value
        else:
            try:
                raw = json.loads(str(value or "{}"))
            except json.JSONDecodeError:
                raw = {}
        distances = {}
        for mode, distance in raw.items():
            normalized = normalize_mode(mode)
            try:
                distances[normalized] = max(0.0, float(distance))
            except (TypeError, ValueError):
                continue
        return distances

    def on_scan(self, scan):
        self._latest_raw_scan=scan
        previous=(self.scan_evidence,self.evidence_at,self.evidence_pose)
        self._pending_tf_scan=None
        self.front_distance = front_range_statistic(
            scan,
            center_angle_rad=self.front_center,
            half_width_rad=self.front_angle,
            percentile=self.front_distance_percentile,
        )
        self.last_scan_time = time.monotonic()
        self.scan_evidence = None
        try:
            if getattr(self,'footprint_error',None):return
            stamp = Time.from_msg(scan.header.stamp)
            age = (self.get_clock().now() - stamp).nanoseconds / 1e9
            if not 0 <= age <= .6:
                return
            transform = self.tf_buffer.lookup_transform('base_link', scan.header.frame_id, stamp).transform
            q = transform.rotation
            values = (transform.translation.x, transform.translation.y, q.x, q.y, q.z, q.w)
            if (not all(math.isfinite(v) for v in values) or abs(q.x) > .08 or abs(q.y) > .08
                    or abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1) > .01):
                return
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            odom_tf = self.tf_buffer.lookup_transform('odom', 'base_link', stamp).transform
            oq = odom_tf.rotation
            self.evidence_pose = (odom_tf.translation.x, odom_tf.translation.y,
                                  math.atan2(2*(oq.w*oq.z+oq.x*oq.y), 1-2*(oq.y*oq.y+oq.z*oq.z)))
            if not all(math.isfinite(v) for v in self.evidence_pose) or abs(oq.x*oq.x+oq.y*oq.y+oq.z*oq.z+oq.w*oq.w-1) > .01:
                return
            key=(scan.header.stamp.sec,scan.header.stamp.nanosec)
            packet=getattr(self,'scan_packets',{}).get(key)
            clear, summary=visibility(scan,packet,getattr(self,'scan_profile',{}))
            if not hasattr(self,'scan_health'):self.scan_health=ScanHealth()
            health=self.scan_health.observe(scan,age)
            matched=summary.get('source')=='driver_provenance'
            assume=getattr(self,'assume_missing_clear',True)
            active=bool(assume and matched and packet.get('healthy') is True and health['ready_for_inference'])
            self.scan_evidence = ScanEvidence(scan, (transform.translation.x, transform.translation.y, yaw),
                                              getattr(self,'self_returns',()),self.avoidance.footprint,
                                              .01 if matched and health['ready_for_inference'] else 0.,
                                              packet['kinds'] if matched else None,
                                              assume_missing_clear=active)
            self.avoidance.missing_data_policy={'mode':'assume_clear' if assume else 'observed_only',
                                                'active':active,'device_proven':False}
            self.avoidance.assumed_clear=self.scan_evidence.assumed_clear
            self.avoidance.scan_provenance=summary
            self.avoidance.scan_health=health
            self.avoidance.sampling_gap_inferred=self.scan_evidence.sampling_gap_inferred
            if clear:
                ranges=list(self.scan_evidence.visibility_ranges)
                for index,distance in clear.items():
                    ranges[index]=distance
                self.scan_evidence._visibility=ranges
            self.evidence_at = time.monotonic() - age
        except Exception as exc:
            # The scan can arrive a few milliseconds before its exact odom TF.
            # Retry that same stamped scan; never substitute a latest-time TF
            # or extend the original evidence's expiry while waiting.
            if isinstance(exc, ExtrapolationException) and 'future' in str(exc).lower():
                self._pending_tf_scan=scan
                if previous[0] is not None and 0 <= time.monotonic()-previous[1] <= .6:
                    self.scan_evidence,self.evidence_at,self.evidence_pose=previous
            else:
                self.scan_evidence = None

    def on_avoidance_odom(self, msg):
        try:
            stamp = Time.from_msg(msg.header.stamp)
            age = (self.get_clock().now() - stamp).nanoseconds / 1e9
            if not 0 <= age <= .5 or msg.header.frame_id != 'odom':
                self.pose = None
                return
            # Use this odometry's pose, not a simultaneous odom->base TF that
            # may still be in transit when the odometry callback fires.
            p, q = msg.pose.pose.position, msg.pose.pose.orientation
            if abs(q.x*q.x+q.y*q.y+q.z*q.z+q.w*q.w-1) > .01:
                raise ValueError('Invalid odometry orientation')
            yaw = math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))
            if msg.child_frame_id == 'base_link':
                tx = ty = rotation = 0.0
            else:
                tf = self.tf_buffer.lookup_transform(msg.child_frame_id, 'base_link', stamp).transform
                cq = tf.rotation
                tx, ty = tf.translation.x, tf.translation.y
                rotation = math.atan2(2*(cq.w*cq.z+cq.x*cq.y), 1-2*(cq.y*cq.y+cq.z*cq.z))
            pose = (p.x+math.cos(yaw)*tx-math.sin(yaw)*ty,
                    p.y+math.sin(yaw)*tx+math.cos(yaw)*ty, wrap(yaw+rotation))
            speed = math.hypot(msg.twist.twist.linear.x, msg.twist.twist.linear.y) + abs(msg.twist.twist.angular.z) * math.hypot(tx, ty)
            self.actual_angular_speed=msg.twist.twist.angular.z
            if not all(math.isfinite(v) for v in (*pose, speed, msg.twist.twist.angular.z)):
                raise ValueError('Non-finite odometry')
            if self.pose is not None and (math.hypot(pose[0]-self.pose[0], pose[1]-self.pose[1]) > .20 or abs(wrap(pose[2]-self.pose[2])) > .5):
                self.avoidance.stop('sensor_fault', '里程计发生跳变，请停止后重试')
            self.pose, self.actual_speed = pose, speed
            self.actual_angular = msg.twist.twist.angular.z
            self.odom_at = time.monotonic() - age
        except Exception:
            self.pose = None

    def on_avoidance_config(self, msg):
        try:
            request = json.loads(msg.data)
            settings = validate_settings(request['settings'])
            request_id = request['request_id']
            radius = request.get('robot_radius_m')
            if isinstance(radius, bool) or not isinstance(radius, (int, float)) or not math.isfinite(radius) or not .01 <= radius <= 2.0:
                raise ValueError('Invalid shared robot radius')
            if self.avoidance.footprint and radius<self.avoidance.footprint.radius:
                raise ValueError('Navigation bounding radius is smaller than measured body')
            if not isinstance(request_id, str) or not request_id:
                raise ValueError('Invalid request ID')
            if (self.avoidance_confirmed and not self.avoidance_config.error and request_id == self.avoidance_request_id
                    and settings == self.avoidance.settings and radius == self.avoidance.radius):
                return
            if self.mode != 'stop' or self.pose is None or time.monotonic()-self.odom_at > .5 or self.actual_speed > .01 or abs(self.actual_angular) > .03:
                return
            if settings != self.avoidance_config.value or self.avoidance_config.error:
                self.avoidance_config.save(settings)
            self.avoidance.settings = settings
            self.avoidance.radius = radius
            self.avoidance.reset()
            self.avoidance_confirmed = True
            self.avoidance_request_id = request_id
        except (ValueError, KeyError, TypeError, OSError) as exc:
            self.avoidance_confirmed = False
            self.avoidance_config.error = '避障设置未生效：' + str(exc)
            self.avoidance.stop('sensor_fault', str(exc))

    def publish_avoidance_status(self):
        now = time.monotonic()
        payload = {**self.avoidance.status(), 'settings': self.avoidance.settings,
                   'request_id': self.avoidance_request_id, 'instance_id': self.avoidance_instance_id,
                   'robot_radius_m': self.avoidance.radius,
                   'confirmed': self.avoidance_confirmed and not self.avoidance_config.error,
                   'available': self.scan_evidence is not None and now-self.evidence_at <= .6 and self.pose is not None and now-self.odom_at <= .5}
        if self.avoidance_config.error:
            payload.update(state='sensor_fault', reason=self.avoidance_config.error)
        transition = (payload['state'], payload['reason'])
        if transition != getattr(self, '_last_avoidance_transition', None):
            self.get_logger().info('avoidance_transition ' + json.dumps({
                'state': payload['state'], 'reason': payload['reason'],
                'build_id': payload.get('build_id'),
                'requested_motion': payload.get('requested_motion'),
                'applied_motion': payload.get('applied_motion')}, ensure_ascii=False))
            self._last_avoidance_transition = transition
        message = String()
        message.data = json.dumps(payload, allow_nan=False)
        self.avoidance_status_pub.publish(message)

    def on_detection(self, msg):
        self.detection = normalize_command(msg.data)
        self.last_detection_time = time.monotonic()

    def on_lane_offset(self, msg):
        self.lane_offset = float(msg.data)
        self.last_lane_time = time.monotonic()

    def update_follow_target(self, mode, valid):
        self.follow_targets[mode] = (valid, time.monotonic())
        if self.mode == mode and not valid:
            self.last_lane_time = 0.0
            self.avoidance.reset()

    def on_color_target(self, msg):
        try:
            value = json.loads(msg.data)
            self.update_follow_target('color_track', value.get('found') is True)
        except (ValueError, TypeError, AttributeError):
            self.update_follow_target('color_track', False)

    def on_tracking_target(self, msg):
        try:
            value = json.loads(msg.data)
            self.update_follow_target('object_follow', value.get('locked') is True and value.get('visible') is True)
        except (ValueError, TypeError, AttributeError):
            self.update_follow_target('object_follow', False)

    def on_manual_command(self, msg):
        now = time.monotonic()
        lease = getattr(self, 'control_lease', None)
        if lease is not None and msg.data != 'stop':
            try:
                intent = json.loads(msg.data)
            except (ValueError, TypeError):
                return
            if not lease.accepts_drive(intent, now, self.mode):
                sink = getattr(self, 'diagnostic_log', None)
                if sink and now - getattr(self, '_last_rejection', 0) >= 1:
                    self._last_rejection = now
                    sink.emit('motion.rejected', 'drive_identity_or_sequence', level='WARN')
                return
            self.drive_diagnostic_ids = wire_ids(intent.get('diagnostic'))
            command = normalize_command(intent.get('command'))
        else:
            command = normalize_command(msg.data)
        if command == 'stop' and msg.data == 'stop':
            self.drive_diagnostic_ids = {}
        if command != self.manual_command:
            self.avoidance.reset()
        self.manual_command = command
        self.last_manual_time = now
        self.operator_stop = self.manual_command == 'stop'
        if self.operator_stop:
            self.avoidance.reset()

    def on_mode(self, msg):
        next_mode = normalize_mode(msg.data)
        if self.mode != next_mode:
            lease = getattr(self, "control_lease", None)
            if lease is not None and self.mode in ("manual", "mapping") and lease.purpose == self.mode:
                lease.revoke("operator_mode_changed")
            self.manual_command = 'stop'
            self.drive_diagnostic_ids = {}
            self.last_manual_time = 0.0
            self.navigation_motion = None
            self.last_navigation_time = 0.0
            self.operator_stop = False
            self.avoidance.reset()
            if next_mode in self.follow_targets:
                self.follow_targets[next_mode] = (False, 0.0)
                self.last_lane_time = 0.0
        self.mode = next_mode

    def on_navigation_command(self, msg):
        if self.mode != "navigation":
            return
        self.navigation_motion = {"linear_x": msg.linear.x, "linear_y": msg.linear.y, "angular_z": msg.angular.z}
        self.last_navigation_time = time.monotonic()

    def on_emergency_stop(self, msg):
        self.emergency_stop = bool(msg.data)
        if self.emergency_stop and getattr(self, 'control_lease', None) is not None:
            self.control_lease.revoke('emergency_stop')

    def on_speed_scale(self, msg):
        self.speed_scale = max(0.0, min(1.0, float(msg.data)))

    def on_turn_speed(self, msg):
        try:
            self.manual_turn_speed = turn_speed(round(float(msg.data), 3))
        except ValueError as exc:
            self.get_logger().warning(str(exc))

    def on_mode_obstacle_stop_distances(self, msg):
        self.mode_obstacle_stop_distances = self._parse_mode_obstacle_stop_distances(msg.data)

    def control_loop(self):
        pending=getattr(self,'_pending_tf_scan',None)
        if pending is not None:self.on_scan(pending)
        now = time.monotonic()
        period=now-getattr(self,'_previous_control_at',now)
        self._previous_control_at=now
        self.control_period_ms=period*1000
        self.control_overruns=getattr(self,'control_overruns',0)+int(period>2./self.publish_rate_hz)
        twist = Twist()
        diagnostics = getattr(self, 'motion_diagnostics', None)
        reasons = [] if diagnostics and diagnostics.sink.enabled else None
        motion = decide_motion(
            mode=self.mode,
            emergency_stop=self.emergency_stop,
            front_distance=self.front_distance,
            detection=self.detection,
            manual_command=self.manual_command,
            lane_offset=self.lane_offset,
            has_recent_detection=now - self.last_detection_time <= self.detection_timeout_sec,
            has_recent_manual=now - self.last_manual_time <= self.command_timeout_sec,
            has_recent_lane=now - self.last_lane_time <= self.lane_timeout_sec,
            has_recent_scan=now - self.last_scan_time <= self.scan_timeout_sec,
            obstacle_stop_distance=self.obstacle_stop_distance,
            obstacle_slow_distance=self.obstacle_slow_distance,
            mode_obstacle_stop_distances=self.mode_obstacle_stop_distances,
            cruise_speed=self.cruise_speed,
            slow_speed=self.slow_speed,
            turn_speed=self.turn_speed,
            lane_kp=self.lane_kp,
            max_angular_speed=self.max_angular_speed,
            speed_scale=self.speed_scale,
            manual_turn_speed=self.manual_turn_speed,
            navigation_motion=self.navigation_motion,
            has_recent_navigation=now - self.last_navigation_time <= self.navigation_timeout_sec,
            apply_obstacle_stop=False,
            diagnostic_reasons=reasons,
        )
        gate = getattr(self, 'search_gate', None)
        lease = getattr(self, 'control_lease', None)
        lease_blocked = lease is not None and (lease.blocked(now) or lease.purpose != self.mode)
        policy = vector(motion) if reasons is not None else None
        gate_blocked = False
        if self.operator_stop or self.emergency_stop or (gate_blocked := gate is not None and gate.blocked(now)) or lease_blocked:
            if reasons is not None:
                if self.operator_stop:
                    reasons.append('operator_stop')
                if self.emergency_stop and 'emergency_stop' not in reasons:
                    reasons.append('emergency_stop')
                if gate_blocked:
                    reasons.append(getattr(gate, 'diagnostic_reason', 'search_gate_blocked'))
                if lease_blocked:
                    reasons.append(lease.reason if lease.owner is None else 'lease_mode_mismatch')
            motion = dict(ZERO)
        if self.mode in self.follow_targets:
            valid, observed_at = self.follow_targets[self.mode]
            if not valid or now-observed_at > .5:
                if reasons is not None:
                    reasons.append('follow_target_unavailable')
                motion = dict(ZERO)
        evidence = self.scan_evidence
        if any(motion.values()) and evidence is not None and self.pose is not None and self.evidence_pose is not None:
            tx, ty = self.avoidance.local(self.evidence_pose[:2], self.pose)
            evidence = evidence.reframe(tx, ty, wrap(self.evidence_pose[2]-self.pose[2]))
        avoidance_input = any(motion.values()) if reasons is not None else False
        motion = self.avoidance.step(motion, mode=self.mode, now=now,
                    evidence=evidence, scan_age=now-self.evidence_at,
                    pose=self.pose, odom_age=now-self.odom_at,
                    confirmed=self.avoidance_confirmed and not self.avoidance_config.error,
                    legacy_stop=self.mode_obstacle_stop_distances.get(self.mode, self.obstacle_stop_distance),
                    actual_speed=self.actual_speed)
        if avoidance_input and not any(motion.values()):
            reasons.append('avoidance_' + self.avoidance.state)
        # The final gate also prevents avoidance manoeuvres continuing after expiry.
        if lease_blocked:
            if reasons is not None and any(motion.values()):
                reasons.append(lease.reason if lease.owner is None else 'lease_mode_mismatch')
            motion = dict(ZERO)
        limit = getattr(lease, "forward_limit_mps", None)
        if limit is not None:
            # A bounded forward task never follows an avoidance sidestep or turn.
            if motion["linear_x"] < 0 or abs(motion["linear_y"]) > 1e-9 or abs(motion["angular_z"]) > 1e-9:
                if reasons is not None:
                    reasons.append('bounded_forward_components')
                motion = dict(ZERO)
            else:
                motion["linear_x"] = min(motion["linear_x"], limit)
        twist.linear.x = motion["linear_x"]
        twist.linear.y = motion["linear_y"]
        twist.angular.z = motion["angular_z"]
        try:
            self.publisher.publish(twist)
        except Exception:
            if diagnostics:
                diagnostics.finish('twist_publication_failed')
            raise
        if reasons is not None:
            try:
                ids = getattr(self, 'lease_diagnostic_ids', {})
                if self.mode in ('manual', 'mapping') and not self.operator_stop:
                    ids = {**ids, **getattr(self, 'drive_diagnostic_ids', {})}
                if gate_blocked and getattr(self, 'search_diagnostic_ids', None):
                    ids = self.search_diagnostic_ids
                intent = self.manual_command if self.mode in ('manual', 'mapping') else self.mode
                if intent == 'stop':
                    intent = None
                diagnostics.observe(time.monotonic(), mode=self.mode, intent=intent, policy=policy,
                                    final=vector(motion), reasons=reasons, lease=lease, limit=limit,
                                    odom=(self.odom_at, self.actual_speed, getattr(self, 'actual_angular_speed', math.inf)),
                                    ids=ids, requested=vector(self.navigation_motion) if
                                    self.mode == 'navigation' and self.navigation_motion else intent)
            except Exception:
                # Diagnostics may never abort a control callback.
                pass

    def on_control_lease(self, message):
        try:
            now = time.monotonic()
            stationary = (not self.emergency_stop and self.mode == 'stop' and 0 <= now-self.odom_at < .5 and self.actual_speed < .01
                          and abs(getattr(self, 'actual_angular_speed', 1.)) < .02)
            request = json.loads(message.data)
            if self.control_lease.update(request, now, stationary) and request["op"] != "renew":
                self.lease_diagnostic_ids = wire_ids(request.get('diagnostic'))
                self.drive_diagnostic_ids = {}
                self.manual_command = "stop"
                self.last_manual_time = 0.0
                self.navigation_motion = None
                self.last_navigation_time = 0.0
                self.avoidance.reset()
        except (ValueError, TypeError, AttributeError):
            pass

    def publish_control_lease(self):
        message = String()
        value = self.control_lease.snapshot(time.monotonic())
        value["linear_cruise_speed_mps"] = self.cruise_speed
        message.data = json.dumps(value, allow_nan=False)
        self.lease_status_pub.publish(message)
        sink = getattr(self, 'diagnostic_log', None)
        signature = (value['control_epoch'], value['blocked'], value['purpose'], value['reason'])
        if sink and signature != getattr(self, '_diagnostic_lease_signature', None):
            self._diagnostic_lease_signature = signature
            reason = value['reason']
            sink.emit('lease.changed', reason, level='WARN' if reason == 'control_lease_expired' else 'INFO',
                      ids=getattr(self, 'lease_diagnostic_ids', {}),
                      details={'lease_blocked': value['blocked'], 'lease_purpose': value['purpose']})

    def on_search_control(self, message):
        try:
            value = json.loads(message.data)
            stationary = (self.mode == 'stop' and time.monotonic()-self.odom_at < .5
                          and self.actual_speed < .01 and abs(getattr(self,'actual_angular_speed',1.)) < .02)
            if self.search_gate.update(value, time.monotonic(), stationary) and value.get('op') != 'heartbeat':
                self.search_diagnostic_ids = {**wire_ids(value.get('diagnostic')), 'run_id': self.search_gate.run_id}
        except (ValueError, TypeError, AttributeError):
            pass

    def on_scan_provenance(self, message):
        try:
            value=json.loads(message.data)
            key=tuple(value['stamp'])
            if len(key)!=2 or not all(type(v) is int for v in key):return
            self.scan_packets[key]=value
            while len(self.scan_packets)>4:self.scan_packets.pop(next(iter(self.scan_packets)))
            scan=getattr(self,'_latest_raw_scan',None)
            if scan is not None and key==(scan.header.stamp.sec,scan.header.stamp.nanosec):
                self.on_scan(scan)
        except (ValueError,TypeError,KeyError):
            pass

    def publish_search_status(self):
        message = String()
        message.data = json.dumps({**self.search_gate.snapshot(time.monotonic()),
            'control_period_ms':getattr(self,'control_period_ms',0.),
            'control_overruns':getattr(self,'control_overruns',0)}, allow_nan=False)
        self.search_status_pub.publish(message)

    def apply_detection_rule(self, twist):
        if self.detection in {"red_light", "shutdown", "stop"}:
            return True
        if self.detection in {"turn_right", "right"}:
            twist.angular.z = -self.turn_speed
            return True
        if self.detection in {"turn_left", "left"}:
            twist.angular.z = self.turn_speed
            return True
        if self.detection in {"go_straight", "green_light", "no_light"}:
            twist.linear.x = self.cruise_speed
            return True
        if self.detection in {"limiting_velocity", "school_decelerate", "slow"}:
            twist.linear.x = self.slow_speed
            return True
        return False

    def apply_manual_command(self, twist):
        command = self.manual_command
        speed = self.slow_speed if self.front_distance <= self.obstacle_slow_distance else self.cruise_speed

        if command == "stop":
            return True
        if command == "forward":
            twist.linear.x = speed
            return True
        if command == "backward":
            twist.linear.x = -speed
            return True
        if command == "left":
            twist.linear.y = speed
            return True
        if command == "right":
            twist.linear.y = -speed
            return True
        if command in {"turn_l", "turn_left"}:
            twist.angular.z = self.turn_speed
            return True
        if command in {"turn_r", "turn_right"}:
            twist.angular.z = -self.turn_speed
            return True
        return False


def main():
    rclpy.init()
    node = DecisionController()
    try:
        rclpy.spin(node)
    finally:
        node.publisher.publish(Twist())
        diagnostics = getattr(node, 'motion_diagnostics', None)
        if diagnostics:
            diagnostics.finish('controller_exited')
            if diagnostics.moving:
                node.diagnostic_log.emit('motion.zero', 'controller_shutdown', level='WARN',
                                         details={'final': [0, 0, 0], 'mode': node.mode})
            node.diagnostic_log.close()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
