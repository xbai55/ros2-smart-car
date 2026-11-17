import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from smart_car_decision.base_serial_transport import CheckedSerial
from test_base_serial_binding import Port, SPEED, IMU

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_serial_overlay', ROOT / 'scripts/prepare_base_serial_overlay.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


@pytest.fixture
def generated():
    sdk = ROOT / 'output/serial-binding-20261117/vehicle-sdk.py'
    driver = ROOT / 'output/serial-binding-20261117/vehicle-driver.py'
    if not sdk.exists() or not driver.exists():
        pytest.skip('audited field sources not present; transport/binding tests remain runnable')
    return prepare.prepare(sdk.read_bytes(), driver.read_bytes(), expected_sdk_sha256=prepare.SDK_SHA256)


def message():
    return NS(header=NS(stamp=None, frame_id=''), linear=NS(x=0, y=0), angular=NS(z=0),
              linear_acceleration=NS(x=0, y=0, z=0), angular_velocity=NS(x=0, y=0, z=0),
              magnetic_field=NS(x=0, y=0, z=0), orientation_covariance=[0.] * 9)


def publisher():
    messages = []
    return NS(publish=messages.append, messages=messages)


def build_driver_function(text):
    tree = ast.parse(text)
    cls = next(x for x in tree.body if isinstance(x, ast.ClassDef))
    fn = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == 'pub_data')
    scope = {name: message for name in ['Imu', 'Twist', 'Float32', 'MagneticField', 'JointState', 'DiagnosticArray']}
    scope.update(DiagnosticStatus=type('Status', (), {'OK': 0, 'ERROR': 2}),
                 KeyValue=lambda **k: NS(**k), Clock=lambda: NS(now=lambda: NS(to_msg=lambda: 123)))
    import time
    scope['time'] = time
    exec(compile(ast.Module(body=[fn], type_ignores=[]), 'generated_pub_data', 'exec'), scope)
    return scope['pub_data']


def driver_state(data=b''):
    ser = CheckedSerial(Port(data))
    ser.read(1000)
    log = []
    node = NS(car=NS(ser=ser, get_version=lambda: 3.3), Prefix='', imu_link='imu_link',
              _last_health_log=0., _last_feedback_stamp={},
              get_clock=lambda: NS(now=lambda: NS(to_msg=lambda: 123)),
              get_logger=lambda: NS(error=log.append), logs=log)
    for prefix in ['health', 'vel', 'imu', 'mag', 'vol', 'Edi']:
        setattr(node, prefix + 'Publisher', publisher())
    return node


def test_generated_driver_does_not_publish_default_feedback(generated):
    fn = build_driver_function(generated['guarded_vendor_driver.py'])
    node = driver_state()
    fn(node)
    assert node.healthPublisher.messages[-1].status[0].level == 2
    assert not node.imuPublisher.messages and not node.velPublisher.messages
    assert node.logs


def test_generated_driver_uses_actual_feedback_and_no_duplicate_new_timestamps(generated):
    fn = build_driver_function(generated['guarded_vendor_driver.py'])
    node = driver_state(SPEED + IMU)
    fn(node)
    fn(node)
    assert len(node.imuPublisher.messages) == len(node.velPublisher.messages) == 1
    msg = node.imuPublisher.messages[0]
    assert msg.linear_acceleration.z == pytest.approx(9.8, abs=0.01)
    assert msg.orientation_covariance[0] == -1
    assert node.healthPublisher.messages[-1].status[0].level == 0


def test_overlay_cannot_silently_patch_other_vendor_versions():
    with pytest.raises(ValueError, match='SDK hash'):
        prepare.prepare(b'unknown', b'unknown', expected_sdk_sha256=prepare.SDK_SHA256)


def test_generated_sdk_uses_verified_alias_and_no_implicit_servo_command(generated):
    text = generated['verified_rosmaster.py']
    tree = ast.parse(text)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
    init = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
    ctor = ast.unparse(init)
    assert 'open_verified_serial(com)' in ctor
    assert 'set_uart_servo_torque' not in ctor
    assert '/dev/robot_base' in ctor and '/dev/myserial' not in ctor


def test_startup_checks_profile_before_any_vendor_import(monkeypatch):
    from smart_car_decision import serial_binding, verified_base_driver
    def missing():
        raise serial_binding.BindingError('profile missing')
    monkeypatch.setattr(serial_binding, 'load_profile', missing)
    with pytest.raises(serial_binding.BindingError, match='profile missing'):
        verified_base_driver.main()


def test_passive_capture_needs_separate_authorization(tmp_path):
    s = importlib.util.spec_from_file_location('inspect_serial', ROOT / 'scripts/inspect_base_serial.py')
    module = importlib.util.module_from_spec(s)
    s.loader.exec_module(module)
    def forbidden(**kwargs):
        pytest.fail('serial open attempted without authorization')
    with pytest.raises(RuntimeError, match='authorization'):
        module.passive_capture({}, 10, tmp_path / 'capture', serial_factory=forbidden)
    assert not (tmp_path / 'capture').exists()
