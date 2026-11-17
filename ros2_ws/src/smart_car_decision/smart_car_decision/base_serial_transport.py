"""Guarded serial adapter used by the staged, pinned vendor-driver patch.

Identity must be confirmed before this code opens hardware. Never imports or
constructs the vendor SDK (whose constructor transmits servo instructions).
"""
import math
import os
import struct
import threading

from .base_serial_feedback import Feedback
from .serial_binding import BindingError, collect_devices, holders, load_profile, preflight, select_device


def motion_frame(x, y, yaw):
    if not all(math.isfinite(v) for v in (x, y, yaw)):
        raise ValueError('non-finite velocity')
    # Identical X3 packet and integer truncation to installed SDK 3.3.1.
    frame = bytearray(b'\xff\xfc\x0a\x12\x01')
    frame.extend(struct.pack('<hhh', *(int(v * 1000) for v in (x, y, yaw))))
    frame.append((sum(frame) + 5) & 255)
    return bytes(frame)


class CheckedSerial:
    def __init__(self, serial_port, *, feedback=None):
        self.port = serial_port
        self.feedback = Feedback() if feedback is None else feedback
        self.lock = threading.RLock()
        self.error = None
        self.last_nonzero = False
        self.packets = []
        self.tx_write_calls = 0
        self.tx_motion_write_calls = 0
        self.tx_nonzero_motion_write_calls = 0

    def __getattr__(self, name):
        return getattr(self.port, name)

    def read(self, size=1):
        try:
            data = self.port.read(size)
        except OSError as exc:
            self.error = f'serial_read_error: {exc}'
            raise
        with self.lock:
            self.packets.extend(self.feedback.feed(data))
        return data

    def take_packets(self):
        with self.lock:
            packets, self.packets = self.packets, []
            return packets

    def status(self):
        with self.lock:
            state = self.feedback.status()
            state.update(tx_write_calls=self.tx_write_calls,
                         tx_motion_write_calls=self.tx_motion_write_calls,
                         tx_nonzero_motion_write_calls=self.tx_nonzero_motion_write_calls)
            if self.error:
                state.update(ok=False, transport_error=self.error)
            return state

    def snapshot(self):
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            return self.feedback.snapshot()

    def write(self, data):
        raw = bytes(data)
        with self.lock:
            movement = len(raw) >= 4 and raw[:2] == b'\xff\xfc' and raw[3] in (0x10, 0x11, 0x12)
            if movement:
                if raw[3] != 0x12 or len(raw) != 12 or raw[2] != 10 or raw[4] != 1 or (sum(raw[:-1]) + 5) & 255 != raw[-1]:
                    raise ValueError('unsupported or malformed motion packet')
                nonzero = any(struct.unpack('<hhh', raw[5:11]))
                if nonzero and not self.status()['ok']:
                    raise RuntimeError(f'motion rejected: {self.status()}')
            else:
                nonzero = False
            try:
                self.tx_write_calls += 1
                if movement:
                    self.tx_motion_write_calls += 1
                    self.tx_nonzero_motion_write_calls += int(nonzero)
                count = self.port.write(raw)
                if count != len(raw):
                    raise OSError(f'partial serial write: {count}/{len(raw)}')
            except OSError as exc:
                self.error = f'serial_write_error: {exc}'
                raise
            if movement:
                self.last_nonzero = nonzero
            return count

    def stop_if_unhealthy(self):
        with self.lock:
            state = self.status()
            if not state['ok'] and self.last_nonzero:
                # One zero to the already identity-checked port, never to a guessed device.
                self.write(motion_frame(0, 0, 0))
            return state

    def close(self):
        self.port.close()


def open_verified_serial(com='/dev/robot_base', *, profile_path='/etc/insightrover/serial-binding.json',
                         serial_factory=None, inspect=collect_devices, verify=preflight, claim=None,
                         post_open_holders=holders):
    if com != '/dev/robot_base':
        raise BindingError('legacy port override forbidden; no myserial/ttyUSB fallback')
    profile = load_profile(profile_path)  # Pending roles fail BEFORE any hardware access.
    device = verify(profile, devices=inspect())
    if serial_factory is None:
        import serial
        serial_factory = serial.Serial
    port = serial_factory(port=None, baudrate=115200, bytesize=8, parity='N', stopbits=1,
                          timeout=0.1, write_timeout=0.2, exclusive=True,
                          xonxoff=False, rtscts=False, dsrdtr=False)
    try:
        port.dtr = False
        port.rts = False
        port.port = com
        port.open()
        if claim is None:
            import fcntl
            import termios
            fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
            if os.fstat(port.fileno()).st_rdev != os.stat(device).st_rdev:
                raise BindingError('opened device changed during binding validation')
        else:
            claim(port, device)
        if select_device(profile, inspect()) != device:
            raise BindingError('USB identity changed while opening')
        if post_open_holders(device):
            raise BindingError('another process already held the port at exclusive claim')
        return CheckedSerial(port)
    except BaseException:
        port.close()
        raise
