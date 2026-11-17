#!/usr/bin/env python3
"""Inventory/preflight, rule rendering, and bounded receive-only protocol capture.

The passive subcommand changes the hardware interface and requires separate
operator authorization. No subcommand writes any serial bytes.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ros2_ws/src/smart_car_decision'))
from smart_car_decision.base_serial_feedback import Feedback
from smart_car_decision.serial_binding import (
    BindingError, collect_devices, holders, load_profile, preflight, render_rules,
    select_device, validate_profile,
)


def passive_capture(profile, duration, output, *, authorized=False, serial_factory=None):
    if not authorized:
        raise BindingError('explicit authorization required before opening hardware')
    if not 1 <= duration <= 30:
        raise BindingError('passive duration must be 1..30 seconds')
    # This diagnostic permits a CANDIDATE role, but never transmits or enables it.
    validate_profile(profile, confirmed=False)
    checked = json.loads(json.dumps(profile))
    for spec in checked['roles'].values():
        spec.update(confirmed=True, evidence='candidate selection for receive-only capture, NOT role confirmation')
    device = select_device(checked, collect_devices())
    if holders(device):
        raise BindingError('candidate device is occupied; do not steal it')
    if serial_factory is None:
        import serial
        serial_factory = serial.Serial
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    port = serial_factory(port=None, baudrate=115200, bytesize=8, parity='N', stopbits=1,
                          timeout=0.1, exclusive=True, xonxoff=False, rtscts=False, dsrdtr=False)
    parser, started = Feedback(), time.monotonic()
    count, problem = 0, None
    try:
        port.dtr = port.rts = False
        port.port = device
        port.open()
        import fcntl
        import termios
        fcntl.ioctl(port.fileno(), termios.TIOCEXCL)
        import os
        if os.fstat(port.fileno()).st_rdev != os.stat(device).st_rdev:
            raise BindingError('device replaced while opening')
        with (output / 'rx.bin').open('xb') as raw, (output / 'chunks.jsonl').open('x', encoding='utf-8') as times:
            while time.monotonic() - started < duration and count < 1024 * 1024:
                data = port.read(min(256, 1024 * 1024 - count))
                if data:
                    times.write(json.dumps({'offset': count, 'monotonic': time.monotonic(), 'size': len(data)}) + '\n')
                    raw.write(data)
                    parser.feed(data)
                    count += len(data)
    except Exception as exc:
        problem = f'{type(exc).__name__}: {exc}'
    finally:
        try:
            port.close()
        except OSError as exc:
            if problem is None:
                problem = f'close_error: {exc}'
        elapsed = time.monotonic() - started
        report = {'device': device, 'duration': time.monotonic() - started, 'bytes': count,
                  'transmitted_bytes': 0, 'error': problem, 'feedback': parser.status(),
                  'candidate_only': True, 'inventory': collect_devices(),
                  'last_decoded_samples': parser.samples,
                  'observed_frame_hz': {k: v / max(elapsed, 1e-9) for k, v in parser.frame_counts.items()},
                  'byte_limit_reached': count >= 1024 * 1024}
        raw_path = output / 'rx.bin'
        if raw_path.exists():
            report['rx_sha256'] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
        (output / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    if problem:
        raise BindingError(problem)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['inventory', 'preflight', 'rules', 'passive', 'decode'])
    p.add_argument('--profile', type=Path, default=Path('/etc/insightrover/serial-binding.json'))
    p.add_argument('--authorized-passive-candidate', action='store_true')
    p.add_argument('--seconds', type=float, default=10)
    p.add_argument('--output', type=Path)
    p.add_argument('--input', type=Path)
    args = p.parse_args()
    try:
        if args.action == 'inventory':
            result = collect_devices()
        elif args.action == 'decode':
            if args.input is None or args.input.stat().st_size > 1024 * 1024:
                raise BindingError('input required, maximum size 1 MiB')
            f = Feedback()
            f.feed(args.input.read_bytes())
            result = {'feedback': f.status(), 'samples': f.samples,
                      'note': 'file replay times are decode times, not original sensor timestamps'}
        elif args.action == 'passive':
            if args.output is None:
                raise BindingError('new output directory required')
            profile = json.loads(args.profile.read_text(encoding='utf-8'))
            result = passive_capture(profile, args.seconds, args.output,
                                     authorized=args.authorized_passive_candidate)
        else:
            profile = load_profile(args.profile)
            result = preflight(profile) if args.action == 'preflight' else render_rules(profile)
        if args.action == 'rules':
            print(result, end='')
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (BindingError, OSError, ValueError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
