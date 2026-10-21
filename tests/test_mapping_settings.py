import json
import sys
from types import SimpleNamespace

import pytest
import yaml
from fastapi.testclient import TestClient

from smart_car_decision.mapping_settings import MappingSettings, laser_range, turn_speed
from smart_car_decision.mapping_session import MappingRestartManager, MapSnapshotStore
from smart_car_decision.mapping_recording import MappingInputRecorder, INPUT_TOPICS, INITIAL_CONTROL_TOPICS
from smart_car_decision.control_policy import decide_motion
from smart_car_decision.web_api import create_app


@pytest.mark.parametrize('value', [float('nan'), float('inf'), None, True, .04, .61, 'bad'])
def test_turn_validation_rejects_invalid_values(value):
    with pytest.raises(ValueError):
        turn_speed(value)


@pytest.mark.parametrize('value', [.5, 1, 3, 6])
def test_distance_presets(value):
    assert laser_range(value) == value


@pytest.mark.parametrize('value', [True, None, 0, 2, float('nan'), 'bad'])
def test_distance_rejects_unlisted_values(value):
    with pytest.raises(ValueError):
        laser_range(value)


def test_settings_persist_and_failed_multi_update_does_not_partially_apply(tmp_path):
    path = tmp_path / 'settings.json'
    settings = MappingSettings(path)
    assert settings.snapshot() == {'turn_speed': .15, 'max_laser_range': 3.}
    settings.update(turn_speed=.6, max_laser_range=.5)
    assert MappingSettings(path).snapshot() == settings.snapshot()
    with pytest.raises(ValueError):
        settings.update(turn_speed=.2, max_laser_range=2)
    assert json.loads(path.read_text()) == settings.snapshot() == {'turn_speed': .6, 'max_laser_range': .5}


@pytest.mark.parametrize('mode', ['manual', 'mapping'])
@pytest.mark.parametrize('scale', [.15, .35, 1.])
def test_manual_turn_speed_is_independent_and_stop_gates_take_precedence(mode, scale):
    args = dict(mode=mode, emergency_stop=False, front_distance=5., detection='',
                manual_command='turn_l', lane_offset=0., has_recent_detection=False,
                has_recent_manual=True, has_recent_lane=False, speed_scale=scale,
                manual_turn_speed=.15)
    assert decide_motion(**args)['angular_z'] == .15
    assert decide_motion(**{**args, 'manual_command': 'turn_r'})['angular_z'] == -.15
    assert decide_motion(**{**args, 'emergency_stop': True})['angular_z'] == 0
    assert decide_motion(**{**args, 'has_recent_manual': False})['angular_z'] == 0
    if mode == 'mapping':
        assert decide_motion(**{**args, 'has_recent_scan': False})['angular_z'] == 0


def test_autonomous_turn_keeps_existing_scaled_policy():
    args = dict(mode='auto', emergency_stop=False, front_distance=5., detection='turn_left',
                manual_command='', lane_offset=0., has_recent_detection=True,
                has_recent_manual=False, has_recent_lane=False, speed_scale=.35, turn_speed=1.)
    assert decide_motion(**args, manual_turn_speed=.15)['angular_z'] == .35


def test_settings_api_preserves_current_map_and_reports_next_value(fake_node, tmp_path):
    fake_node.motion_settings = MappingSettings(tmp_path/'settings.json')
    fake_node.set_motion_settings = lambda changes: fake_node.motion_settings.update(**changes)
    fake_node.map_snapshot.update({'data': [0], 'session_id': 'existing-map'})
    client = TestClient(create_app(fake_node))
    for value in [.5, 1, 3, 6]:
        response = client.post('/api/mapping/settings', json={'max_laser_range': value})
        assert response.status_code == 200
        assert response.json()['settings']['max_laser_range'] == value
        assert client.get('/api/map').json()['session_id'] == 'existing-map'
    assert client.post('/api/mapping/settings', json={'turn_speed': .15}).status_code == 200
    assert client.get('/api/status').json()['motion_settings']['turn_speed'] == .15
    for payload in ({}, {'turn_speed': True}, {'max_laser_range': 2}, {'unexpected': 1}):
        assert client.post('/api/mapping/settings', json=payload).status_code == 422


def test_session_uses_its_own_range_snapshot_in_generated_parameters(monkeypatch, tmp_path):
    share = tmp_path/'share'
    (share/'config').mkdir(parents=True)
    source = share/'config/slam_toolbox.yaml'
    source.write_text(yaml.safe_dump({'slam_toolbox': {'ros__parameters': {'max_laser_range': 6., 'resolution': .05}}}))
    module = SimpleNamespace(get_package_share_directory=lambda name: str(share))
    monkeypatch.setitem(sys.modules, 'ament_index_python', SimpleNamespace(packages=module))
    monkeypatch.setitem(sys.modules, 'ament_index_python.packages', module)
    process = SimpleNamespace(pid=123, poll=lambda: None)
    calls=[]
    monkeypatch.setattr('smart_car_decision.mapping_session.subprocess.Popen', lambda args, **kw: calls.append(args) or process)
    recorder = SimpleNamespace(directory=tmp_path/'session')
    logger=SimpleNamespace(info=lambda *a:None)
    manager=MappingRestartManager(logger, MapSnapshotStore(), recorder=recorder)
    manager._state.update(session_id='testsession', max_laser_range=.5)
    manager._log_file=tmp_path/'slam.log'
    manager.settings.update(max_laser_range=1.)
    manager._start_slam()
    saved=yaml.safe_load((recorder.directory/'slam-params.yaml').read_text())['slam_toolbox']['ros__parameters']
    assert saved == {'max_laser_range': .5, 'resolution': .05}
    assert yaml.safe_load(source.read_text())['slam_toolbox']['ros__parameters']['max_laser_range'] == 6
    assert str(recorder.directory/'slam-params.yaml') in ' '.join(calls[0])


