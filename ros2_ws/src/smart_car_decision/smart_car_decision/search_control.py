"""Controller-side search lease. Expiry latches a stop; stale messages cannot release it."""
import math
from uuid import uuid4


class SearchGate:
    def __init__(self):
        self.instance_id = uuid4().hex
        self.run_id = None
        self.version = -1
        self.held = True
        self.active = False
        self.at = 0.
        self.reason = '无搜索任务'
        self.diagnostic_reason = 'search_gate_held'
        self.control_epoch = None
        self.owner = None

    def update(self, value, now, stationary=False, lease=None):
        if not isinstance(value, dict) or not math.isfinite(now):
            return False
        if value.get('controller_id') != self.instance_id:
            return False
        ident, version, op = value.get('run_id'), value.get('version'), value.get('op')
        if not isinstance(ident, str) or not 1 <= len(ident) <= 128 or type(version) is not int:
            return False
        if lease is not None:
            if value.get('control_epoch') != lease.epoch:
                return False
            identity = value.get('control_lease')
            if identity is not None and (not isinstance(identity, dict) or lease.blocked(now)
                    or any(identity.get(k) != v for k, v in (
                        ('controller_id', lease.controller_id), ('control_epoch', lease.epoch), ('owner', lease.owner)))):
                return False
            if self.active and self.control_epoch != lease.epoch:
                self.active, self.held = False, True
            if ident == self.run_id and self.control_epoch is not None and self.control_epoch != lease.epoch:
                if op != 'arm' or not stationary:
                    return False
                self.run_id = None
        if ident != self.run_id:
            if op != 'arm' or self.active or not stationary:
                return False
            self.run_id, self.version, self.active, self.held = ident, -1, True, True
            self.control_epoch = lease.epoch if lease is not None else None
            self.owner = lease.owner if lease is not None else None
        if version <= self.version:
            return False
        if op == 'heartbeat':
            if not self.active or self.held:
                return False
        elif op == 'resume':
            if not self.active or not stationary:
                return False
            self.held = False
        elif op in {'arm', 'hold'}:
            self.held = True
        elif op == 'release':
            if not stationary:
                return False
            self.active, self.held = False, True
        else:
            return False
        self.version, self.at, self.reason = version, now, str(value.get('reason', op))[:200]
        self.diagnostic_reason = 'search_gate_held'
        return True

    def blocked(self, now):
        if self.active and (not math.isfinite(now) or now - self.at > 1.):
            self.held, self.reason = True, '搜索心跳超时，等待人工恢复'
            self.diagnostic_reason = 'search_gate_timeout'
        return self.active and self.held

    def blocked_for(self, lease, mode, now):
        if lease is None:
            return self.blocked(now)
        if self.control_epoch != lease.epoch or self.owner != lease.owner:
            return False
        # A stationary observer owns no motion lease. It must be cancelled by
        # the explicit takeover path, but cannot gate another owner's motion.
        return mode == 'navigation' and self.blocked(now)

    def snapshot(self, now):
        self.blocked(now)
        return dict(controller_id=self.instance_id, run_id=self.run_id, version=self.version,
                    active=self.active, held=self.held, reason=self.reason,
                    control_epoch=self.control_epoch, owner=self.owner)
