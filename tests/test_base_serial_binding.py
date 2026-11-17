import copy
import importlib.util
import json
import struct
from pathlib import Path

import pytest

from smart_car_decision.serial_binding import (
    BindingError, remove_legacy_alias, render_rules, select_device, validate_profile,
)
from smart_car_decision.base_serial_feedback import Feedback
from smart_car_decision.base_serial_transport import CheckedSerial, motion_frame, open_verified_serial

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def profile():
    p = json.loads((ROOT / 'ros2_ws/src/smart_car_decision/config/serial-binding.candidate.json').read_text(encoding='utf-8'))
    for spec in p['roles'].values():
        spec.update(confirmed=True, evidence='synthetic test fixture, not field evidence')
    return p


def devices(p, base='/dev/ttyUSB0', smoke='/dev/ttyUSB2'):
    return [{'device': node, 'properties': dict(p['roles'][role]['match'])}
            for node, role in [(base, 'base'), (smoke, 'smoke')]]


def frame(kind, payload):
    b = bytes([len(payload) + 3, kind]) + payload
    return b'\xff\xfb' + b + bytes([sum(b) & 255])


SPEED = frame(0x0a, struct.pack('<hhhB', 0, 0, 0, 124))
IMU = frame(0x0b, struct.pack('<9h', 0, 0, 0, 0, 0, 16384, 0, 0, 0))


def test_same_vid_pid_physical_paths_are_distinct(profile):
    assert select_device(profile, devices(profile)) == '/dev/ttyUSB0'
    rules = render_rules(profile)
    assert rules.count('SYMLINK+="robot_base"') == 1
    assert rules.count('SYMLINK+="smoke_sensor"') == 1
    assert 'ID_PATH' in rules and 'myserial' not in rules and 'voice' not in rules


def test_enumeration_reorder_does_not_change_role(profile):
    assert select_device(profile, devices(profile, '/dev/ttyUSB7', '/dev/ttyUSB0')) == '/dev/ttyUSB7'


def test_service_account_can_be_limited_to_only_its_device(profile):
    profile['service_user'] = 'jetson'
    rules = render_rules(profile)
    assert 'OWNER="jetson"' in rules and 'MODE="0600"' in rules
    assert 'GROUP="dialout"' not in rules


def test_service_account_cannot_inject_udev_rule(profile):
    profile['service_user'] = 'jetson", MODE="0777'
    with pytest.raises(BindingError, match='service account'):
        render_rules(profile)


def test_missing_device_never_uses_smoke(profile):
    with pytest.raises(BindingError, match='found 0'):
        select_device(profile, devices(profile)[1:])


def test_duplicate_unique_serial_is_rejected(profile):
    p = copy.deepcopy(profile)
    p['roles'] = {'base': p['roles']['base']}
    m = p['roles']['base']['match']
    m.pop('ID_PATH')
    m['ID_SERIAL_SHORT'] = 'duplicate'
    ds = [{'device': f'/dev/ttyUSB{i}', 'properties': dict(m)} for i in range(2)]
    with pytest.raises(BindingError, match='found 2'):
        select_device(p, ds)


def test_two_roles_cannot_claim_one_device(profile):
    profile['roles']['smoke']['match'] = dict(profile['roles']['base']['match'])
    with pytest.raises(BindingError, match='same physical'):
        validate_profile(profile)


def test_serial_and_path_selectors_cannot_overlap_live_device(profile):
    spec = profile['roles']['smoke']['match']
    spec.pop('ID_PATH')
    spec['ID_SERIAL_SHORT'] = 'shared'
    ds = devices(profile)
    ds[0]['properties']['ID_SERIAL_SHORT'] = 'shared'
    with pytest.raises(BindingError, match='same connected'):
        select_device(profile, ds)


@pytest.mark.parametrize('selector', ['', '*', 'path"bad', 'path\ninvalid'])
def test_unsafe_selectors_rejected(profile, selector):
    profile['roles']['base']['match']['ID_PATH'] = selector
    with pytest.raises(BindingError):
        render_rules(profile)


