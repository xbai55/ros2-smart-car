"""Persistent avoidance configuration and acknowledged web/controller handshake."""
import json
import math
import os
import threading
import time
from pathlib import Path
from uuid import uuid4

DEFAULTS = {"enabled": False, "trigger_distance_m": .6, "protection_mode": "basic"}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) not in (set(DEFAULTS), {"enabled", "trigger_distance_m"}):
        raise ValueError("防护设置须包含 protection_mode、enabled 和 trigger_distance_m")
    mode = value.get("protection_mode", "basic")
    if not isinstance(mode, str) or mode not in {"basic", "full"}:
        raise ValueError("防护模式须为 basic 或 full")
    distance = value["trigger_distance_m"]
    if type(value["enabled"]) is not bool or isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance) or not .4 <= distance <= 1.5:
        raise ValueError("避障开关须为布尔值，触发距离须为 0.40–1.50 米")
    return {"enabled": value["enabled"], "trigger_distance_m": round(distance, 3), "protection_mode": mode}


class AvoidanceSettings:
    def __init__(self, path):
        self.path = Path(path).expanduser()
        self.value, self.error = dict(DEFAULTS), None
        self.needs_migration = False
        try:
            if self.path.exists():
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.value = validate_settings(raw)
                if "protection_mode" not in raw:
                    self.value.update(protection_mode="basic", enabled=False)
                    self.needs_migration = True
        except (OSError, ValueError, TypeError) as exc:
            self.error = "避障设置损坏，请停车后重新保存：" + str(exc)

    def save(self, value):
        value = validate_settings(value)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_name(self.path.name + "." + uuid4().hex + ".tmp")
        try:
            if self.needs_migration and self.path.exists():
                backup = self.path.with_name(self.path.name + ".pre-basic")
                if not backup.exists():
                    backup.write_bytes(self.path.read_bytes())
            temp.write_text(json.dumps(value), encoding="utf-8")
            os.replace(temp, self.path)
        finally:
            temp.unlink(missing_ok=True)
        self.value, self.error = value, None
        self.needs_migration = False


class AvoidanceService:
    """Only the controller persists settings. HTTP success means pending, not applied."""
    def __init__(self, node, path, publish, clock=time.monotonic):
        self.node, self.publish, self.clock = node, publish, clock
        self.lock = threading.RLock()
        self.settings = AvoidanceSettings(path)
        self.request_id = uuid4().hex
        self.requested = None if self.settings.error else dict(self.settings.value)
        self.actual = None
        self.recovery_epoch = None
        self.received_at = None

    def transmit(self):
        with self.lock:
            if self.requested is not None:
                self.publish({"request_id": self.request_id, "settings": self.requested,
                              "robot_radius_m": getattr(self.node, 'navigation_radius', .25),
                              "recovery_epoch": self.recovery_epoch})

    def observe(self, message):
        with self.lock:
            if not isinstance(message, dict) or not isinstance(message.get("confirmed"), bool):
                return
            message = dict(message)
            velocity = message.get('velocity')
            if isinstance(velocity, dict) and type(velocity.get('measured_at')) in (float, int):
                # Both nodes run on the vehicle's monotonic clock. Transport
                # latency must not renew a twist sample's original expiry.
                age = self.clock() - velocity['measured_at']
                message['velocity'] = {**velocity, 'age_sec': age if math.isfinite(age) else None,
                                       'ok': velocity.get('ok') is True and 0 <= age <= .5}
            self.actual = message
            if (message.get('rejected_request_id') == self.request_id and message.get('confirmed') is True
                    and isinstance(message.get('request_id'), str)):
                self.requested = dict(message['settings'])
                self.request_id = message['request_id']
                self.recovery_epoch = None
            self.received_at = self.clock()

    def snapshot(self):
        with self.lock:
            actual = dict(self.actual or {})
            fresh = self.received_at is not None and self.clock() - self.received_at <= .6
            confirmed = (fresh and actual.get("confirmed") is True and actual.get("request_id") == self.request_id
                         and actual.get("settings") == self.requested
                         and actual.get('robot_radius_m') == getattr(self.node, 'navigation_radius', .25))
            result = {**actual, "supported": True, "confirmed": bool(confirmed), "available": bool(confirmed and actual.get("available")),
                      "requested": self.requested, "settings": actual.get("settings", self.requested or self.settings.value),
                      "protection_supported": actual.get("protection_protocol") == 2}
            velocity = actual.get('velocity')
            if isinstance(velocity, dict):
                value = velocity.get('age_sec')
                age = value + self.clock() - self.received_at if type(value) in (float, int) and self.received_at is not None else math.inf
                result['velocity'] = {**velocity, 'age_sec': age if math.isfinite(age) else None,
                                      'ok': velocity.get('ok') is True and 0 <= age <= .5}
            if not confirmed:
                fault = fresh and actual.get('state') == 'sensor_fault'
                result.update(state='sensor_fault' if fault or self.settings.error else 'waiting',
                              reason=self.settings.error or actual.get('config_rejection') or (actual.get('reason') if fault else '等待控制器确认避障设置'))
            return result

    def update(self, changes):
        with self.lock:
            state = self.node.store.snapshot()
            odom = state.get("odom", {})
            age = self.node.ros_status_age_sec()
            actual = self.snapshot()
            if actual.get('protection_supported'):
                velocity = actual.get('velocity') or {}
                odom = {**odom, 'ok': velocity.get('ok')}
                values = (velocity.get('linear_speed_xy'), velocity.get('angular_speed'))
            else:
                values = (odom.get("linear_speed_xy"), odom.get("angular_speed"))
            handoff = getattr(self.node, 'map_handoff', None)
            if (getattr(self.node, 'control_lease_ack', {}).get('owner') is not None or
                    (handoff is not None and handoff.active())):
                raise RuntimeError('请先停止并释放当前任务或地图准备的控制权')
            if (age is None or not math.isfinite(age) or not 0 <= age <= .5 or state.get("mode") != "stop" or state.get("emergency_stop") or not odom.get("ok") or
                    any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values) or
                    abs(values[0]) > .01 or abs(values[1]) > .03):
                raise RuntimeError("请停止小车并等待有效里程计确认静止后再修改避障设置")
            if isinstance(changes, dict) and set(changes) == {"acknowledge"}:
                token = changes["acknowledge"]
                actual = self.snapshot()
                if not actual.get("confirmed") or not actual.get("recovery_required") or token != actual.get("motion_epoch"):
                    raise RuntimeError("恢复状态已变化，请刷新后重试")
                self.recovery_epoch = token
                self.request_id = uuid4().hex
                self.transmit()
                return self.snapshot()
            if not isinstance(changes, dict) or not changes or set(changes) - set(DEFAULTS):
                raise ValueError("无效的避障设置")
            if (self.actual or {}).get("recovery_required"):
                raise RuntimeError("请先确认故障恢复，再修改防护设置")
            self.recovery_epoch = None
            self.requested = validate_settings({**(self.requested or self.settings.value), **changes})
            self.request_id = uuid4().hex
            self.settings.error = None
            self.transmit()
            return self.snapshot()
