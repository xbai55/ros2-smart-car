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

    def update(self, value, now, stationary=False):
        if value.get('controller_id') != self.instance_id:
            return False
        ident, version, op = value.get('run_id'), value.get('version'), value.get('op')
        if not isinstance(ident, str) or not 1 <= len(ident) <= 128 or type(version) is not int:
            return False
        if ident != self.run_id:
            if op != 'arm' or self.active or not stationary:
                return False
            self.run_id, self.version, self.active, self.held = ident, -1, True, True
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

    def snapshot(self, now):
        self.blocked(now)
        return dict(controller_id=self.instance_id, run_id=self.run_id, version=self.version,
                    active=self.active, held=self.held, reason=self.reason)