def test_pending_identity_cannot_render_or_open(tmp_path, profile):
    profile['roles']['base']['confirmed'] = False
    p = tmp_path / 'pending.json'
    p.write_text(json.dumps(profile), encoding='utf-8')
    def forbidden(**kwargs):
        pytest.fail('hardware factory called before identity confirmation')
    with pytest.raises(BindingError, match='not confirmed'):
        open_verified_serial(profile_path=p, serial_factory=forbidden)
    with pytest.raises(BindingError):
        render_rules(profile)


@pytest.mark.parametrize('port', ['/dev/myserial', '/dev/ttyUSB0', '/dev/serial/by-id/CH340'])
def test_legacy_override_is_rejected_before_open(port):
    with pytest.raises(BindingError, match='override forbidden'):
        open_verified_serial(port)


def test_cleanup_preserves_lidar_and_historical_comments():
    rule = 'KERNEL=="ttyUSB*", SYMLINK+="myserial"\n'
    others = '# old myserial rule\nKERNEL=="ttyUSB*", SYMLINK+="rplidar"\n'
    assert remove_legacy_alias(rule + others) == others
    with pytest.raises(BindingError, match='mixed'):
        remove_legacy_alias('KERNEL=="ttyUSB*", SYMLINK+="myserial other"\n')


def test_zero_stationary_velocity_needs_real_frames():
    f = Feedback()
    assert not f.status()['ok']
    f.feed(SPEED + IMU)
    assert f.status()['ok'] and f.snapshot()['speed']['velocity'] == (0, 0, 0)
    assert f.snapshot()['imu']['accel'][2] == pytest.approx(9.8, abs=0.01)


def test_mpu_and_icm_signs_match_installed_sdk():
    f = Feedback()
    f.feed(SPEED + frame(0x0b, struct.pack('<9h', 3755, 3755, 3755, 0, 0, 16384, 1, 2, 3)))
    assert f.snapshot()['imu']['gyro'] == pytest.approx((1, -1, -1), abs=0.001)
    f.feed(frame(0x0e, struct.pack('<9h', 100, 200, 300, 0, 0, 9800, 1, 2, 3)))
    assert f.snapshot()['imu']['gyro'] == (0.1, 0.2, 0.3)


def test_zero_acceleration_not_a_valid_imu():
    f = Feedback()
    f.feed(SPEED + frame(0x0e, bytes(18)))
    assert not f.status()['ok'] and f.status()['invalid_imu'] == 1


def test_corruption_fragmentation_and_resynchronization():
    f = Feedback()
    corrupted = bytearray(IMU)
    corrupted[-1] ^= 0xff
    data = b'noise\xff\xfb\xff' + bytes(corrupted) + SPEED + IMU
    for byte in data:
        f.feed(bytes([byte]))
    assert f.status()['ok']
    assert f.status()['checksum_errors'] > 0 and f.status()['length_errors'] > 0


def test_invalid_lengths_and_unknown_packets_do_not_refresh_health():
    f = Feedback()
    f.feed(frame(0x0a, bytes(4)) + frame(0x51, bytes(2)))
    assert not f.status()['ok'] and f.valid_frames == 0


def test_timeout_does_not_relabel_cached_zero_as_fresh():
    clock = [0.0]
    f = Feedback(clock=lambda: clock[0])
    f.feed(SPEED + IMU)
    clock[0] = 0.51
    with pytest.raises(RuntimeError, match='unavailable'):
        f.snapshot()
    f.feed(SPEED)
    assert not f.status()['ok'] and f.status()['stale'] == ['imu']
    f.feed(IMU)
    assert f.status()['ok']


class Port:
    def __init__(self, data=b'', partial=False, **kwargs):
        self.data, self.partial, self.kwargs = data, partial, kwargs
        self.writes, self.is_open, self.closed = [], False, False
    def read(self, size=1):
        data, self.data = self.data[:size], self.data[size:]
        return data
    def write(self, data):
        self.writes.append(data)
        return len(data) - int(self.partial)
    def open(self):
        self.is_open = True
    def close(self):
        self.is_open, self.closed = False, True


