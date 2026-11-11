import base64
import json
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from smart_car_decision.vision_admin import VisionAdmin, require_stationary
from smart_car_decision.safety_vision import load_config


def node():
    status = {'mode': 'stop', 'odom': {'ok': True, 'linear_speed_xy': 0., 'angular_speed': 0., 'odom_age_sec': .01}}
    value = SimpleNamespace(store=SimpleNamespace(snapshot=lambda: status), ros_status_age_sec=lambda: .01,
                            navigation_tasks=SimpleNamespace(snapshot=lambda: {'state': 'idle'}))
    return value, status


def test_maintenance_requires_fresh_stationary_odom_and_no_task():
    value, status = node()
    require_stationary(value)
    for patch in ({'ok': False}, {'linear_speed_xy': .1}, {'angular_speed': float('nan')}, {'odom_age_sec': 1}):
        previous = dict(status['odom'])
        status['odom'].update(patch)
        with pytest.raises(RuntimeError):
            require_stationary(value)
        status['odom'] = previous
    value.navigation_tasks.snapshot = lambda: {'state': 'paused'}
    with pytest.raises(RuntimeError):
        require_stationary(value)


def test_snapshot_rejects_missing_stale_and_limits_dimensions():
    import cv2
    value, _ = node()
    ok, jpeg = cv2.imencode('.jpg', np.zeros((1400, 1800, 3), dtype=np.uint8))
    camera = SimpleNamespace(frame_snapshot=lambda **_: None)
    admin = VisionAdmin(value, camera)
    with pytest.raises(RuntimeError):
        admin.frame()
    camera.frame_snapshot = lambda **_: {'jpeg': jpeg.tobytes(), 'sequence': 1, 'age_ms': 3000, 'captured_at': time.time()-3}
    with pytest.raises(RuntimeError):
        admin.frame()
    camera.frame_snapshot = lambda **_: {'jpeg': jpeg.tobytes(), 'sequence': 2, 'age_ms': 0, 'captured_at': time.time()}
    result = admin.frame()
    image = cv2.imdecode(np.frombuffer(base64.b64decode(result['jpeg_base64']), dtype=np.uint8), cv2.IMREAD_COLOR)
    assert max(image.shape[:2]) == 1280 and result['sequence'] == 2


def test_receipt_prevents_duplicate_maintenance_and_parameter_changes(monkeypatch):
    value, _ = node()
    admin = VisionAdmin(value, None)
    calls = []
    monkeypatch.setattr(admin, '_recover', lambda body: calls.append(body) or {'state': 'completed'})
    body = {'operation_id': 'a'*64, 'target': 'camera'}
    assert admin.mutate('recover', body) == admin.mutate('recover', body)
    assert len(calls) == 1
    with pytest.raises(ValueError):
        admin.mutate('recover', {**body, 'target': 'yoloe'})


def test_pending_evidence_and_thread_exit_block_recovery():
    value, _ = node()
    admin = VisionAdmin(value, None)
    value.safety_vision = SimpleNamespace(snapshot=lambda: {'pending_in_memory': 1})
    with pytest.raises(RuntimeError, match='未落盘'):
        admin.mutate('recover', {'operation_id': 'b'*64, 'target': 'safety'})
    worker = SimpleNamespace(config_lock=threading.Lock(), snapshot=lambda: {'pending_in_memory': 0},
                             stop_event=threading.Event(), thread=SimpleNamespace(join=lambda **_: None, is_alive=lambda: True))
    with pytest.raises(RuntimeError, match='尚未退出'):
        admin._restart_safety(worker)


def test_install_share_model_resolution_and_sha(tmp_path, monkeypatch):
    import sys
    import types
    share = tmp_path/'share'
    (share/'models').mkdir(parents=True)
    model = share/'models'/'fall.pt'
    model.write_bytes(b'weight')
    packages = types.ModuleType('ament_index_python.packages')
    packages.get_package_share_directory = lambda _: str(share)
    monkeypatch.setitem(sys.modules, 'ament_index_python.packages', packages)
    import hashlib
    cfg = load_config(tmp_path/'config.json', {'enabled': True, 'models': [{'path': 'models/fall.pt',
                      'sha256': hashlib.sha256(b'weight').hexdigest(), 'class_map': {'fallen': 'fallen_person'}}]})
    assert cfg['models'][0]['path'] == str(model.resolve())
    cfg['models'][0]['sha256'] = '0'*64
    with pytest.raises(ValueError, match='SHA256'):
        load_config(tmp_path/'config.json', cfg)


def test_disabled_model_does_not_require_missing_weight(tmp_path):
    cfg = load_config(tmp_path/'config.json', {'enabled': True, 'models': [{'path': 'missing.pt', 'enabled': False,
                      'class_map': {'fallen': 'fallen_person'}}]})
    assert cfg['models'][0]['enabled'] is False
