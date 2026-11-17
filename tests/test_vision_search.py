import asyncio
import json
import time
from types import SimpleNamespace as NS

import pytest

from smart_car_decision.search_control import SearchGate
from smart_car_decision.vision_search import Confirmation, associate_clutter, targets
from smart_car_decision.scan_provenance import visibility


def test_controller_lease_expiry_latches_and_old_messages_cannot_release():
    gate=SearchGate()
    def send(version,op,stationary=True,**extra):
        return gate.update({'controller_id':gate.instance_id,'run_id':'a','version':version,'op':op,**extra},0.,stationary)
    assert not send(0,'arm',False)
    assert send(0,'arm') and gate.blocked(.1)
    assert send(1,'resume') and not gate.blocked(.2)
    assert gate.blocked(1.1)
    assert not send(2,'heartbeat')
    assert not send(0,'release')
    assert not send(3,'release',False)
    assert not send(3,'resume',controller_id='old-controller')
    assert send(4,'release') and not gate.blocked(2.)


def test_unknown_task_cannot_takeover_and_old_run_cannot_release():
    gate=SearchGate()
    message={'controller_id':gate.instance_id,'run_id':'a','version':1,'op':'arm'}
    assert gate.update(message,0.,True)
    assert not gate.update({**message,'run_id':'b','version':100,'op':'release'},0.,True)
    assert not gate.update({**message,'run_id':'b','version':100},0.,True)


def test_old_search_failure_never_stops_new_manual_owner(service):
    service.search.update(state='searching', run_id='old', travel='patrol',
                          gate_control_epoch='old-epoch', control_lease={'controller_id':'c','control_epoch':'old-epoch','owner':'search'})
    service.node.control_lease_ack = {'controller_id':'c','control_epoch':'new-epoch','owner':'manual'}
    service.node.search_ack = {'controller_id':'search-controller'}
    service.node.set_mode('manual')
    service._hold('fault', 'late old failure')
    assert service.node.store.snapshot()['mode'] == 'manual'
    assert service.messages[-1]['control_epoch'] == 'old-epoch'


def test_targets_use_explicit_english_and_expand_presets():
    assert targets([{'name':'服务器'}])[0]['prompt']=='server rack'
    assert len(targets([{'name':'实验器材'}]))==3
    with pytest.raises(ValueError):targets([{'name':'某种特殊设备'}])
    with pytest.raises(ValueError):targets([{'name':'设备','prompt':'a; shell'}])


def test_confirmation_requires_unique_fresh_frames_and_same_object():
    confirm=Confirmation(); d={'key':'rack:1','confidence':.8}
    assert confirm.observe(1,0.,0.,[d]) is None
    assert confirm.observe(1,.2,.2,[d]) is None
    assert confirm.observe(2,.2,.2,[d]) is None
    assert confirm.observe(3,.4,.4,[d])==d
    assert confirm.observe(4,0.,2.,[d]) is None
    other=Confirmation()
    for i in range(5):assert other.observe(i,i*.2,i*.2,[{**d,'key':str(i)}]) is None


def test_lidar_projection_needs_calibration_timing_and_corridor():
    calibration={'intrinsics':[100,100,320,240],'image_size':[640,480],
                 'base_to_camera':[0,-1,0,0, 0,0,-1,0, 1,0,0,0]}
    box=[300,220,340,260]
    assert associate_clutter(box,[(1.,0.,0.)],calibration,[640,480],1.,1.)['points']==1
    assert associate_clutter(box,[(1.,0.,0.)],calibration,[640,480],1.,.7) is None
    assert associate_clutter(box,[(1.,.4,0.)],calibration,[640,480],1.,1.) is None
    assert associate_clutter(box,[(1.,0.,0.)],None,[640,480],1.,1.) is None


