import errno

from smart_car_decision.diagnostic_log import DiagnosticLog, read_page
from smart_car_decision.motion_diagnostics import MotionDiagnostics


class Sink:
    def __init__(self):
        self.events = []

    def emit(self, kind, reason, **data):
        self.events.append((kind, reason, data))


def test_stop_keeps_trigger_and_requires_post_stop_odometry():
    sink = Sink()
    recorder = MotionDiagnostics(sink)
    moving = dict(mode='navigation', intent='navigation', policy=[.1, 0, 0], final=[.1, 0, 0],
                  reasons=[], lease=None, limit=None, ids={'run_id': 'run-one'})
    recorder.observe(10, odom=(9.9, 0, 0), **moving)
    stopped = {**moving, 'final': [0, 0, 0], 'reasons': ['control_lease_expired', 'bounded_forward_components']}
    recorder.observe(11, odom=(10.99, 0, 0), **stopped)
    assert len(sink.events) == 1
    kind, reason, data = sink.events[0]
    assert (kind, reason) == ('motion.zero', 'control_lease_expired')
    assert data['details']['winner'] == 'bounded_forward_components'
    recorder.observe(11.2, odom=(11.1, 0, 0), **stopped)
    assert sink.events[1][0] == 'motion.stationary'
    assert sink.events[1][2]['ids']['episode_id'] == data['ids']['episode_id']


def test_spool_rotation_resume_and_disk_full(tmp_path, monkeypatch):
    log = DiagnosticLog('controller', tmp_path, max_segment=1024)
    for i in range(24):
        log.emit('motion.zero', 'operator_stop', details={'mode': 'manual'})
    log.close()
    page = read_page({}, tmp_path)
    assert 0 < len(page['events']) < 24
    assert not read_page(page['cursors'], tmp_path)['events']
    assert read_page({'controller-1': 'missing-cursor'}, tmp_path)['gaps'] == ['controller-1']
    assert all(path.stat().st_size <= 1024 for path in tmp_path.glob('*.jsonl'))

    def fail(*_):
        raise OSError(errno.ENOSPC, 'disk full')

    offline = DiagnosticLog('web', tmp_path)
    monkeypatch.setattr(offline, '_append', fail)
    offline.emit('stop.requested', 'independent_stop')
    offline.close()
    assert offline.health['write_failed'] == 1
