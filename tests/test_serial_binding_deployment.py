import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from test_base_serial_binding import profile, ROOT
from smart_car_decision.serial_binding import BindingError

spec = importlib.util.spec_from_file_location('prepare_serial_binding', ROOT / 'scripts/prepare_serial_binding_deployment.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


def inventory(profile):
    raw = 'KERNEL=="ttyUSB*", SYMLINK+="myserial"\n# Preserve this comment\n'
    return {'devices': {f'/dev/ttyUSB{i}': {'properties': value['match']}
                        for i, value in enumerate(profile['roles'].values())},
            'rules': {'/etc/udev/rules.d/serial.rules': {'text': raw, 'sha256': hashlib.sha256(raw.encode()).hexdigest()}}}


def test_pending_roles_produce_no_deployment_files(profile, tmp_path):
    profile['roles']['base']['confirmed'] = False
    with pytest.raises(BindingError):
        deploy.prepare(inventory(profile), profile, tmp_path / 'bundle')
    assert not (tmp_path / 'bundle').exists()


def test_bundle_preserves_backups_and_before_after_fingerprints(profile, tmp_path):
    inv = inventory(profile)
    result = deploy.prepare(inv, profile, tmp_path / 'bundle')
    assert result['live_changes_executed'] is False
    first = result['files'][0]
    assert first['before_sha256'] == inv['rules']['/etc/udev/rules.d/serial.rules']['sha256']
    assert (tmp_path / 'bundle' / (first['artifact'] + '.before')).read_text() == inv['rules']['/etc/udev/rules.d/serial.rules']['text']
    cleaned = (tmp_path / 'bundle' / (first['artifact'] + '.after')).read_text()
    assert 'myserial' not in cleaned and '# Preserve' in cleaned
    assert len(result['files']) == 3


def test_inventory_checksum_drift_blocks_bundle(profile, tmp_path):
    inv = inventory(profile)
    inv['rules']['/etc/udev/rules.d/serial.rules']['sha256'] = 'changed'
    with pytest.raises(BindingError, match='checksum'):
        deploy.prepare(inv, profile, tmp_path / 'bundle')


def test_unassigned_ch340_keeps_existing_access_without_alias(profile, tmp_path):
    inv = inventory(profile)
    profile['roles'].pop('smoke')
    rule = inv['rules']['/etc/udev/rules.d/serial.rules']
    rule['text'] = 'ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="7523", MODE:="0777", SYMLINK+="myserial"\n'
    rule['sha256'] = hashlib.sha256(rule['text'].encode()).hexdigest()
    inv['device_permissions'] = {'/dev/ttyUSB1': {'uid': 0, 'gid': 20, 'mode': '0o777'}}
    result = deploy.prepare(inv, profile, tmp_path / 'bundle')
    assert result['files'][0]['target'] == '/etc/udev/rules.d/serial.rules'
    content = (tmp_path / 'bundle' / (result['files'][0]['artifact'] + '.after')).read_text()
    assert 'MODE:="0777"' in content and 'ID_PATH' in content
    assert 'SYMLINK' not in content