def test_infinity_never_proves_free_without_verified_driver_semantics():
    scan=NS(ranges=[float('inf'),float('inf'),1.],range_max=8.,header=NS(frame_id='laser',stamp=NS(sec=1,nanosec=0)))
    packet={'stamp':[1,0],'frame_id':'laser','kinds':['no_return','unsampled','hit'],'healthy':True,'driver_sha256':'d'}
    assert visibility(scan,None,{})[0]=={}
    assert visibility(scan,packet,{})[0]=={}
    profile={'verified':True,'driver_sha256':'d','evidence_sha256':'e','usable_range_m':3.}
    assert visibility(scan,packet,profile)[0]=={0:3.}
    assert visibility(scan,{**packet,'stamp':[2,0]},profile)[0]=={}
    assert visibility(scan,{**packet,'healthy':False},profile)[0]=={}


@pytest.fixture
def service(tmp_path,monkeypatch):
    from smart_car_decision.vision_service import VisionService
    from smart_car_decision.web_video import AnnotatedFrameStore
    import queue
    monkeypatch.setattr('smart_car_decision.vision_service.mp.get_context',lambda _:NS(Queue=queue.Queue))
    state={'mode':'stop','odom':{'ok':True,'odom_age_sec':0.,'linear_speed':0.,'linear_speed_xy':0.,'angular_speed':0.},'map_pose':{'ok':False}}
    node=NS(store=NS(snapshot=lambda:dict(state)),ros_status_age_sec=lambda:0.,search_ack={},
            annotated_frames=AnnotatedFrameStore(),navigation_tasks=None,navigation=None)
    node.control_lease_ack={"controller_id":"c", "control_epoch":"e", "owner":None}
    node.set_mode=lambda mode:state.update(mode=mode)
    messages=[];node.publish_search_control=lambda value:messages.append(value)
    value=VisionService(node,NS(),tmp_path,start_worker=False)
    value.messages=messages
    return value


def test_unverified_model_never_starts_motion(service):
    with pytest.raises(RuntimeError,match='性能'):
        asyncio.run(service.start({'targets':[{'name':'服务器'}]}))
    assert service.node.store.snapshot()['mode']=='stop'


def test_stationary_search_keeps_lock_and_retries_use_same_record(service):
    service.status.update(state="running", mobile_ready=False)
    payload = {"run_id": "stationary-1", "targets": [{"name": "服务器"}], "travel": "stationary"}
    original_publish = service.node.publish_search_control

    def acknowledge(value):
        original_publish(value)
        service.node.search_ack = {
            "controller_id": "test", "run_id": value["run_id"], "active": True, "held": True,
            "received_at": time.monotonic(),
        }
        service.status["run_id"] = value["run_id"]
        service.result_at = time.monotonic()

    service.node.search_ack = {"controller_id": "test"}
    service.node.publish_search_control = acknowledge

    async def scenario():
        first = await service.start(payload)
        assert first["state"] == "searching"
        assert service.node.store.snapshot()["mode"] == "stop"
        assert [message["op"] for message in service.messages] == ["arm"]
        service._supervise_search(time.monotonic())
        assert await service.start(payload) == first
        with pytest.raises(RuntimeError, match="请求已变化"):
            await service.start({**payload, "targets": [{"name": "实验器材"}]})
        stopped = await service.action({"action": "cancel", "run_id": payload["run_id"]})
        assert stopped["state"] == "cancelled" and stopped["version"] > first["version"]
        assert await service.start(payload) == stopped
        assert service._read_run(payload["run_id"]) == stopped

    asyncio.run(scenario())


