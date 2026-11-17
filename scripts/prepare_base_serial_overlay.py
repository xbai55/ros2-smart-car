#!/usr/bin/env python3
"""Build (never install) a pinned vendor overlay; preserve the original SDK/driver.

Use only with source extracted from the inspected vehicle, not an arbitrary SDK.
Generated code requires a CONFIRMED /etc/insightrover/serial-binding.json.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path

DRIVER_SHA256 = '2be9784289154b3d2ec972266ccdba5056ffe317b06a4d17c2a9a48e42a8d39a'
SDK_SHA256 = 'bc0f1313f4f2527cca5f631373ab66cf03c66035d1732a3f2fd665f32a27c139'


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f'vendor source mismatch: {old[:70]!r}')
    return text.replace(old, new, 1)


def prepare(sdk_bytes, driver_bytes, *, expected_sdk_sha256):
    if expected_sdk_sha256 != SDK_SHA256 or hashlib.sha256(sdk_bytes).hexdigest() != SDK_SHA256:
        raise ValueError('SDK hash mismatch')
    if hashlib.sha256(driver_bytes).hexdigest() != DRIVER_SHA256:
        raise ValueError('driver differs from audited vehicle; review before preparing')
    sdk = sdk_bytes.decode('utf-8').replace('\r\n', '\n')
    driver = driver_bytes.decode('utf-8').replace('\r\n', '\n')
    sdk = replace_once(sdk, 'com="/dev/myserial"', 'com="/dev/robot_base"')
    sdk = replace_once(sdk, 'self.ser = serial.Serial(com, 115200)',
                       'from smart_car_decision.base_serial_transport import open_verified_serial\n'
                       '        self.ser = open_verified_serial(com)')
    # The X3 has no arm in this project. Do not transmit the SDK's implicit servo torque command.
    sdk = replace_once(sdk, 'self.set_uart_servo_torque(1)', '# No implicit arm-servo initialization.')
    tree = ast.parse(sdk)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Rosmaster')
    receive = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '__receive_data')
    lines = sdk.splitlines(keepends=True)
    lines[receive.lineno-1:receive.end_lineno] = ['''    def __receive_data(self):
        while self.ser.is_open:
            try:
                self.ser.read(128)
                for kind, payload in self.ser.take_packets():
                    try:
                        self.__parse_data(kind, list(payload))
                    except (IndexError, ValueError, struct.error) as exc:
                        # A malformed auxiliary report must not kill reception silently.
                        print("base auxiliary protocol error:", exc)
            except OSError as exc:
                print("base serial receive failed:", exc)
                return
''']
    sdk = ''.join(lines)
    driver = replace_once(driver, 'from Rosmaster_Lib import Rosmaster',
                          'from .verified_rosmaster import Rosmaster\nimport time\n'
                          'from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue')
    driver = replace_once(driver, 'self.car = Rosmaster()',
                          'self.car = Rosmaster()\n\t\tself._last_feedback_stamp = {}\n'
                          '\t\tself._last_health_log = 0.0\n'
                          '\t\tself.healthPublisher = self.create_publisher(DiagnosticArray, "/diagnostics", 10)')
    driver = replace_once(driver, '\tdef pub_data(self):', '''\tdef pub_data(self):
\t\ttry:
\t\t\thealth = self.car.ser.stop_if_unhealthy()
\t\t\tfeedback = self.car.ser.snapshot() if health["ok"] else None
\t\texcept (OSError, RuntimeError) as exc:
\t\t\thealth = {"ok": False, "error": str(exc)}
\t\tstatus = DiagnosticStatus()
\t\tstatus.name = "robot_base/serial_feedback"
\t\tstatus.hardware_id = "/dev/robot_base"
\t\tstatus.level = DiagnosticStatus.OK if health["ok"] else DiagnosticStatus.ERROR
\t\tstatus.message = "valid base feedback" if health["ok"] else "base communication unavailable"
\t\tstatus.values = [KeyValue(key=str(k), value=str(v)) for k, v in health.items()]
\t\tarray = DiagnosticArray()
\t\tarray.header.stamp = self.get_clock().now().to_msg()
\t\tarray.status = [status]
\t\tself.healthPublisher.publish(array)
\t\tif not health["ok"]:
\t\t\tif time.monotonic() - self._last_health_log >= 2.0:
\t\t\t\tself.get_logger().error("base feedback invalid: " + str(health))
\t\t\t\tself._last_health_log = time.monotonic()
\t\t\treturn
'''.rstrip())
    substitutions = {
        'self.car.get_accelerometer_data()': 'feedback["imu"]["accel"]',
        'self.car.get_gyroscope_data()': 'feedback["imu"]["gyro"]',
        'self.car.get_magnetometer_data()': 'feedback["imu"]["mag"]',
        'self.car.get_motion_data()': 'feedback["speed"]["velocity"]',
        'self.car.get_battery_voltage()*1.0': 'feedback["speed"]["battery"]',
    }
    for old, new in substitutions.items():
        driver = driver.replace(old, new)
    driver = replace_once(driver, 'imu.header.stamp = time_stamp.to_msg()',
                          'imu.header.stamp = time_stamp.to_msg()\n\t\timu.orientation_covariance[0] = -1.0')
    for topic, key in [('vel', 'speed'), ('imu', 'imu'), ('mag', 'imu')]:
        variable = {'vel': 'twist', 'imu': 'imu', 'mag': 'mag'}[topic]
        driver = replace_once(driver, f'self.{topic}Publisher.publish({variable})',
                              f'if self._last_feedback_stamp.get("{topic}") != feedback["{key}"]["received_monotonic"]:\n'
                              f'\t\t\tself.{topic}Publisher.publish({variable})\n'
                              f'\t\t\tself._last_feedback_stamp["{topic}"] = feedback["{key}"]["received_monotonic"]')
    for name, text in [('verified_rosmaster.py', sdk), ('guarded_vendor_driver.py', driver)]:
        compile(text, name, 'exec')
    return {'verified_rosmaster.py': sdk, 'guarded_vendor_driver.py': driver}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sdk', type=Path, required=True)
    p.add_argument('--driver', type=Path, required=True)
    p.add_argument('--sdk-sha256', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    sdk, driver = a.sdk.read_bytes(), a.driver.read_bytes()
    files = prepare(sdk, driver, expected_sdk_sha256=a.sdk_sha256)
    a.output.mkdir(parents=True, exist_ok=False)
    manifest = {'sdk_sha256': hashlib.sha256(sdk).hexdigest(), 'driver_sha256': DRIVER_SHA256,
                'files': {}, 'installed': False}
    for name, text in files.items():
        data = text.encode('utf-8')
        (a.output / name).write_bytes(data)
        manifest['files'][name] = hashlib.sha256(data).hexdigest()
    (a.output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(json.dumps(manifest, indent=2))


if __name__ == '__main__':
    main()
