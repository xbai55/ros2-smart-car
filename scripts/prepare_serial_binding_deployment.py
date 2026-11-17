#!/usr/bin/env python3
"""Prepare a file-only installation bundle. Never connects to or changes a car.

Pending hardware roles cannot be deployed. Manifest expected-before hashes must
be checked again on the vehicle immediately before installation or restoration.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'ros2_ws/src/smart_car_decision'))
from smart_car_decision.serial_binding import BindingError, render_rules, remove_legacy_alias, select_device
import re


def prepare(inventory, profile, output):
    rules = render_rules(profile)  # Reject all pending roles before creating files.
    devices = [{'device': dev, 'properties': value['properties']} for dev, value in inventory['devices'].items()]
    for role in profile['roles']:
        select_device(profile, devices, role)
    changes = []
    for path, item in inventory['rules'].items():
        cleaned = remove_legacy_alias(item['text'])
        if cleaned == item['text']:
            continue
        if not path.startswith('/etc/udev/rules.d/') or Path(path).suffix != '.rules':
            raise BindingError('system/vendor legacy rule needs explicit review; do not rewrite automatically')
        before = item['text'].encode('utf-8')
        if hashlib.sha256(before).hexdigest() != item['sha256']:
            raise BindingError('inventory rule bytes differ from checksum; recapture losslessly')
        # Removing the legacy combined permission/alias rule must not revoke
        # access to a still-unassigned CH340. Preserve only its observed access,
        # matched by physical identity; do not assign it a guessed business role.
        if '1a86' in item['text'] and '7523' in item['text']:
            assigned = {select_device(profile, devices, role) for role in profile['roles']}
            for dev in devices:
                props = dev['properties']
                if dev['device'] in assigned or props.get('ID_VENDOR_ID') != '1a86' or props.get('ID_MODEL_ID') != '7523':
                    continue
                perm = inventory.get('device_permissions', {}).get(dev['device'])
                if not perm:
                    raise BindingError('capture existing unassigned serial permissions before removing legacy rule')
                physical_path = props.get('ID_PATH', '')
                interface = props.get('ID_USB_INTERFACE_NUM', '')
                mode = format(int(perm['mode'], 8), '04o')
                if not re.fullmatch(r'[A-Za-z0-9_.:+/-]+', physical_path) or not re.fullmatch(r'[0-9a-f]{2}', interface):
                    raise BindingError('unsafe unassigned serial identity')
                if not re.fullmatch(r'0[0-7]{3}', mode) or int(perm['uid']) < 0 or int(perm['gid']) < 0:
                    raise BindingError('invalid existing serial access')
                cleaned += '\n# Preserve existing access only; device business role remains unconfirmed.\n'
                cleaned += (f'SUBSYSTEM=="tty", ENV{{ID_VENDOR_ID}}=="1a86", ENV{{ID_MODEL_ID}}=="7523", '
                            f'ENV{{ID_USB_INTERFACE_NUM}}=="{interface}", ENV{{ID_PATH}}=="{physical_path}", '
                            f'OWNER="{int(perm["uid"])}", GROUP="{int(perm["gid"])}", MODE:="{mode}"\n')
        changes.append((path, before, cleaned.encode('utf-8')))
    if not changes:
        raise BindingError('expected conflicting legacy rule not found; audit inventory drift')
    targets = {
        '/etc/udev/rules.d/99-insightrover-serial.rules': rules.encode('utf-8'),
        '/etc/insightrover/serial-binding.json': (json.dumps(profile, indent=2) + '\n').encode('utf-8'),
    }
    for path, data in targets.items():
        if path in inventory['rules']:
            raise BindingError('target rule already exists; obtain exact backup and review it')
        changes.append((path, None, data))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {'live_changes_executed': False, 'files': [],
                'preconditions': ['explicit live authorization', 'vehicle service stopped',
                                  'both serial devices unoccupied', 'all before hashes rechecked',
                                  'new-target files confirmed absent; do not overwrite']}
    for index, (target, before, after) in enumerate(changes):
        name = f'{index:02d}-{Path(target).name}'
        (output / (name + '.after')).write_bytes(after)
        if before is not None:
            (output / (name + '.before')).write_bytes(before)
        manifest['files'].append({'target': target, 'artifact': name,
                                  'before_sha256': hashlib.sha256(before).hexdigest() if before is not None else None,
                                  'after_sha256': hashlib.sha256(after).hexdigest()})
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory', type=Path, required=True)
    p.add_argument('--profile', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = prepare(json.loads(a.inventory.read_text(encoding='utf-8')),
                     json.loads(a.profile.read_text(encoding='utf-8')), a.output)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
