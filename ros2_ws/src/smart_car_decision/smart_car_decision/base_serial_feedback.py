"""ROSMASTER receive framing/health, based on the installed 3.3.1 SDK.

No SDK construction, hardware access, transmission, or ROS dependency here.
"""
import math
import struct
import time


class Feedback:
    def __init__(self, clock=time.monotonic, max_age=0.5):
        self.clock, self.max_age = clock, max_age
        self.buffer = bytearray()
        self.samples = {}
        self.checksum_errors = self.length_errors = self.invalid_imu = 0
        self.valid_frames = 0
        self.frame_counts = {'speed': 0, 'imu': 0}

    def feed(self, data):
        self.buffer.extend(data)
        frames = []
        while len(self.buffer) >= 3:
            start = self.buffer.find(b'\xff\xfb')
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1:] == b'\xff' else b''
                break
            del self.buffer[:start]
            if len(self.buffer) < 3:
                break
            length = self.buffer[2]
            if not 3 <= length <= 64:
                self.length_errors += 1
                del self.buffer[0]
                continue
            total = length + 2
            if len(self.buffer) < total:
                break
            raw = bytes(self.buffer[:total])
            if sum(raw[2:-1]) & 255 != raw[-1]:
                self.checksum_errors += 1
                del self.buffer[0]
                continue
            del self.buffer[:total]
            kind, payload = raw[3], raw[4:-1]
            expected = {0x0a: 7, 0x0b: 18, 0x0e: 18}.get(kind)
            if expected is None:
                frames.append((kind, payload))
                continue  # Other checksummed packets do not establish motion/IMU health.
            if len(payload) != expected:
                self.length_errors += 1
                continue
            if kind == 0x0a:
                x, y, z, battery = struct.unpack('<hhhB', payload)
                value = {'velocity': (x / 1000, y / 1000, z / 1000), 'battery': battery / 10}
                key = 'speed'
            else:
                v = struct.unpack('<9h', payload)
                if kind == 0x0b:
                    gyro = (v[0] / 3754.9, -v[1] / 3754.9, -v[2] / 3754.9)
                    accel, mag = tuple(a / 1671.84 for a in v[3:6]), tuple(v[6:9])
                else:
                    gyro, accel, mag = [tuple(a / 1000 for a in v[i:i+3]) for i in (0, 3, 6)]
                if math.sqrt(sum(a*a for a in accel)) == 0:
                    self.invalid_imu += 1
                    self.samples.pop('imu', None)
                    continue
                value, key = {'gyro': gyro, 'accel': accel, 'mag': mag}, 'imu'
            self.samples[key] = (self.clock(), value)
            self.valid_frames += 1
            self.frame_counts[key] += 1
            frames.append((kind, payload))
        return frames

    def status(self):
        ages = {key: max(0, self.clock() - stamp) for key, (stamp, _) in self.samples.items()}
        missing = [key for key in ('speed', 'imu') if key not in ages]
        stale = [key for key, age in ages.items() if age > self.max_age]
        return {'ok': not missing and not stale, 'missing': missing, 'stale': stale, 'ages': ages,
                'valid_frames': self.valid_frames, 'checksum_errors': self.checksum_errors,
                'frame_counts': dict(self.frame_counts),
                'length_errors': self.length_errors, 'invalid_imu': self.invalid_imu}

    def snapshot(self):
        state = self.status()
        if not state['ok']:
            raise RuntimeError(f'base feedback unavailable: {state}')
        return {key: dict(value, received_monotonic=stamp) for key, (stamp, value) in self.samples.items()}
