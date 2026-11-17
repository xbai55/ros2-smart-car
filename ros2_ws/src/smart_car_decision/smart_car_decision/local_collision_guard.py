"""Body-frame collision checks without a map or odometry pose.

Twist and scans retain their original expiry. Uncompensated body motion expands
the envelope; it never changes an unknown ray into observed free space.
"""
import math

from .avoidance import ZERO, MIN_CLEARANCE_M, DistanceOnlyEvidence

SCAN_MAX_AGE = .6
VELOCITY_MAX_AGE = .5


def velocity_evidence(msg, now_ros, received_at, transform=None):
    """Validate twist independently of pose, including a displaced base origin."""
    age = now_ros - (msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9)
    if not math.isfinite(age) or not 0 <= age <= VELOCITY_MAX_AGE:
        raise ValueError('velocity_stale')
    vx, vy, omega = msg.twist.twist.linear.x, msg.twist.twist.linear.y, msg.twist.twist.angular.z
    if not all(math.isfinite(v) for v in (vx, vy, omega)):
        raise ValueError('velocity_invalid')
    displacement = 0.
    if msg.child_frame_id != 'base_link':
        if transform is None:
            raise ValueError('velocity_frame_unavailable')
        q, p = transform.rotation, transform.translation
        if (not all(math.isfinite(v) for v in (p.x, p.y, q.x, q.y, q.z, q.w))
                or abs(q.x) > .08 or abs(q.y) > .08
                or abs(q.x*q.x + q.y*q.y + q.z*q.z + q.w*q.w - 1) > .01):
            raise ValueError('velocity_frame_invalid')
        displacement = math.hypot(p.x, p.y)
    return math.hypot(vx, vy) + abs(omega) * displacement, omega, received_at - age


def distance_scan_ready(evidence):
    if evidence is None or not evidence.full or not evidence.rays:
        return False
    valid = sum(v is not None and math.isfinite(v) for v in evidence.rays)
    return valid >= max(3, math.ceil(len(evidence.rays) * .05))


def local_guard(controller, motion, *, evidence, scan_age, speed, angular, velocity_age):
    """Reuse the swept geometry, adding bounds for scan/body-frame drift.

    Linear deceleration .3 m/s² retains the existing guard's model. Angular
    deceleration .3 rad/s² is an explicit model assumption, requiring vehicle
    validation before deployment. No missing-velocity fallback is allowed.
    """
    controller.requested_motion = dict(motion) if isinstance(motion, dict) else dict(ZERO)
    controller.applied_motion = dict(ZERO)
    controller.reason_code = 'sensor_fault'
    if (not isinstance(motion, dict) or set(motion) != set(ZERO)
            or not all(type(v) in (float, int) and math.isfinite(v) for v in motion.values())):
        return controller.stop('sensor_fault', '运动指令无效')
    if evidence is None or not math.isfinite(scan_age) or not 0 <= scan_age <= SCAN_MAX_AGE:
        return controller.stop('sensor_fault', '雷达证据或安装坐标变换不可用')
    if not distance_scan_ready(evidence):
        return controller.stop('sensor_fault', '雷达整体无有效测距，已停车')
    if (not all(math.isfinite(v) for v in (speed, angular, velocity_age))
            or speed < 0 or not 0 <= velocity_age <= VELOCITY_MAX_AGE):
        return controller.stop('sensor_fault', '底盘速度证据无效或过期')
    body_radius = controller.footprint.radius if controller.footprint else controller.radius
    # A point at radius r moves at most r*|theta| under rotation. Include the
    # stopping rotation even when a new command requests a smaller angular speed.
    angular_bound = max(abs(angular), abs(motion["angular_z"]))
    commanded_speed = math.hypot(motion['linear_x'], motion['linear_y'])
    duration = max(1., .6 + max(speed, commanded_speed) / .3)
    sweep_extent = (max(body_radius, controller.radius) + MIN_CLEARANCE_M
                    + commanded_speed * duration + max(speed, commanded_speed)**2 / .6)
    # Rotation affects the whole commanded sweep, including its translated end,
    # not only the body at the scan origin. The chord bounds all intermediate
    # rotations; cap at pi, where the largest possible displacement is 2*r.
    angle = min(math.pi, angular_bound * scan_age + angular_bound * angular_bound / .6)
    drift = 2 * sweep_extent * math.sin(angle / 2)
    controller.actual_speed, controller.scan_age = speed, scan_age
    controller.state, controller.reason = 'idle', '基础防护：仅按实际测距防撞'
    controller.path = []
    result = controller.guard(motion, DistanceOnlyEvidence(evidence), controller.radius + MIN_CLEARANCE_M + drift)
    controller.requested_motion, controller.applied_motion = dict(motion), dict(result)
    controller.reason_code = controller.state
    return result