def test_cancel_before_search_prevents_delayed_dispatch(service):
    async def scenario():
        tombstone = await service.action({"action": "cancel", "run_id": "late"})
        result = await service.start({"run_id": "late", "targets": [{"name": "服务器"}]})
        assert result == tombstone == service.search_snapshot_for("late")
        assert not service.messages

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["planning", "dwelling", "running"])
def test_patrol_search_allows_matching_long_running_station_transition(service, phase):
    now = time.monotonic()
    service.search.update(state="searching", run_id="route", travel="patrol")
    service.route_id, service.at, service.result_at = "route", now-60, now
    service.node.search_ack = {"active": True, "held": False, "run_id": "route", "received_at": now}
    service.node.navigation_tasks = NS(snapshot=lambda: {"state": phase, "run_id": "route", "goal_id": "g"})
    service.node.navigation = NS(snapshot=lambda: {"state": "succeeded", "goal_id": "g"})
    service._supervise_search(now)
    assert service.search["state"] == "searching"


def test_settings_stationary_guard_and_no_false_enable(service):
    service.configure({'clutter_enabled':False})
    assert not service.settings()['clutter_enabled']
    assert not service.snapshot()['mobile_ready']
    service.node.set_mode('manual')
    with pytest.raises(RuntimeError):service.configure({'enabled':False})


def test_search_hit_stops_before_evidence_io_and_keeps_latch_on_failure(service,monkeypatch):
    from smart_car_decision.vision_search import vocabulary_id
    service.search.update(state='searching',run_id='task',gate_control_epoch='e',targets=[{'name':'机柜','prompt':'server rack'}],travel='auto')
    service.node.search_ack={'controller_id':'controller'}
    service.node.set_mode('auto')
    def broken(*args):
        assert service.node.store.snapshot()['mode']=='stop'
        assert service.messages[-1]['op']=='hold'
        raise OSError('disk full')
    monkeypatch.setattr(service.outbox,'put',broken)
    start=time.monotonic()
    for i in range(3):
        now=start+i*.2
        monkeypatch.setattr('smart_car_decision.vision_service.time.monotonic',lambda:now)
        service._result({'version':vocabulary_id(service._prompts()),'run_id':'task','sequence':i,'captured_mono':now,
            'captured_at':time.time(),'detections':[{'key':'rack:1','label':'server rack','confidence':.9,'box':[0,0,10,10]}],
            'model_sha256':'model','inference_ms':10,'image_size':[640,480],'original':b'original','annotated':b'annotated'})
    assert service.search['state']=='stopping'
    assert service.desired_gate=='hold'
    assert 'save_error' in service.search['evidence']


def test_wrong_vocabulary_or_task_results_are_ignored(service):
    service._result({'version':'old','run_id':'old'})
    assert service.result_at==0


