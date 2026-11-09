"""Independent stop: attempt all stop paths even if one component fails."""
import asyncio
import math
import time
from uuid import uuid4
from .diagnostic_log import request_ids
from .lease_bridge import LeaseBridge


def stationary_evidence(sample, after, now):
    if sample is None:
        return False
    received_at, odom = sample
    if not isinstance(odom, dict) or not after <= received_at <= now:
        return False
    values = [odom.get(key) for key in ("odom_age_sec", "linear_speed", "angular_speed")]
    if odom.get("ok") is not True or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        return False
    age, linear, angular = values
    # Reject pre-stop odometry republished in a newer status frame.
    return (0 <= age <= received_at - after and age + now - received_at <= .5
            and abs(linear) < .01 and abs(angular) < .02)


async def stop_vehicle(node):
    sink = getattr(node, 'diagnostic_log', None)
    ids = {**request_ids.get(), 'episode_id': uuid4().hex} if sink else {}
    if sink:
        sink.emit('stop.requested', 'independent_stop', ids=ids)
    errors = []
    sent = False
    for name, argument in (("set_command", "stop"), ("set_mode", "stop")):
        try:
            getattr(node, name)(argument)
            sent = True
        except Exception:
            errors.append(name + "_failed")
    runner = getattr(node, "navigation_tasks", None)
    if runner is not None:
        try:
            runner.interrupt("人工停止：取消后续导航")
        except Exception:
            errors.append("task_cancel_failed")
    bridge = getattr(node, "navigation", None)
    if bridge is not None:
        try:
            bridge.cancel()
        except Exception:
            errors.append("navigation_cancel_failed")
    lease = LeaseBridge(node)
    confirmed = False
    confirmed_at = None
    try:
        token = request_ids.set(ids) if sink else None
        try:
            result = await lease.request({"op": "stop", "controller_id": lease.snapshot().get("controller_id")})
        finally:
            if token is not None:
                request_ids.reset(token)
        stopped_lease = result.get("lease", {})
        confirmed = result.get("confirmed") is True and stopped_lease.get("blocked") is True
        if confirmed:
            confirmed_at = time.monotonic()
    except Exception:
        errors.append("controller_stop_unconfirmed")
    vision = getattr(node, "vision_service", None)
    if vision is not None:
        try:
            search = vision.search_snapshot()
            if search.get("run_id") and search.get("state") not in {"idle", "cancelled", "not_found", "finished"}:
                await vision.action({"run_id": search["run_id"], "action": "cancel"})
        except Exception:
            errors.append("search_cancel_failed")
    stationary = False
    if confirmed_at is not None:
        deadline = time.monotonic() + .8
        while time.monotonic() < deadline:
            current = lease.snapshot()
            if not current.get("fresh") or any(current.get(key) != stopped_lease.get(key)
                                                for key in ("controller_id", "control_epoch", "blocked")):
                break
            if stationary_evidence(getattr(node, "stop_odometry_sample", None), confirmed_at, time.monotonic()):
                stationary = True
                break
            await asyncio.sleep(.05)
    output = {"request_sent": sent or confirmed, "controller_confirmed": confirmed,
              "stationary_confirmed": stationary, "errors": errors}
    if sink:
        sink.emit('stop.result', 'stationary_confirmed' if stationary else 'stationary_unconfirmed',
                  ids=ids, level='INFO' if stationary else 'WARN', details={**output, 'failures': errors})
    return output
