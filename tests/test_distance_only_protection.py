import json
import math
from pathlib import Path
from types import SimpleNamespace as N

import pytest

from smart_car_decision.avoidance import AvoidanceController, ScanEvidence, ZERO
from smart_car_decision.footprint import Rectangle
from smart_car_decision.local_collision_guard import local_guard
from test_avoidance import scene
from test_avoidance_adapter import controller
from test_basic_protection import ready, drive


@pytest.fixture
def captured():
    raw=json.loads((Path(__file__).parent/'fixtures/basic-protection-scan-20261116.json').read_text(encoding='utf-8'))
    scan=N(**{k:raw[k] for k in ('angle_min','angle_increment','range_min','range_max')},
           ranges=[float(v) for v in raw['ranges']],header=N(stamp=N(**raw['stamp'])))
    footprint=Rectangle(**raw['profile']['rectangle'])
    evidence=ScanEvidence(scan,raw['transform'],raw['profile'].get('self_returns',()),footprint,
                          .01,raw['provenance']['kinds'],assume_missing_clear=False)
    return evidence,footprint


@pytest.mark.parametrize('motion', [{**ZERO,'linear_x':.042},{**ZERO,'linear_x':-.042},
    {**ZERO,'linear_y':.042},{**ZERO,'linear_y':-.042},{**ZERO,'angular_z':.05},{**ZERO,'angular_z':-.05}])
def test_real_scan_gap_does_not_lock_basic_but_full_requires_observation(captured,motion):
    evidence,f=captured
    original=list(evidence.visibility_ranges)
    basic=AvoidanceController(f.radius);basic.footprint=f
    result=local_guard(basic,motion,evidence=evidence,scan_age=.1,speed=0.,angular=.004,velocity_age=.1)
    assert any(result.values())
    full=AvoidanceController(f.radius);full.footprint=f;full.actual_speed=0.;full.scan_age=.1
    assert full.guard(motion,evidence,f.radius+.05)==ZERO
    assert full.state=='waiting_observation'
    assert evidence.visibility_ranges==original and not evidence.assumed_clear['rays']


def test_actual_obstacle_still_blocks_and_safe_reverse_remains_available():
    c=AvoidanceController();c.footprint=Rectangle(.0935,.1565,.1)
    e=scene(obstacles=((.13,0,.01),))
    assert local_guard(c,{**ZERO,'linear_x':.042},evidence=e,scan_age=.1,speed=0.,angular=0.,velocity_age=.1)==ZERO
    assert c.coverage['kind']=='obstacle'
    assert local_guard(c,{**ZERO,'linear_x':-.042},evidence=e,scan_age=.1,speed=0.,angular=0.,velocity_age=.1)['linear_x']<0


def test_whole_scan_failure_is_not_confused_with_normal_gaps():
    e=scene(obstacles=());e.rays=[None]*len(e.rays)
    c=AvoidanceController()
    assert local_guard(c,{**ZERO,'linear_x':.05},evidence=e,scan_age=.1,speed=0.,angular=0.,velocity_age=.1)==ZERO
    assert c.state=='sensor_fault'


def test_enabled_detour_does_not_require_pose_for_clear_basic_motion(controller,captured):
    c=controller;identity=ready(c);c.avoidance.settings['enabled']=True
    c.scan_evidence,c.avoidance.footprint=captured
    c.pose=c.evidence_pose=None
    assert drive(c,identity,'backward',1)[0]<0
    assert c.sensors_ready(100.)


def test_failed_first_motion_keeps_original_intent_in_diagnostics(controller):
    from smart_car_decision.motion_diagnostics import MotionDiagnostics
    c=controller;identity=ready(c)
    class Sink:
        enabled=True
        def __init__(self):self.events=[]
        def emit(self,kind,reason,**values):self.events.append((kind,reason,values))
    sink=Sink();c.motion_diagnostics=MotionDiagnostics(sink)
    c.scan_evidence=scene(obstacles=((.13,0,.01),))
    assert drive(c,identity,'forward',1)==(0,0,0)
    events=[v for v in sink.events if v[0]=='motion.blocked']
    assert events and events[0][2]['details']['command']=='forward'