@pytest.mark.parametrize('missing_required', [False, True])
def test_recorder_full_topic_metadata_and_graceful_close(monkeypatch, tmp_path, missing_required):
    recorder=MappingInputRecorder(tmp_path)
    signals=[]
    class Process:
        pid=123
        returncode=None
        def poll(self): return self.returncode
        def wait(self, timeout):
            bag=recorder.directory/'inputs'
            bag.mkdir()
            omitted={'/imu/data_raw', '/odom'} if missing_required else {'/imu/data_raw'}
            counts=[{'topic_metadata': {'name': name}, 'message_count': 1} for name in INPUT_TOPICS if name not in omitted]
            (bag/'metadata.yaml').write_text(yaml.safe_dump({'rosbag2_bagfile_information': {'topics_with_message_count': counts}}))
            self.returncode=0
    def popen(args, **kwargs):
        assert '/tf_static' in args and '/odom_raw' in args and '/imu/data' in args
        kwargs['stdout'].write(''.join(f"Subscribed to topic '{topic}'\n" for topic in ('/tf_static','/scan',*INITIAL_CONTROL_TOPICS)).encode())
        return Process()
    monkeypatch.setattr('smart_car_decision.mapping_recording.subprocess.Popen', popen)
    monkeypatch.setattr('smart_car_decision.mapping_recording.os.killpg', lambda pid,sig:signals.append((pid,sig)), raising=False)
    recorder.start('session1', {'turn_speed': .15, 'max_laser_range': 3.})
    recorder.append_status({'map_pose': {'yaw': 1.}, 'odom': {'angular_speed': .15}})
    recorder.stop('mode_exit')
    summary=json.loads((recorder.directory/'session.json').read_text())
    assert summary['state']==('error' if missing_required else 'finished')
    assert summary['complete'] is (not missing_required)
    assert '/imu/data_raw' in summary['missing_topics']
    if missing_required:
        assert '/odom' in summary['error']
    assert summary['topic_counts']['/tf_static']==1
    assert 'map_pose' in (recorder.directory/'status.jsonl').read_text()
    recorder.stop('again')
    assert len(signals)==1


def test_recorder_start_failure_is_explicit(monkeypatch, tmp_path):
    def fail(*a, **kw): raise FileNotFoundError('ros2 bag missing')
    monkeypatch.setattr('smart_car_decision.mapping_recording.subprocess.Popen', fail)
    recorder=MappingInputRecorder(tmp_path)
    with pytest.raises(RuntimeError, match='ros2 bag missing'):
        recorder.start('session1', {})
    assert recorder.snapshot()['state']=='error'
    assert recorder.snapshot()['complete'] is False


def test_recorder_startup_is_ordered_before_slam_and_failure_is_not_ready(monkeypatch, tmp_path):
    events=[]
    class Recorder:
        directory=tmp_path
        def start(self, session, settings): events.append(('record', settings['max_laser_range']))
        def stop(self, reason, error=None): events.append(('stop',reason))
        def snapshot(self): return {'state':'recording','error':None}
    recorder=Recorder()
    logger=SimpleNamespace(info=lambda *a:None,error=lambda *a:None)
    manager=MappingRestartManager(logger,MapSnapshotStore(),recorder=recorder,
                                  capture_initial_inputs=lambda:events.append(('initial_controls',1)))
    manager.settings.update(max_laser_range=1.)
    monkeypatch.setattr(manager,'_stop_existing_slam',lambda:None)
    monkeypatch.setattr(manager,'_start_slam',lambda:events.append(('slam',1)) or SimpleNamespace(pid=123,poll=lambda:None))
    manager.restart()
    assert events[:3]==[('record',1.),('initial_controls',1),('slam',1)]
    assert manager.snapshot()['max_laser_range']==1.
    manager.settings.update(max_laser_range=6.)
    assert manager.snapshot()['max_laser_range']==1.
    assert manager.snapshot()['configured_max_laser_range']==6.
    def fail(*a):raise RuntimeError('recorder unavailable')
    monkeypatch.setattr(recorder,'start',fail)
    with pytest.raises(RuntimeError,match='recorder unavailable'):
        manager.restart()
    assert manager.snapshot()['state']=='error'
    assert events[-1][0]=='stop'


def test_generic_mode_entry_cannot_bypass_complete_input_recording(fake_node):
    fake_node.mapping_recorder=SimpleNamespace(snapshot=lambda:{'state':'finished'})
    client=TestClient(create_app(fake_node))
    response=client.post('/api/mode',json={'mode':'mapping'})
    assert response.status_code==409 and '开始建图' in response.json()['detail']
    assert fake_node.store.snapshot()['mode']=='stop'
    assert client.post('/api/mode',json={'mode':'manual'}).status_code==200
