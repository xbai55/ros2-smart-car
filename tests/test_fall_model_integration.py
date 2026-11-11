import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from smart_car_decision.safety_vision import load_config, predict_specialists


def test_pinned_model_metadata_matches_local_checkpoint():
    root = Path(__file__).resolve().parents[1]
    metadata = json.loads((root / 'ros2_ws/src/smart_car_decision/config/fall-model.json').read_text(encoding='utf-8'))
    checkpoint = root / 'ros2_ws/src/smart_car_decision/models/yolo11-fall.pt'
    if not checkpoint.is_file():
        pytest.skip('local specialist checkpoint is distributed separately from Git')
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == metadata['sha256']
    assert metadata['classes'] == {'0': 'fallen', '1': 'sitting', '2': 'standing'}
    assert metadata['class_map'] == {'fallen': 'fallen_person'}


def test_specialists_receive_clean_copies_and_only_mapped_classes_become_candidates():
    class Box:
        def __init__(self, cls, score, coords):
            self.cls, self.conf = [cls], [score]
            self.xyxy = [SimpleNamespace(tolist=lambda: coords)]

    class Model:
        def __init__(self, name):
            self.name = name
            self.frames = []

        def predict(self, frame, **kwargs):
            self.frames.append(frame.copy())
            box = Box(0 if self.name == 'fall' else 1, .8, [1., 2., 20., 30.])
            return [SimpleNamespace(names={0: 'fallen', 1: 'sitting'}, boxes=[box])]

    image = np.zeros((32, 32, 3), dtype=np.uint8)
    fall, smoke = Model('fall'), Model('smoke')
    candidates, annotated, timings = predict_specialists(
        [({'path': 'fall.pt', 'class_map': {'fallen': 'fallen_person'}, 'confidence': .25}, fall, 'fallsha'),
         ({'path': 'smoke.pt', 'class_map': {'sitting': 'smoke_fire'}, 'confidence': .5}, smoke, 'smokesha')],
        image, {'device': '0'})
    assert image.max() == 0
    assert all(np.array_equal(frame, image) for frame in fall.frames + smoke.frames)
    assert [item['type'] for item in candidates] == ['fallen_person', 'smoke_fire']
    assert len(timings) == 2
    assert annotated.shape == image.shape


def test_model_sha_is_rejected_when_malformed_or_changed(tmp_path):
    model = tmp_path / 'model.pt'
    model.write_bytes(b'checkpoint')
    with pytest.raises(ValueError, match='SHA256'):
        load_config(tmp_path / 'config.json', {'models': [{'path': str(model), 'class_map': {'fallen': 'fallen_person'}, 'sha256': 'bad'}]})
    with pytest.raises(ValueError, match='SHA256'):
        load_config(tmp_path / 'config.json', {'models': [{'path': str(model), 'class_map': {'fallen': 'fallen_person'}, 'sha256': '0' * 64}]})