def test_ordinary_objects_keep_overlay_without_creating_incidents(service,monkeypatch):
    from datetime import datetime
    from smart_car_decision.vision_search import vocabulary_id
    start=time.monotonic()
    for i in range(16):
        now=start+i*.25
        monkeypatch.setattr('smart_car_decision.vision_service.time.monotonic',lambda:now)
        service._result({'version':vocabulary_id(service._prompts()),'run_id':None,'sequence':i,
            'captured_mono':now,'captured_at':time.time(),'model_sha256':'real-model-hash',
            'inference_ms':10,'image_size':[640,480],'original':b'original','annotated':b'jpeg',
            'detections':[{'key':'box:'+str(i//4),'type':'cardboard box','label':'cardboard box',
                           'confidence':.9,'box':[100,100,300,300]}]})
    events=service.outbox.pending()
    assert events==[]
    assert service._overlay['jpeg']==b'jpeg'


def test_shared_safety_outbox_exposes_and_acknowledges_yolo_events(service,fake_node):
    from fastapi.testclient import TestClient
    from smart_car_decision.web_api import create_app
    fake_node.vision_service=service
    service.outbox.put({'event_id':'vision-event','type':'suspected_clutter'},b'jpeg')
    with TestClient(create_app(fake_node)) as client:
        assert any(e['event_id']=='vision-event' for e in client.get('/api/safety/events').json()['events'])
        assert client.post('/api/safety/events/ack',json={'event_ids':['vision-event']}).status_code==200
        assert service.outbox.pending()==[]


def test_patrol_search_arms_before_start_and_cancels_route(service):
    service.status.update(state='running',mobile_ready=True)
    service.node.avoidance_service=NS(snapshot=lambda:{'confirmed':True,'available':True})
    service.node.search_ack={'controller_id':'controller'}
    actions = []

    async def create(spec):
        return {"run_id": spec["run_id"], "state": "prepared"}

    async def action(value):
        actions.append(value)

    service.node.navigation_tasks = NS(active=False, _lease_valid=lambda identity: bool(identity),
                                       create=create, action=action, snapshot=lambda: {"run_id": "route", "state": "prepared"})
    def publish(value):
        service.messages.append(value)
        service.node.search_ack={**value,'active':value['op']!='release','held':value['op'] not in {'resume','heartbeat'},'received_at':time.monotonic()}
        service.status['run_id']=value['run_id'];service.result_at=time.monotonic()
    service.node.publish_search_control=publish
    async def exercise():
        state=await service.start({'run_id': 'route', 'targets':[{'name':'服务器'}],
                                   'travel': 'patrol', 'control_lease': {'owner': 'host'}})
        assert state['state']=='searching'
        assert [m['op'] for m in service.messages[:2]]==['arm','resume']
        assert actions[0] == {'run_id': 'route', 'action': 'start', 'control_lease': {'owner': 'host'}}
        await service.action({'run_id':state['run_id'],'action':'pause'})
        assert service.search['state']=='paused' and service.node.store.snapshot()['mode']=='stop'
        await service.action({'run_id':state['run_id'],'action':'cancel'})
        assert service.search['state']=='cancelled' and service.desired_gate=='hold'
        assert actions[-1]['action'] == 'cancel'
    asyncio.run(exercise())


def test_cancel_during_prepare_never_starts_motion(service):
    service.status.update(state='running',mobile_ready=True)
    service.node.avoidance_service=NS(snapshot=lambda:{'confirmed':True,'available':True})
    service.node.search_ack={'controller_id':'controller'}
    async def exercise():
        task=asyncio.create_task(service.start({'targets':[{'name':'服务器'}]}))
        await asyncio.sleep(.06)
        await service.action({'run_id':service.search['run_id'],'action':'cancel'})
        with pytest.raises(RuntimeError):await task
        assert service.node.store.snapshot()['mode']=='stop'
        assert not any(m['op']=='resume' for m in service.messages)
    asyncio.run(exercise())


def test_api_old_vehicle_and_settings_conflict(fake_node):
    from fastapi.testclient import TestClient
    from smart_car_decision.web_api import create_app
    with TestClient(create_app(fake_node)) as client:
        assert client.get('/api/vision/status').status_code==501
        assert client.post('/api/search/start',json={}).status_code==501


def test_driver_patch_preserves_unknown_and_publishes_matching_evidence():
    import importlib.util
    from pathlib import Path
    spec=importlib.util.spec_from_file_location('provenance_patch',Path(__file__).resolve().parents[1]/'scripts/prepare_scan_provenance_patch.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    source='\n'.join(['#include <sensor_msgs/msg/laser_scan.hpp>','scan_msg->ranges.resize(node_count);',
        'pub->publish(*scan_msg);','int angle_compensate_offset = 0;','if (nodes[i].dist_mm_q2 != 0) {',
        'size_t   count = _countof(nodes);','rclcpp::Publisher<sensor_msgs::msg::LaserScan>::SharedPtr scan_pub;'])
    result=module.instrument(source)
    assert 'scan_sampled_.assign' in result and '"unsampled" : "unknown"' in result
    assert result.index('scan_provenance_pub_->publish(packet)')<result.index('pub->publish(*scan_msg)')
    assert '"no_return"' not in result
    with pytest.raises(ValueError):module.instrument(result)
    with pytest.raises(ValueError):module.instrument('unknown version')
