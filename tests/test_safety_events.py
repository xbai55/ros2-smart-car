import base64
import json
import time
from types import SimpleNamespace as NS
import sys

import pytest

from smart_car_decision.safety_events import DetectionTracks, EventGate, SafetyOutbox, corridor_candidate
from smart_car_decision.safety_vision import load_config, SafetyVisionWorker


def test_persistent_confirmation_deduplication_and_clear():
    gate = EventGate(confirm_sec=2, clear_sec=5, max_gap_sec=1)
    c = {'key': 'smoke:zone1', 'type': 'smoke_fire'}
    assert not gate.update([c], 0)
    assert not gate.update([c], 1)
    assert gate.update([c], 2) == [c]
    assert not gate.update([c], 3)
    assert not gate.update([], 9)
    assert not gate.update([c], 10)
    gate.update([c], 11)
    assert gate.update([c], 12) == [c]


def test_frame_gap_never_counts_as_continuous_evidence():
    gate = EventGate(confirm_sec=2)
    c = {'key': 'fall', 'type': 'fallen_person'}
    assert not gate.update([c], 0)
    assert not gate.update([c], 3)
    gate.update([c], 4)
    assert gate.update([c], 5)


def test_unrelated_boxes_cannot_share_a_confirmation_track():
    tracks = DetectionTracks()
    def box(coords):
        return {'type':'fallen_person', 'confidence':.8, 'box':coords}
    original = tracks.update([box([0,0,10,10])], 0)[0]['key']
    moved = tracks.update([box([1,0,11,10])], .2)[0]['key']
    other = tracks.update([box([100,100,110,110])], .4)[0]['key']
    assert moved == original
    assert other != original


def test_outbox_survives_restart_and_retries_same_id(tmp_path):
    path = tmp_path / 'outbox.sqlite3'
    outbox = SafetyOutbox(path)
    event = outbox.put({'type': 'smoke_fire'}, b'jpeg-evidence')
    recovered = SafetyOutbox(path)
    assert recovered.pending()[0]['event_id'] == event['event_id']
    assert base64.b64decode(recovered.pending()[0]['snapshot_base64']) == b'jpeg-evidence'
    recovered.acknowledge([event['event_id']])
    recovered.acknowledge([event['event_id']])
    assert recovered.pending() == []
    with recovered._connect() as db:
        assert db.execute('SELECT length(jpeg) FROM events WHERE id=?', (event['event_id'],)).fetchone()[0] == 0
    with pytest.raises(ValueError):
        recovered.put({'type': 'smoke_fire'}, b'')


def test_corridor_requires_matching_map_fresh_pose_and_insufficient_free_width():
    zone = {'id': 'door', 'map_key': 'map1', 'polygon': [[0,-.5],[2,-.5],[2,.5],[0,.5]]}
    points = [(1., y) for y in [-.4,-.2,0,.2,.4]]
    pose = {'ok': True, 'x': 0., 'y': 0., 'yaw': 0.}
    args = dict(now=10., scan_at=9.9, pose_fresh=True)
    assert corridor_candidate(points, [zone], pose, 'map1', **args)
    assert not corridor_candidate(points, [zone], pose, 'other', **args)
    assert not corridor_candidate(points, [zone], pose, 'map1', **{**args, 'scan_at': 7})
    assert not corridor_candidate(points, [zone], pose, 'map1', **{**args, 'pose_fresh': False})
    assert not corridor_candidate([(1., .45)] * 5, [zone], pose, 'map1', **args)


def test_staggered_obstacles_along_corridor_are_not_projected_into_a_wall():
    zone = {'id':'hall', 'map_key':'m', 'polygon':[[0,-1],[4,-1],[4,1],[0,1]]}
    points = [(i*.6+.1, -.8+i*.32) for i in range(6)]
    assert not corridor_candidate(points, [zone], {'ok':True,'x':0.,'y':0.,'yaw':0.}, 'm', now=1.,scan_at=1.,pose_fresh=True)


def test_missing_specialist_weight_has_no_automatic_coco_fallback(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'models': [{'path': 'missing.pt', 'class_map': {'fire': 'smoke_fire'}}]}))
    with pytest.raises(ValueError, match='专项模型'):
        load_config(path)


def wait_for(predicate, timeout=4.):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError('worker did not recover')


def worker_fixture(tmp_path, config):
    import cv2
    import numpy as np
    ok, encoded = cv2.imencode('.jpg', np.zeros((32,32,3), dtype=np.uint8))
    assert ok
    class Camera:
        bad = False
        sequence = 0
        def frame_snapshot(self, **kwargs):
            self.sequence += 1
            data = b'bad-jpeg' if self.bad else encoded.tobytes()
            self.bad = False
            return {'jpeg':data,'sequence':self.sequence,'captured_at':time.time()}
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config), encoding='utf-8')
    node = NS(store=NS(snapshot=lambda:{'mode':'stop'}), map_snapshot=NS(snapshot=lambda:None),
              ros_status_age_sec=lambda:0.,get_logger=lambda:NS(error=lambda message:None))
    camera = Camera()
    return SafetyVisionWorker(node,camera,path,tmp_path/'outbox.sqlite3'), camera


def test_bad_camera_frame_does_not_end_inspection_thread(tmp_path):
    worker,camera = worker_fixture(tmp_path, {'enabled':True,'corridors':[{'id':'z','map_key':'m','polygon':[[0,0],[1,0],[1,1]]}]})
    camera.bad = True
    worker.start()
    try:
        wait_for(lambda:worker.snapshot()['state']=='degraded')
        wait_for(lambda:worker.snapshot()['state']=='running')
        assert worker.thread.is_alive()
    finally:
        worker.close()


def test_temporary_disk_error_retries_the_same_event_and_picture(tmp_path, monkeypatch):
    model_path = tmp_path / 'trained.pt'
    model_path.write_text('test-only fake model')
    box = NS(cls=[0],conf=[.9],xyxy=[NS(tolist=lambda:[2.,2.,22.,22.])])
    model = NS(names={0:'fire'},predict=lambda *a,**kw:[NS(names={0:'fire'},boxes=[box])])
    monkeypatch.setitem(sys.modules,'ultralytics',NS(YOLO=lambda path:model))
    worker,_ = worker_fixture(tmp_path,{'enabled':True,'rate_hz':5,'confirm_sec':.2,
                                      'models':[{'path':str(model_path),'class_map':{'fire':'smoke_fire'}}]})
    original = worker.outbox.put
    attempts = []
    def flaky(event,jpeg):
        attempts.append(event['event_id'])
        if len(attempts)==1:
            raise OSError('temporary disk failure')
        return original(event,jpeg)
    monkeypatch.setattr(worker.outbox,'put',flaky)
    worker.start()
    try:
        wait_for(lambda:bool(worker.pending))
        with pytest.raises(RuntimeError,match='尚未落盘'):
            worker.configure_corridors([])
        wait_for(lambda:len(worker.outbox.pending())==1)
        assert attempts[0] == attempts[1]
        assert not worker.pending
        assert worker.thread.is_alive()
    finally:
        worker.close()
