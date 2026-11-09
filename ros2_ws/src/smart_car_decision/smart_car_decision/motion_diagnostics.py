"""Observes the existing arbitration and independent odometry evidence."""
import math
from uuid import uuid4


def winning_module(reason):
    if reason.startswith('avoidance_'):
        return 'avoidance'
    if reason.startswith(('control_lease_', 'control_released', 'lease_')):
        return 'control_lease'
    if reason.startswith('search_gate_'):
        return 'search_gate'
    if reason in {'emergency_stop', 'operator_stop', 'bounded_forward_components', 'follow_target_unavailable'}:
        return 'decision_controller'
    return 'control_policy'


def vector(motion):
    result = []
    for key in ('linear_x', 'linear_y', 'angular_z'):
        value = motion.get(key)
        result.append(value if type(value) in (int, float) and math.isfinite(value) else None)
    return result


class MotionDiagnostics:
    def __init__(self, sink):
        self.sink = sink
        self.moving = False
        self.last_state = None
        self.pending = None
        self.previous_motion = [0, 0, 0]
        self.previous_mode = None

    def observe(self, now, *, mode, intent, policy, final, reasons, lease, limit, odom, ids, requested=None):
        moving = any(final)
        if moving:
            if self.pending:
                self.finish("motion_resumed")
            self.previous_motion = final
            self.previous_mode = mode
            self.moving, self.last_state = True, None
            return
        first = reasons[0] if reasons else "zero_intent"
        last = reasons[-1] if reasons else "policy"
        state = (mode, first, last)
        if (self.moving or intent) and state != self.last_state:
            if self.pending:
                self.finish("stop_reason_changed")
            event_ids = {**ids, "episode_id": ids.get('episode_id') or uuid4().hex}
            self.pending = (now, event_ids)
            self.sink.emit("motion.zero" if self.moving else "motion.blocked", first, ids=event_ids,
                           level="WARN", details={
                               "mode": mode, "command": intent, "first": first, "winner": last,
                               "winner_module": winning_module(last),
                               "gates": reasons, "policy": policy, "final": final,
                               "previous_output": self.previous_motion, "previous_mode": self.previous_mode,
                               "requested": requested,
                               "lease_blocked": not lease or lease.owner is None,
                               "lease_reason": lease.reason if lease else None,
                               "lease_purpose": lease.purpose if lease else None,
                               "forward_limit": limit,
                           })
            self.last_state = state
        self.moving = False
        if self.pending:
            began, ids = self.pending
            measured, linear, angular = odom
            if (all(math.isfinite(v) for v in odom) and began <= measured <= now
                    and now - measured <= .5 and abs(linear) < .01 and abs(angular) < .02):
                self.sink.emit("motion.stationary", "fresh_odometry", ids=ids, details={
                    "odom_age": now - measured, "linear_speed": linear, "angular_speed": angular,
                })
                self.pending = None
            elif now - began >= .8:
                self.finish("stationary_evidence_unavailable")

    def finish(self, reason):
        if self.pending:
            self.sink.emit("motion.unconfirmed", reason, ids=self.pending[1], level="WARN")
            self.pending = None