def test_motion_rejected_without_feedback_and_no_automatic_restart():
    port = Port(SPEED + IMU)
    c = CheckedSerial(port)
    with pytest.raises(RuntimeError, match='motion rejected'):
        c.write(motion_frame(0.14, 0, 0))
    assert not port.writes
    assert c.status()['tx_motion_write_calls'] == 0
    c.read(1000)
    assert c.status()['ok']
    assert not port.writes  # Feedback recovery never replays a previous request.
    c.write(motion_frame(0.14, 0, 0))
    assert len(port.writes) == 1
    assert c.status()['tx_motion_write_calls'] == 1
    assert c.status()['tx_nonzero_motion_write_calls'] == 1


def test_stop_once_on_feedback_timeout():
    clock = [0.0]
    f = Feedback(clock=lambda: clock[0])
    f.feed(SPEED + IMU)
    port = Port()
    c = CheckedSerial(port, feedback=f)
    c.write(motion_frame(0.1, 0, 0))
    clock[0] = 1
    assert not c.stop_if_unhealthy()['ok']
    c.stop_if_unhealthy()
    assert port.writes == [motion_frame(0.1, 0, 0), motion_frame(0, 0, 0)]


def test_partial_write_is_sticky_fault():
    port = Port(partial=True)
    c = CheckedSerial(port)
    with pytest.raises(OSError, match='partial'):
        c.write(motion_frame(0, 0, 0))
    assert not c.status()['ok'] and 'serial_write_error' in c.status()['transport_error']


@pytest.mark.parametrize('values', [(float('nan'), 0, 0), (0, float('inf'), 0)])
def test_nonfinite_commands_rejected(values):
    with pytest.raises(ValueError):
        motion_frame(*values)


def test_open_is_exclusive_and_rechecks_identity(profile, tmp_path):
    p = tmp_path / 'profile.json'
    p.write_text(json.dumps(profile), encoding='utf-8')
    port = Port()
    def factory(**kwargs):
        port.kwargs = kwargs
        return port
    c = open_verified_serial(profile_path=p, serial_factory=factory,
                             inspect=lambda: devices(profile), verify=lambda *a, **k: '/dev/ttyUSB0',
                             claim=lambda *a: None, post_open_holders=lambda *a: [])
    assert c.port is port and port.kwargs['exclusive'] is True
    assert not port.dtr and not port.rts and not port.writes


def test_identity_changes_during_open_closes_port(profile, tmp_path):
    p = tmp_path / 'profile.json'
    p.write_text(json.dumps(profile), encoding='utf-8')
    port = Port()
    seq = iter([devices(profile), devices(profile, '/dev/ttyUSB7')])
    with pytest.raises(BindingError, match='changed'):
        open_verified_serial(profile_path=p, serial_factory=lambda **k: port,
                             inspect=lambda: next(seq), verify=lambda *a, **k: '/dev/ttyUSB0',
                             claim=lambda *a: None, post_open_holders=lambda *a: [])
    assert port.closed and not port.writes


def test_occupancy_race_after_exclusive_open_is_rejected(profile, tmp_path):
    p = tmp_path / 'profile.json'
    p.write_text(json.dumps(profile), encoding='utf-8')
    port = Port()
    with pytest.raises(BindingError, match='already held'):
        open_verified_serial(profile_path=p, serial_factory=lambda **k: port,
                             inspect=lambda: devices(profile), verify=lambda *a, **k: '/dev/ttyUSB0',
                             claim=lambda *a: None, post_open_holders=lambda *a: [{'pid': 999}])
    assert port.closed and not port.writes


def test_read_error_is_visible_not_fake_stationary_data():
    class Broken(Port):
        def read(self, size=1):
            raise OSError('disconnected')
    c = CheckedSerial(Broken())
    with pytest.raises(OSError):
        c.read()
    assert 'serial_read_error' in c.status()['transport_error']
    with pytest.raises(RuntimeError):
        c.snapshot()
